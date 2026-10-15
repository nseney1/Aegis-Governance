"""Unit tests for v3.3.0 Phase 3.3.3: Segmented Telemetry Compaction & SARIF 2.1.0 Output."""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import gzip
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from aegis_cli.check import CheckCommand, run_check
from aegis_cli.verify import VerifyCommand, format_sarif_report, run_verify
from aegis_core.telemetry import (
    compact_signals,
    compute_cell_fitness,
    get_rule_stats,
    invalidate_signals_cache,
    load_checkpoint_rollup,
    load_signals,
)


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = "".join(json.dumps(r) + "\n" for r in records)
    path.write_text(content, encoding="utf-8")


class TestSegmentedTelemetryCompaction:
    """Verify compact_signals partitions, archives, rolls up, and preserves priors."""

    def test_compact_archives_expired_and_preserves_priors(self, tmp_path: Path):
        now = datetime.now(timezone.utc)
        old_ts_1 = (now - timedelta(days=45)).strftime("%Y-%m-%dT%H:%M:%SZ")
        old_ts_2 = (now - timedelta(days=60)).strftime("%Y-%m-%dT%H:%M:%SZ")
        recent_ts = (now - timedelta(days=5)).strftime("%Y-%m-%dT%H:%M:%SZ")

        records = [
            {"timestamp": old_ts_1, "cell": "rule-alpha", "signal": "tp", "source": "session"},
            {"timestamp": old_ts_1, "cell": "rule-alpha", "signal": "tp", "source": "session"},
            {"timestamp": old_ts_2, "cell": "rule-alpha", "signal": "fp", "source": "session"},
            {"timestamp": old_ts_2, "cell": "rule-beta", "signal": "fn", "source": "ci"},
            {"timestamp": recent_ts, "cell": "rule-alpha", "signal": "tp", "source": "session"},
            {"timestamp": "not-a-valid-ts", "cell": "rule-beta", "signal": "tp", "source": "manual"},
        ]

        signals_file = tmp_path / ".aegis" / "telemetry" / "signals.jsonl"
        _write_jsonl(signals_file, records)
        invalidate_signals_cache()

        # Capture stats and fitness BEFORE compaction
        stats_before_alpha = get_rule_stats(tmp_path, "rule-alpha")
        stats_before_beta = get_rule_stats(tmp_path, "rule-beta")
        fitness_before_alpha = compute_cell_fitness(tmp_path, "rule-alpha")
        fitness_before_beta = compute_cell_fitness(tmp_path, "rule-beta")
        cell_fitness_before = compute_cell_fitness({"id": "rule-alpha"}, workspace=tmp_path)

        assert stats_before_alpha["helped"] == 3
        assert stats_before_alpha["harmed"] == 1
        assert stats_before_alpha["applied"] == 4
        assert stats_before_beta["helped"] == 1
        assert stats_before_beta["ignored"] == 1

        # Execute compaction (30-day retention)
        res = compact_signals(workspace=tmp_path, retention_days=30, dry_run=False)
        assert res["expired_count"] == 4
        assert res["retained_count"] == 2
        assert res["compacted_count"] == 4

        # Verify active signals.jsonl contains only the 2 retained records
        remaining = load_signals(tmp_path)
        assert len(remaining) == 2
        assert remaining[0]["timestamp"] == recent_ts
        assert remaining[1]["timestamp"] == "not-a-valid-ts"

        # Verify checkpoint_rollup.json contents
        rollup_path = tmp_path / ".aegis" / "telemetry" / "checkpoint_rollup.json"
        assert rollup_path.is_file()
        rollup = load_checkpoint_rollup(tmp_path)
        assert rollup["compacted_count"] == 4
        assert rollup["last_compacted_at"]
        assert rollup["rules"]["rule-alpha"]["helped"] == 2
        assert rollup["rules"]["rule-alpha"]["harmed"] == 1
        assert rollup["rules"]["rule-alpha"]["applied"] == 3
        assert rollup["rules"]["rule-alpha"]["alpha_delta"] == 2.0
        assert rollup["rules"]["rule-alpha"]["beta_delta"] == 1.0
        assert rollup["rules"]["rule-beta"]["ignored"] == 1

        # Verify .jsonl.gz archive exists and decompresses to the 4 expired records
        archive_dir = tmp_path / ".aegis" / "telemetry" / "archive"
        gz_files = sorted(archive_dir.glob("signals-*.jsonl.gz"))
        assert len(gz_files) >= 1
        archived_records = []
        for gz in gz_files:
            with gzip.open(gz, "rt", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        archived_records.append(json.loads(line))
        assert len(archived_records) == 4

        # Verify Thompson Sampling priors and rule stats AFTER compaction match BEFORE exactly
        stats_after_alpha = get_rule_stats(tmp_path, "rule-alpha")
        stats_after_beta = get_rule_stats(tmp_path, "rule-beta")
        fitness_after_alpha = compute_cell_fitness(tmp_path, "rule-alpha")
        fitness_after_beta = compute_cell_fitness(tmp_path, "rule-beta")
        cell_fitness_after = compute_cell_fitness({"id": "rule-alpha"}, workspace=tmp_path)

        assert stats_after_alpha == stats_before_alpha
        assert stats_after_beta == stats_before_beta
        assert fitness_after_alpha == pytest.approx(fitness_before_alpha)
        assert fitness_after_beta == pytest.approx(fitness_before_beta)
        assert cell_fitness_after == pytest.approx(cell_fitness_before)

    def test_compact_dry_run_does_not_mutate_files(self, tmp_path: Path):
        old_ts = (datetime.now(timezone.utc) - timedelta(days=50)).strftime("%Y-%m-%dT%H:%M:%SZ")
        signals_file = tmp_path / ".aegis" / "telemetry" / "signals.jsonl"
        _write_jsonl(signals_file, [{"timestamp": old_ts, "cell": "rule-x", "signal": "tp", "source": "ci"}])

        res = compact_signals(workspace=tmp_path, retention_days=30, dry_run=True)
        assert res["dry_run"] is True
        assert res["expired_count"] == 1
        assert res["retained_count"] == 0
        assert len(load_signals(tmp_path)) == 1
        assert not (tmp_path / ".aegis" / "telemetry" / "checkpoint_rollup.json").exists()


class TestSarifOutput:
    """Verify `aegis check --format sarif` and `format_sarif_report`."""

    def test_check_parser_accepts_sarif_format(self):
        cmd = CheckCommand()
        parser = argparse.ArgumentParser()
        cmd.configure_parser(parser)
        args = parser.parse_args(["--format", "sarif", "foo.py"])
        assert args.format == "sarif"

        vcmd = VerifyCommand()
        vparser = argparse.ArgumentParser()
        vcmd.configure_parser(vparser)
        vargs = vparser.parse_args(["--format", "sarif", "--files", "foo.py"])
        assert vargs.format == "sarif"

    def test_check_sarif_output_on_passing_run(self, tmp_path: Path, capsys):
        (tmp_path / ".aegis" / "rules").mkdir(parents=True)
        sample = tmp_path / "clean_mod.py"
        sample.write_text("def greet(name: str) -> str:\n    return f'hello {name}'\n", encoding="utf-8")

        passed_results = [
            SimpleNamespace(tool="syntax_check", target="clean_mod.py", verdict=True, detail="OK"),
            SimpleNamespace(tool="import_guard", target="clean_mod.py", verdict=True, detail="All imports valid"),
        ]
        args = argparse.Namespace(
            target_files=["clean_mod.py"],
            files=None,
            hook=False,
            full=False,
            release=False,
            release_gate=False,
            checkpoint_only=False,
            plan=None,
            plan_file=None,
            workspace=str(tmp_path),
            json=False,
            format="sarif",
        )
        with patch("aegis_core.verification.runner.run_layer1", return_value=passed_results), \
             patch("aegis_core.verification.runner.gate_verdict", return_value=True), \
             patch("aegis_core.verification.runner.format_summary", return_value="Layer 1: PASS"):
            rc = run_check(args)

        assert rc == 0
        raw_out = capsys.readouterr().out
        sarif = json.loads(raw_out)
        assert sarif["$schema"] == "https://json.schemastore.org/sarif-2.1.0.json"
        assert sarif["version"] == "2.1.0"
        assert len(sarif["runs"]) == 1
        run_obj = sarif["runs"][0]
        assert run_obj["tool"]["driver"]["name"] == "Aegis Guardrails"
        assert run_obj["results"] == []

    def test_check_sarif_output_on_failing_run(self, tmp_path: Path, capsys):
        (tmp_path / ".aegis" / "rules").mkdir(parents=True)
        broken = tmp_path / "broken_mod.py"
        broken.write_text("def broken(\n", encoding="utf-8")

        failed_results = [
            SimpleNamespace(
                tool="syntax_check",
                target="broken_mod.py",
                verdict=False,
                detail="SyntaxError: unexpected EOF while parsing",
            ),
            SimpleNamespace(
                tool="import_guard",
                target="broken_mod.py",
                verdict=True,
                detail="Skipped",
            ),
        ]
        args = argparse.Namespace(
            target_files=["broken_mod.py"],
            files=None,
            hook=False,
            full=False,
            release=False,
            release_gate=False,
            checkpoint_only=False,
            plan=None,
            plan_file=None,
            workspace=str(tmp_path),
            json=False,
            format="sarif",
        )
        with patch("aegis_core.verification.runner.run_layer1", return_value=failed_results), \
             patch("aegis_core.verification.runner.gate_verdict", return_value=False), \
             patch("aegis_core.verification.runner.format_summary", return_value="Layer 1: FAIL"):
            rc = run_check(args)

        assert rc == 1
        raw_out = capsys.readouterr().out
        sarif = json.loads(raw_out)
        assert sarif["version"] == "2.1.0"
        results_list = sarif["runs"][0]["results"]
        assert len(results_list) == 1
        item = results_list[0]
        assert item["ruleId"] == "syntax_check"
        assert item["level"] == "error"
        assert item["message"] == {"text": "SyntaxError: unexpected EOF while parsing"}
        assert item["locations"] == [
            {"physicalLocation": {"artifactLocation": {"uri": "broken_mod.py"}}}
        ]

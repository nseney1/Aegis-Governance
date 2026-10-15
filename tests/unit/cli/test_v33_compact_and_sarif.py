"""Unit tests for v3.3.0 Phase 3.3.3: segmented telemetry compaction.

SARIF output was removed in v4 (#40) and `aegis system compact` with the
`system` command (D5); the core compaction behavior stays tested here.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import gzip
import json
from pathlib import Path

import pytest

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



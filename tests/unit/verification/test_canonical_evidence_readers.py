"""Cross-reader contract tests for canonical signal evidence."""
from __future__ import annotations

import argparse
import importlib
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

from aegis_core.yaml import dump_frontmatter
import pytest

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").exists())
ENZYMES = ROOT / "enzymes"
if str(ENZYMES) not in sys.path:
    sys.path.insert(0, str(ENZYMES))


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(record) + "\n" for record in records), encoding="utf-8")


def _signal(cell: str, signal: str, timestamp: str = "2026-01-01T00:00:00Z", weight=None) -> dict:
    record = {"cell": cell, "signal": signal, "timestamp": timestamp}
    if weight is not None:
        record["metadata"] = {"credit_weight": weight}
    return record


def _cell(path: Path, cell_id: str, cell_type: str = "trap", age_days: int = 45) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    created = (datetime.now() - timedelta(days=age_days)).strftime("%Y-%m-%d")
    metadata = {
        "id": cell_id,
        "domain": "testing",
        "type": cell_type,
        "enforcement": "gate" if cell_type in ("wall", "invariant") else "advisory",
        "created": created,
        "expiry_days": 365,
        "expiry_sessions": 365,
    }
    path.write_text(dump_frontmatter(metadata, body=f"# {cell_id}\n"), encoding="utf-8")


def test_aggregate_signals_reports_errors_preserves_dimensions_and_weights(tmp_path):
    from aegis_core.evidence import aggregate_signals

    evidence = tmp_path / ".aegis" / "evidence"
    evidence.mkdir(parents=True)
    (evidence / "signals.jsonl").write_text(
        json.dumps(_signal("outcome-only", "tp", weight="0.25")) + "\n"
        + json.dumps(_signal("outcome-only", "fp", weight="0.5")) + "\n"
        + json.dumps(_signal("triggered", "trigger")) + "\n"
        + "{malformed}\n",
        encoding="utf-8",
    )
    _write_jsonl(evidence / "fitness.jsonl", [{"cell_id": "legacy", "triggered_at": "x"}])
    _write_jsonl(evidence / "outcomes.jsonl", [{"cell_id": "legacy", "outcome": "tp"}])

    result = aggregate_signals(str(evidence))
    assert result.counts["outcome-only"] == {
        "triggers": 0,
        "tp": 0.25,
        "fp": 0.5,
        "last_trigger": None,
        "has_triggers": False,
        "has_outcomes": True,
    }
    assert result.counts["triggered"]["has_triggers"] is True
    assert "legacy" not in result.counts
    assert result.errors and result.errors[0]["line"] == 4


def test_sync_fails_on_malformed_complete_signal_row(tmp_path, monkeypatch, capsys):
    import aegis_cli.sync as sync

    evidence = tmp_path / ".aegis" / "evidence"
    evidence.mkdir(parents=True)
    (tmp_path / ".aegis" / "rules").mkdir(parents=True)
    (evidence / "signals.jsonl").write_text("{bad}\n", encoding="utf-8")
    monkeypatch.setattr(sync, "resolve_root", lambda _args: tmp_path)

    assert sync.run_sync(argparse.Namespace(dry_run=False, json=True)) == 1
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "error"
    assert output["errors"][0]["line"] == 1


def test_report_and_status_use_canonical_triggers_not_legacy(tmp_path, capsys):
    from aegis_cli.report import run_report
    from aegis_cli.status import run_status

    (tmp_path / "genome").mkdir()
    (tmp_path / "genome" / "canonical.md").write_text("# canonical\n", encoding="utf-8")
    evidence = tmp_path / ".aegis" / "evidence"
    _write_jsonl(evidence / "signals.jsonl", [
        _signal("canonical", "trigger", "2026-01-01T00:00:00Z"),
        _signal("canonical", "trigger", "2026-01-01T00:01:00Z"),
    ])
    _write_jsonl(evidence / "fitness.jsonl", [{"cell_id": "legacy", "triggered_at": "2026-01-01T00:00:00Z"}])

    assert run_report(argparse.Namespace(session=-1, _root=tmp_path)) == 0
    report_output = capsys.readouterr().out
    assert "canonical" in report_output and "2 fires" in report_output
    assert "legacy" not in report_output

    assert run_status(argparse.Namespace(_root=tmp_path)) == 0
    status_output = capsys.readouterr().out
    canonical_line = next(line for line in status_output.splitlines() if "canonical" in line)
    assert canonical_line.split()[1] == "2"


def test_lifecycle_uses_weighted_canonical_signals(tmp_path):
    from aegis_core.lifecycle import evaluate_promotions

    cells = tmp_path / ".aegis" / "rules" / "traps"
    _cell(cells / "canonical.md", "canonical")
    evidence = tmp_path / ".aegis" / "evidence"
    signals = [_signal("canonical", "trigger", f"2026-01-01T00:{index:02d}:00Z") for index in range(20)]
    signals += [_signal("canonical", "tp", weight="0.5") for _ in range(34)]
    _write_jsonl(evidence / "signals.jsonl", signals)
    _write_jsonl(evidence / "outcomes.jsonl", [{"cell_id": "canonical", "outcome": "fp"}] * 100)

    candidates = evaluate_promotions(str(tmp_path))
    assert candidates[0]["cell_id"] == "canonical"
    assert candidates[0]["tp_rate"] == 0.85


def test_checkpoint_fails_closed_and_uses_weighted_outcomes(tmp_path):
    from aegis_core.verification.checkpoint_checks import check_cell_fitness

    evidence = tmp_path / ".aegis" / "evidence"
    evidence.mkdir(parents=True)
    (evidence / "signals.jsonl").write_text(
        json.dumps(_signal("weighted", "tp", weight="0.5")) + "\n"
        + json.dumps(_signal("weighted", "fp", weight="1.5")) + "\n"
        + "not-json\n",
        encoding="utf-8",
    )
    _write_jsonl(evidence / "outcomes.jsonl", [{"cell_id": "weighted", "outcome": "tp"}] * 10)

    issues = check_cell_fitness(tmp_path)
    assert any("parse" in issue["message"].lower() for issue in issues)
    assert any(issue.get("cell_id") == "weighted" and "75%" in issue["message"] for issue in issues)


def test_owned_production_has_no_active_legacy_evidence_paths():
    production = [
        p for p in [
            ROOT / "aegis_cli" / "sync.py", ROOT / "aegis_cli" / "report.py", ROOT / "aegis_cli" / "status.py",
            ROOT / "aegis_core" / "verification" / "checkpoint_checks.py",
            ROOT / "aegis_core" / "lifecycle.py",
        ]
        if p.exists()
    ]
    forbidden = (".aegis/evidence/fitness.jsonl", ".aegis/evidence/outcomes.jsonl", ".aegis/evidence/sessions_processed.jsonl")
    offenders = {
        path.relative_to(ROOT).as_posix(): needle
        for path in production
        for needle in forbidden
        if needle in path.read_text(encoding="utf-8").replace("', 'evidence', '", "/evidence/").replace('\", \"evidence\", \"', "/evidence/")
    }
    assert offenders == {}


def test_sync_malformed_ledger_does_not_apply_partial_counts(tmp_path, monkeypatch, capsys):
    import aegis_cli.sync as sync

    cell = tmp_path / ".aegis" / "rules" / "vacuoles" / "mixed.md"
    _cell(cell, "mixed")
    original = cell.read_bytes()
    evidence = tmp_path / ".aegis" / "evidence"
    evidence.mkdir(parents=True)
    (evidence / "signals.jsonl").write_text(
        json.dumps(_signal("mixed", "trigger")) + "\n{bad}\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(sync, "resolve_root", lambda _args: tmp_path)

    assert sync.run_sync(argparse.Namespace(dry_run=False, json=True)) == 1
    assert cell.read_bytes() == original
    assert json.loads(capsys.readouterr().out)["errors"]


def test_lifecycle_does_not_infer_zero_triggers_from_outcome_only_data(tmp_path):
    from aegis_core.lifecycle import evaluate_demotions

    cell = tmp_path / ".aegis" / "rules" / "walls" / "outcome-only.md"
    _cell(cell, "outcome-only", cell_type="wall", age_days=120)
    _write_jsonl(
        tmp_path / ".aegis" / "evidence" / "signals.jsonl",
        [_signal("outcome-only", "tp", weight="0.5")],
    )

    assert evaluate_demotions(str(tmp_path)) == []


def test_invalid_present_credit_weight_is_a_structured_error(tmp_path):
    from aegis_core.evidence import aggregate_signals

    evidence = tmp_path / ".aegis" / "evidence"
    _write_jsonl(evidence / "signals.jsonl", [_signal("bad-weight", "tp", weight="NaN")])

    result = aggregate_signals(str(evidence))
    assert result.counts["bad-weight"]["tp"] == 0
    assert result.counts["bad-weight"]["has_outcomes"] is True
    assert result.errors[0]["line"] == 1
    assert "credit_weight" in result.errors[0]["error"]


def test_negative_or_excessive_credit_weight_rejected(tmp_path):
    from aegis_core.evidence import aggregate_signals

    evidence = tmp_path / ".aegis" / "evidence"
    _write_jsonl(evidence / "signals.jsonl", [
        _signal("cell-neg", "tp", weight=-1.5),
        _signal("cell-huge", "tp", weight=50),
    ])

    result = aggregate_signals(str(evidence))
    assert result.counts["cell-neg"]["tp"] == 0
    assert result.counts["cell-huge"]["tp"] == 0
    assert len(result.errors) == 2
    assert "credit_weight" in result.errors[0]["error"]
    assert "credit_weight" in result.errors[1]["error"]


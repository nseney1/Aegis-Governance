"""Transaction regressions for canonical evidence production and sync."""
import argparse
import json
import os
import time

import pytest
from aegis_core.yaml import dump_frontmatter


def _rows(path):
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def _cell(workspace, cell_id, triggers=0, tp=0, fp=0, score=None):
    path = workspace / ".aegis" / "rules" / "vacuoles" / f"{cell_id}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    fitness = {
        "score": score,
        "impact_weight": 1.0,
        "triggers": triggers,
        "true_positives": tp,
        "false_positives": fp,
    }
    fm = {"id": cell_id, "type": "vacuole", "fitness": fitness}
    path.write_text(dump_frontmatter(fm, body="Body\n"), encoding="utf-8")
    return path


def test_append_signals_conflict_leaves_ledger_byte_identical(tmp_path):
    from aegis_sdk.telemetry import EventConflictError, append_signal, append_signals

    append_signal(str(tmp_path), "cell-b", "tp", "mcp", metadata={"v": 1},
                  principal="mcp", idempotency_scope="batch", idempotency_key="same")
    ledger = tmp_path / ".aegis" / "evidence" / "signals.jsonl"
    before = ledger.read_bytes()

    with pytest.raises(EventConflictError):
        append_signals(str(tmp_path), [
            {"cell_name": "cell-a", "signal_type": "tp", "source": "mcp",
             "principal": "mcp", "idempotency_scope": "batch", "idempotency_key": "new"},
            {"cell_name": "cell-b", "signal_type": "fp", "source": "mcp",
             "metadata": {"v": 2}, "principal": "mcp",
             "idempotency_scope": "batch", "idempotency_key": "same"},
        ])

    assert ledger.read_bytes() == before


def test_report_outcome_batch_failure_then_same_key_retries_once(tmp_path, monkeypatch):
    import aegis_sdk.telemetry as telemetry
    from aegis_mcp.tools import execute_tool

    _cell(tmp_path, "cell-a")
    _cell(tmp_path, "cell-b")
    monkeypatch.setenv("AEGIS_WORKSPACE", str(tmp_path))
    real_validate = telemetry._validate_event
    calls = {"count": 0}

    def fail_on_second(event):
        calls["count"] += 1
        if calls["count"] == 2:
            raise OSError("second signal rejected")
        return real_validate(event)

    monkeypatch.setattr(telemetry, "_validate_event", fail_on_second)
    args = {"outcome": "success", "cells_used": ["cell-a", "cell-b"],
            "idempotency_key": "caller-operation-1"}
    result = execute_tool("soma_report_outcome", args)
    ledger = tmp_path / ".aegis" / "evidence" / "signals.jsonl"
    assert result["status"] == "FAIL"
    assert _rows(ledger) == []
    assert not (ledger.parent / "outcomes.jsonl").exists()

    monkeypatch.setattr(telemetry, "_validate_event", real_validate)
    assert execute_tool("soma_report_outcome", args)["status"] == "recorded"
    assert execute_tool("soma_report_outcome", args)["status"] == "recorded"
    rows = _rows(ledger)
    assert sorted(row["cell"] for row in rows) == ["cell-a", "cell-b"]
    assert len(rows) == 2


def test_fitness_updater_retry_completes_every_cell_once(tmp_path):
    from aegis_core.telemetry import update_fitness

    evidence = tmp_path / ".aegis" / "evidence"
    cells = [{"cell_id": "cell-a", "matched_files": ["a.py"]}]
    update_fitness(cells, "transcript-1", evidence)
    update_fitness(cells + [{"cell_id": "cell-b", "matched_files": ["b.py"]}],
                   "transcript-1", evidence)
    rows = _rows(evidence / "signals.jsonl")
    assert sorted(row["cell"] for row in rows) == ["cell-a", "cell-b"]
    assert len(rows) == 2


def test_sync_outcome_only_preserves_trigger_dimension(tmp_path):
    from aegis_cli.sync import aggregate_evidence, sync_frontmatter
    from aegis_sdk.rules import parse_cell_file

    path = _cell(tmp_path, "cell-a", triggers=7, tp=1, fp=1, score=1 / 7)
    evidence = tmp_path / ".aegis" / "evidence"
    evidence.mkdir(parents=True)
    (evidence / "signals.jsonl").write_text(
        json.dumps({"cell": "cell-a", "signal": "tp", "metadata": {"credit_weight": 0.25}}) + "\n",
        encoding="utf-8")
    changes = sync_frontmatter(str(path.parent.parent), aggregate_evidence(str(evidence)))
    fm, _ = parse_cell_file(str(path))
    assert len(changes) == 1
    assert fm["fitness"]["triggers"] == 7
    assert fm["fitness"]["true_positives"] == 0.25
    assert fm["fitness"]["false_positives"] == 0
    assert fm["fitness"]["score"] == round(0.25 / 7, 4)


def test_sync_fractional_credit_uses_decimal_sum(tmp_path):
    from aegis_cli.sync import aggregate_evidence

    evidence = tmp_path / ".aegis" / "evidence"
    evidence.mkdir(parents=True)
    rows = [{"cell": "cell-a", "signal": "tp", "metadata": {"credit_weight": 0.1}},
            {"cell": "cell-a", "signal": "tp", "metadata": {"credit_weight": 0.2}}]
    (evidence / "signals.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    assert aggregate_evidence(str(evidence))["cell-a"]["tp"] == 0.3


def test_sync_replace_failure_returns_nonzero_without_claimed_change(tmp_path, monkeypatch, capsys):
    import aegis_cli.sync as sync_mod

    _cell(tmp_path, "cell-a")
    evidence = tmp_path / ".aegis" / "evidence"
    evidence.mkdir(parents=True)
    (evidence / "signals.jsonl").write_text(
        json.dumps({"cell": "cell-a", "signal": "trigger", "timestamp": "2026-01-01T00:00:00Z"}) + "\n",
        encoding="utf-8")
    monkeypatch.setattr(sync_mod, "resolve_root", lambda args: tmp_path)
    monkeypatch.setattr(sync_mod.os, "replace", lambda source, target: (_ for _ in ()).throw(OSError("disk")))

    rc = sync_mod.run_sync(argparse.Namespace(dry_run=False, json=True))
    payload = json.loads(capsys.readouterr().out)
    assert rc != 0
    assert payload["status"] == "error"
    assert payload["changes"] == []
    assert payload["errors"]

"""Transaction regressions for canonical evidence production and sync."""
import json

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
    from aegis_core.telemetry_engine.ledger import EventConflictError, append_signal, append_signals

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
    import aegis_core.telemetry_engine.ledger as telemetry
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
    args = {"outcome": "success", "rules_used": ["cell-a", "cell-b"],
            "idempotency_key": "caller-operation-1"}
    result = execute_tool("aegis_report_outcome", args)
    ledger = tmp_path / ".aegis" / "evidence" / "signals.jsonl"
    assert result["status"] == "FAIL"
    assert _rows(ledger) == []
    assert not (ledger.parent / "outcomes.jsonl").exists()

    monkeypatch.setattr(telemetry, "_validate_event", real_validate)
    assert execute_tool("aegis_report_outcome", args)["status"] == "recorded"
    assert execute_tool("aegis_report_outcome", args)["status"] == "recorded"
    rows = _rows(ledger)
    assert sorted(row["cell"] for row in rows) == ["cell-a", "cell-b"]
    assert len(rows) == 2



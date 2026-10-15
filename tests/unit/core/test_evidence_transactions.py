"""Transaction regressions for ledger writes: a failed batch writes nothing."""
import json

import pytest
from aegis_core.yaml_engine.serializer import dump_frontmatter


def _rows(path):
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def _rule(workspace, rule_id):
    path = workspace / ".aegis" / "rules" / "traps" / f"{rule_id}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dump_frontmatter({"id": rule_id, "type": "trap"}, body="Body\n"), encoding="utf-8")
    return path


def test_append_conflict_leaves_ledger_byte_identical(tmp_path):
    from aegis_core.telemetry_engine import ledger

    ledger.append(tmp_path, [{"rule": "rule-b", "outcome": "tp", "source": "mcp", "key": "same", "meta": {"v": 1}}])
    path = tmp_path / ".aegis" / "state" / "ledger.jsonl"
    before = path.read_bytes()

    with pytest.raises(ledger.EventConflictError):
        ledger.append(tmp_path, [
            {"rule": "rule-a", "outcome": "tp", "source": "mcp", "key": "new"},
            {"rule": "rule-b", "outcome": "fp", "source": "mcp", "key": "same", "meta": {"v": 2}},
        ])

    assert path.read_bytes() == before


def test_report_outcome_batch_failure_then_same_key_retries_once(tmp_path, monkeypatch):
    import aegis_core.telemetry_engine.ledger as ledger_mod
    from aegis_mcp.tools import execute_tool

    _rule(tmp_path, "rule-a")
    _rule(tmp_path, "rule-b")
    monkeypatch.setenv("AEGIS_WORKSPACE", str(tmp_path))
    real_validate = ledger_mod._validated
    calls = {"count": 0}

    def fail_on_second(event):
        calls["count"] += 1
        if calls["count"] == 2:
            raise OSError("second row rejected")
        return real_validate(event)

    monkeypatch.setattr(ledger_mod, "_validated", fail_on_second)
    args = {"outcome": "success", "rules_used": ["rule-a", "rule-b"],
            "idempotency_key": "caller-operation-1"}
    result = execute_tool("aegis_report_outcome", args)
    path = tmp_path / ".aegis" / "state" / "ledger.jsonl"
    assert result["status"] == "FAIL"
    assert _rows(path) == []

    monkeypatch.setattr(ledger_mod, "_validated", real_validate)
    assert execute_tool("aegis_report_outcome", args)["status"] == "recorded"
    assert execute_tool("aegis_report_outcome", args)["status"] == "recorded"
    rows = _rows(path)
    assert sorted(row["rule"] for row in rows) == ["rule-a", "rule-b"]
    assert len(rows) == 2

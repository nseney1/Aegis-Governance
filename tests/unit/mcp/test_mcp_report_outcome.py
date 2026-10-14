import json
import os
import pytest

def _workspace_with_cell(tmp_path, cell="trap-x"):
    cells = tmp_path / ".aegis" / "rules" / "vacuoles"
    cells.mkdir(parents=True)
    (cells / f"{cell}.md").write_text(
        f"---\nid: {cell}\ntype: vacuole\nhypothesis: h\nprediction: p\n---\n# x\n",
        encoding="utf-8")
    return tmp_path

def _jsonl(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]

def test_report_outcome_writes_only_canonical_signal(tmp_path, monkeypatch):
    from aegis_mcp.tools import execute_tool
    ws = _workspace_with_cell(tmp_path)
    monkeypatch.setenv("AEGIS_WORKSPACE", str(ws))
    result = execute_tool(
        "aegis_report_outcome",
        {"outcome": "success", "cells_used": ["trap-x"],
         "workspace": str(ws), "idempotency_key": "report-1"},
    )
    assert result["status"] == "recorded"
    ev = ws / ".aegis" / "evidence"
    signal, = _jsonl(ev / "signals.jsonl")
    assert signal["cell"] == "trap-x"
    assert signal["signal"] == "tp"
    assert signal["event_id"], "MCP outcome signal is not idempotent"
    assert not (ev / "outcomes.jsonl").exists()


def test_report_outcome_accepts_tp_and_fp(tmp_path, monkeypatch):
    from aegis_mcp.tools import execute_tool, TOOL_DEFINITIONS
    ws = _workspace_with_cell(tmp_path, cell="trap-tp")
    monkeypatch.setenv("AEGIS_WORKSPACE", str(ws))

    # Verify tool definition enum
    tool_def = next(t for t in TOOL_DEFINITIONS if t["name"] == "aegis_report_outcome")
    enum_vals = tool_def["inputSchema"]["properties"]["outcome"]["enum"]
    assert "tp" in enum_vals
    assert "fp" in enum_vals

    # Execute with tp
    res_tp = execute_tool(
        "aegis_report_outcome",
        {"outcome": "tp", "cells_used": ["trap-tp"], "workspace": str(ws), "idempotency_key": "k-tp"},
    )
    assert res_tp["status"] == "recorded"

    # Execute with fp
    res_fp = execute_tool(
        "aegis_report_outcome",
        {"outcome": "fp", "cells_used": ["trap-tp"], "workspace": str(ws), "idempotency_key": "k-fp"},
    )
    assert res_fp["status"] == "recorded"


def test_soma_create_cell_description_clarifies_advisory():
    from aegis_mcp.tools import TOOL_DEFINITIONS
    tool_def = next(t for t in TOOL_DEFINITIONS if t["name"] == "aegis_create_rule")
    assert "prompt" in tool_def["description"].lower()


def test_report_outcome_accepts_pass_and_fail(tmp_path, monkeypatch):
    from aegis_mcp.tools import execute_tool, TOOL_DEFINITIONS
    ws = _workspace_with_cell(tmp_path, cell="trap-pass-fail")
    monkeypatch.setenv("AEGIS_WORKSPACE", str(ws))

    tool_def = next(t for t in TOOL_DEFINITIONS if t["name"] == "aegis_report_outcome")
    enum_vals = tool_def["inputSchema"]["properties"]["outcome"]["enum"]
    assert "pass" in enum_vals
    assert "fail" in enum_vals

    res_pass = execute_tool(
        "aegis_report_outcome",
        {"outcome": "pass", "cells_used": ["trap-pass-fail"], "workspace": str(ws), "idempotency_key": "k-pass"},
    )
    assert res_pass["status"] == "recorded"

    res_fail = execute_tool(
        "aegis_report_outcome",
        {"outcome": "fail", "cells_used": ["trap-pass-fail"], "workspace": str(ws), "idempotency_key": "k-fail"},
    )
    assert res_fail["status"] == "recorded"

    signals = _jsonl(ws / ".aegis" / "evidence" / "signals.jsonl")
    types = [s["signal"] for s in signals if s["cell"] == "trap-pass-fail"]
    assert "tp" in types
    assert "fp" in types



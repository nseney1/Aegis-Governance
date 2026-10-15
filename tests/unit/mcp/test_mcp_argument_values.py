"""Argument values are checked against the tool's published inputSchema before its
handler runs, so a value the schema forbids is never recorded, and a call is never
reported as failed after its ledger row was written.

This covers the scalar arguments (type, enum, maxLength) and ``view``. The list
arguments (files, rules_used) are checked by their handlers, with their own messages.
A JSON null is the same as leaving the argument out.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import aegis_mcp.server as server
from aegis_core.taxonomy import CANONICAL_RULE_TYPES
from aegis_mcp.registry import TOOL_DEFINITIONS
from aegis_mcp.tools import execute_tool

REPORT_SCHEMA = next(t for t in TOOL_DEFINITIONS if t["name"] == "aegis_report_outcome")["inputSchema"]
VIEWS = ["full", "summary", "ids"]
BAD_VIEWS = [123, True, ["ids"], {"a": 1}, "bogus", "IDS"]


@pytest.fixture
def ws(tmp_path: Path) -> Path:
    rules = tmp_path / ".aegis" / "rules" / "traps"
    rules.mkdir(parents=True)
    (rules / "trap-x.md").write_text(
        "---\nid: trap-x\ntype: trap\nhypothesis: h\nprediction: p\ntarget_paths: ['src/*.py']\n---\n# x\n",
        encoding="utf-8",
    )
    return tmp_path


def _rows(ws: Path) -> list:
    path = ws / ".aegis" / "evidence" / "signals.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _report(ws: Path, **extra):
    args = {"workspace": str(ws), "outcome": "success", "rules_used": ["trap-x"], "idempotency_key": "k-1"}
    args.update(extra)
    return execute_tool("aegis_report_outcome", args)


def test_published_views_are_the_ones_accepted():
    for tool in TOOL_DEFINITIONS:
        view = tool["inputSchema"]["properties"].get("view")
        if view is not None:
            assert view["enum"] == VIEWS


@pytest.mark.parametrize("view", BAD_VIEWS, ids=repr)
def test_a_bad_view_fails_a_report_before_anything_is_recorded(ws, view):
    result = _report(ws, view=view)
    assert isinstance(result, dict) and result.get("status") == "FAIL", result
    assert result["error"].startswith("Invalid 'view': ")
    assert _rows(ws) == []


@pytest.mark.parametrize("tool, args", [
    ("aegis_scan", {"files": ["src/app.py"]}),
    ("aegis_list_rules", {}),
])
@pytest.mark.parametrize("view", BAD_VIEWS, ids=repr)
def test_a_bad_view_fails_a_read_only_tool(ws, tool, args, view):
    result = execute_tool(tool, {"workspace": str(ws), "view": view, **args})
    assert isinstance(result, dict) and result.get("status") == "FAIL", result
    assert result["error"].startswith("Invalid 'view': ")


def test_bad_view_messages_name_the_expected_values(ws):
    assert execute_tool("aegis_list_rules", {"workspace": str(ws), "view": "bogus"}) == {
        "status": "FAIL",
        "error": "Invalid 'view': 'bogus'. Expected one of ['full', 'summary', 'ids'].",
    }
    assert execute_tool("aegis_list_rules", {"workspace": str(ws), "view": 123}) == {
        "status": "FAIL",
        "error": "Invalid 'view': 123. Expected a string.",
    }


def test_a_null_view_is_the_same_as_no_view(ws):
    plain = execute_tool("aegis_list_rules", {"workspace": str(ws)})
    assert execute_tool("aegis_list_rules", {"workspace": str(ws), "view": None}) == plain


@pytest.mark.parametrize("field, value, error", [
    ("rework_count", "x", "Invalid 'rework_count': 'x'. Expected an integer."),
    ("rework_count", True, "Invalid 'rework_count': True. Expected an integer."),
    ("rework_count", 1.5, "Invalid 'rework_count': 1.5. Expected an integer."),
    ("tests_passed", "yes", "Invalid 'tests_passed': 'yes'. Expected true or false."),
    ("tests_passed", 1, "Invalid 'tests_passed': 1. Expected true or false."),
    ("notes", {"nested": {"a": 1}}, "Invalid 'notes': {'nested': {'a': 1}}. Expected a string."),
    ("notes", ["a"], "Invalid 'notes': ['a']. Expected a string."),
    ("outcome", "SUCCESS",
     "Invalid 'outcome': 'SUCCESS'. Expected one of "
     "['success', 'partial', 'failure', 'tp', 'fp', 'pass', 'fail']."),
])
def test_report_values_outside_the_schema_record_nothing(ws, field, value, error):
    assert _report(ws, **{field: value}) == {"status": "FAIL", "error": error}
    assert _rows(ws) == []


def test_a_long_bad_value_is_quoted_short(ws):
    result = _report(ws, notes={"blob": "x" * 10_000})
    assert result["status"] == "FAIL"
    assert len(result["error"]) < 200


def test_values_within_the_schema_are_recorded_as_sent(ws):
    result = _report(ws, rework_count=2, tests_passed=False, notes="fine")
    assert result["status"] == "recorded", result
    row, = _rows(ws)
    assert (row["metadata"]["rework_count"], row["metadata"]["tests_passed"], row["metadata"]["notes"]) == (
        2, False, "fine",
    )


@pytest.mark.parametrize("field", ["notes", "idempotency_key"])
def test_report_strings_are_capped_at_their_published_max_length(ws, field):
    cap = REPORT_SCHEMA["properties"][field]["maxLength"]
    assert _report(ws, **{field: "n" * (cap + 1)}) == {
        "status": "FAIL",
        "error": f"Invalid {field!r}: {cap + 1} characters. Expected at most {cap}.",
    }
    assert _rows(ws) == []
    assert _report(ws, **{field: "n" * cap})["status"] == "recorded"


@pytest.mark.parametrize("tool, args", [
    ("aegis_list_rules", {}),
    ("aegis_create_rule", {"description": "no secrets in logs"}),
])
def test_rule_type_outside_the_canonical_six_is_rejected(ws, tool, args):
    assert execute_tool(tool, {"workspace": str(ws), "rule_type": "wall", **args}) == {
        "status": "FAIL",
        "error": f"Invalid 'rule_type': 'wall'. Expected one of {list(CANONICAL_RULE_TYPES)}.",
    }


def test_create_rule_description_must_be_a_string(ws):
    assert execute_tool("aegis_create_rule", {"workspace": str(ws), "description": 42}) == {
        "status": "FAIL",
        "error": "Invalid 'description': 42. Expected a string.",
    }


def test_over_stdio_a_bad_view_is_an_error_and_records_nothing(ws, monkeypatch):
    monkeypatch.setattr(server, "_canonical_workspace", str(ws))
    monkeypatch.setattr(server, "_workspace_error", None)
    monkeypatch.setattr(server, "_session_id", None)
    server._tool_call_times.clear()
    server.handle_request({"jsonrpc": "2.0", "id": 0, "method": "initialize",
                           "params": {"clientInfo": {"name": "codex"}}})
    response = server.handle_request({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "aegis_report_outcome", "arguments": {
            "outcome": "success", "rules_used": ["trap-x"], "idempotency_key": "kh2", "view": 123,
        }},
    })
    assert response["result"]["isError"] is True
    assert json.loads(response["result"]["content"][0]["text"]) == {
        "status": "FAIL",
        "error": "Invalid 'view': 123. Expected a string.",
    }
    assert _rows(ws) == []

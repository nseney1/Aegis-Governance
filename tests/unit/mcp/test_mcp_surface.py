"""The v4 MCP surface: four tools, no receipts, no session token, no execution tier.

These drive ``handle_request`` end to end, the way a host does over stdio.
"""
from __future__ import annotations

import json

import pytest

import aegis_mcp.server as server

SURVIVING_TOOLS = {"aegis_scan", "aegis_report_outcome", "aegis_create_rule", "aegis_list_rules"}

REMOVED_TOOLS = [
    "aegis_request_receipt",
    "aegis_propose_change",
    "aegis_audit_security",
    "aegis_audit_performance",
    "aegis_verify_changes",
    "aegis_poll_verification",
    "aegis_checkpoint",
    "aegis_capture_insight",
    "aegis_generate_manifest",
    "aegis_grade",
    "aegis_coverage",
    "aegis_rule_fitness",
    "aegis_handoff",
]


@pytest.fixture
def initialized(tmp_path, monkeypatch):
    (tmp_path / ".aegis" / "rules").mkdir(parents=True)
    monkeypatch.setattr(server, "_canonical_workspace", str(tmp_path))
    monkeypatch.setattr(server, "_workspace_error", None)
    monkeypatch.setattr(server, "_session_id", None, raising=False)
    response = server.handle_request({
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"clientInfo": {"name": "pytest"}},
    })
    return response


def _list_tools():
    return server.handle_request({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})


def _call(name, arguments):
    return server.handle_request({
        "jsonrpc": "2.0", "id": 3, "method": "tools/call",
        "params": {"name": name, "arguments": arguments},
    })


def test_tools_list_returns_exactly_the_four_surviving_tools(initialized):
    names = [tool["name"] for tool in _list_tools()["result"]["tools"]]
    assert sorted(names) == sorted(SURVIVING_TOOLS)


def test_execution_env_flag_no_longer_widens_the_surface(initialized, monkeypatch):
    monkeypatch.setenv("AEGIS_EXECUTION_ENABLED", "1")
    names = {tool["name"] for tool in _list_tools()["result"]["tools"]}
    assert names == SURVIVING_TOOLS


@pytest.mark.parametrize("name", REMOVED_TOOLS)
def test_removed_tool_is_an_unknown_tool_protocol_error(initialized, name):
    response = _call(name, {})
    assert response["error"] == {"code": -32602, "message": f"Unknown tool: {name}"}


def test_no_tool_schema_takes_a_receipt(initialized):
    for tool in _list_tools()["result"]["tools"]:
        properties = tool["inputSchema"].get("properties", {})
        assert "receipt" not in properties, tool["name"]
        assert "receipt" not in tool["inputSchema"].get("required", []), tool["name"]


def test_initialize_hands_out_no_session_token(initialized):
    server_info = initialized["result"]["serverInfo"]
    assert set(server_info) == {"name", "version"}


def test_tools_call_before_initialize_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "_canonical_workspace", str(tmp_path))
    monkeypatch.setattr(server, "_session_id", None, raising=False)
    response = _call("aegis_list_rules", {})
    assert response["error"] == {"code": -32002, "message": "Server not initialized"}


def test_write_tool_runs_without_a_receipt_or_token(initialized, monkeypatch):
    monkeypatch.setenv("AEGIS_REQUIRE_SESSION_TOKEN", "1")
    response = _call("aegis_create_rule", {"description": "no eval on user input"})
    assert response["result"]["isError"] is False
    payload = json.loads(response["result"]["content"][0]["text"])
    assert "prompt" in payload


def test_read_tool_ignores_a_client_chosen_workspace(tmp_path, monkeypatch):
    def governed(root, rule):
        rules = root / ".aegis" / "rules" / "traps"
        rules.mkdir(parents=True)
        (rules / f"{rule}.md").write_text(f"---\nid: {rule}\ntype: trap\nhypothesis: h\n---\n", encoding="utf-8")
        return root

    canonical = governed(tmp_path / "canonical", "rule-canonical")
    other = governed(tmp_path / "other", "rule-other")
    monkeypatch.setattr(server, "_canonical_workspace", str(canonical))
    monkeypatch.setattr(server, "_workspace_error", None)
    monkeypatch.setattr(server, "_session_id", "session-test")

    response = _call("aegis_list_rules", {"workspace": str(other)})

    names = {rule.get("_name") for rule in json.loads(response["result"]["content"][0]["text"])}
    assert names == {"rule-canonical"}


def test_rule_type_enums_list_only_the_six_canonical_types(initialized):
    from aegis_core.taxonomy import CANONICAL_RULE_TYPES

    tools = {tool["name"]: tool for tool in _list_tools()["result"]["tools"]}
    for name in ("aegis_create_rule", "aegis_list_rules"):
        enum = tools[name]["inputSchema"]["properties"]["rule_type"]["enum"]
        assert enum == list(CANONICAL_RULE_TYPES) == ["invariant", "trap", "gate", "boundary", "persona", "contract"]

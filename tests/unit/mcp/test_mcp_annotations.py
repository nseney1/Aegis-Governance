"""MCP tool annotations: every advertised tool must declare the four boolean
hints (readOnlyHint, destructiveHint, idempotentHint, openWorldHint) and a
title. Expected values are derived from reading each handler in
soma_mcp/tools.py; see docs/project/CHANGELOG.md for rationale.
"""
import pytest

import aegis_mcp.server as server_module
from aegis_mcp.server import handle_request

_HINTS = ("readOnlyHint", "destructiveHint", "idempotentHint", "openWorldHint")

# (readOnly, destructive, idempotent, openWorld)
_EXPECTED = {
    "aegis_scan": (True, False, True, False),
    "aegis_grade": (True, False, True, False),
    "aegis_coverage": (True, False, True, False),
    "aegis_propose_change": (False, False, True, True),
    "aegis_audit_security": (True, False, True, False),
    "aegis_audit_performance": (True, False, True, False),
    "aegis_checkpoint": (False, False, True, False),
    "aegis_verify_changes": (False, False, True, False),
    "aegis_request_receipt": (False, False, False, False),
    "aegis_report_outcome": (False, False, True, False),
    "aegis_capture_insight": (False, False, False, False),
    "aegis_generate_manifest": (False, True, True, False),
    "aegis_poll_verification": (True, False, True, False),
    "aegis_create_rule": (False, False, True, False),
    "aegis_list_rules": (True, False, True, False),
    "aegis_rule_fitness": (True, False, True, False),
    "aegis_handoff": (False, False, False, False),
}


@pytest.fixture
def tools():
    # Properly initialize the server to set the session token
    # instead of mutating private module state directly
    import os
    os.environ["AEGIS_EXECUTION_ENABLED"] = "1"
    server_module._execution_enabled = True # Keep for now as there's no setup fn
    handle_request({"jsonrpc": "2.0", "id": 0, "method": "initialize"})
    resp = handle_request({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    return {t["name"]: t for t in resp["result"]["tools"]}


def test_expected_table_covers_every_advertised_tool(tools):
    assert set(tools) == set(_EXPECTED)


def test_every_tool_declares_four_boolean_hints_and_title(tools):
    for name, tool in tools.items():
        ann = tool.get("annotations")
        assert isinstance(ann, dict), f"{name}: missing annotations"
        for hint in _HINTS:
            assert isinstance(ann.get(hint), bool), f"{name}: {hint} not a bool"
        assert isinstance(ann.get("title"), str) and ann["title"], f"{name}: no title"


@pytest.mark.parametrize("name", sorted(_EXPECTED))
def test_hint_values_match_handler_behavior(tools, name):
    ro, destructive, idem, open_world = _EXPECTED[name]
    ann = tools[name]["annotations"]
    assert ann["readOnlyHint"] is ro
    assert ann["destructiveHint"] is destructive
    assert ann["idempotentHint"] is idem
    assert ann["openWorldHint"] is open_world


def test_read_only_tools_are_never_destructive(tools):
    for name, tool in tools.items():
        ann = tool["annotations"]
        if ann["readOnlyHint"]:
            assert ann["destructiveHint"] is False, name


def test_hints_agree_with_server_privilege_classes(tools):
    # Anything the server gates behind a receipt as a write tool or execute tool must not
    # advertise itself as read-only.
    for name in server_module._WRITE_TOOLS | server_module._EXECUTE_TOOLS:
        assert tools[name]["annotations"]["readOnlyHint"] is False, name


def test_tools_list_filters_execute_tools_when_execution_disabled(monkeypatch):
    monkeypatch.setattr(server_module, "_session_token", "test-session")
    monkeypatch.setattr(server_module, "_execution_enabled", False)
    resp = handle_request({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    returned_tools = {t["name"]: t for t in resp["result"]["tools"]}
    
    for name in server_module._EXECUTE_TOOLS:
        assert name not in returned_tools, f"{name} should be filtered when execution is disabled"

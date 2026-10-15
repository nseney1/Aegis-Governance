"""MCP tool annotations: every advertised tool declares the four boolean hints
(readOnlyHint, destructiveHint, idempotentHint, openWorldHint) and a title, and the
hints match what the handler does.
"""
import pytest

import aegis_mcp.server as server_module
from aegis_mcp.server import handle_request

_HINTS = ("readOnlyHint", "destructiveHint", "idempotentHint", "openWorldHint")

# (readOnly, destructive, idempotent, openWorld)
_EXPECTED = {
    "aegis_scan": (True, False, True, False),
    # Appends to the ledger; a repeated idempotency key is recorded once.
    "aegis_report_outcome": (False, False, True, False),
    # Returns a prompt and writes nothing.
    "aegis_create_rule": (True, False, True, False),
    "aegis_list_rules": (True, False, True, False),
}


@pytest.fixture
def tools(monkeypatch):
    monkeypatch.setattr(server_module, "_session_id", None)
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

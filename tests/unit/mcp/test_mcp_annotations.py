"""MCP tool annotations: every advertised tool declares the four boolean hints
(readOnlyHint, destructiveHint, idempotentHint, openWorldHint) and a title, and a
read-only tool is never destructive. The values themselves are pinned by the contract
snapshot (tests/contract/mcp_tools.json).
"""
import pytest

import aegis_mcp.server as server_module
from aegis_mcp.server import handle_request

_HINTS = ("readOnlyHint", "destructiveHint", "idempotentHint", "openWorldHint")


@pytest.fixture
def tools(monkeypatch):
    monkeypatch.setattr(server_module, "_session_id", None)
    handle_request({"jsonrpc": "2.0", "id": 0, "method": "initialize"})
    resp = handle_request({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    return {t["name"]: t for t in resp["result"]["tools"]}


def test_every_tool_declares_four_boolean_hints_and_title(tools):
    for name, tool in tools.items():
        ann = tool.get("annotations")
        assert isinstance(ann, dict), f"{name}: missing annotations"
        for hint in _HINTS:
            assert isinstance(ann.get(hint), bool), f"{name}: {hint} not a bool"
        assert isinstance(ann.get("title"), str) and ann["title"], f"{name}: no title"


def test_read_only_tools_are_never_destructive(tools):
    for name, tool in tools.items():
        ann = tool["annotations"]
        if ann["readOnlyHint"]:
            assert ann["destructiveHint"] is False, name

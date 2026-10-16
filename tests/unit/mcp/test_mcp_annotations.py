"""MCP tool annotations: a read-only tool declares the four boolean hints
(readOnlyHint, destructiveHint, idempotentHint, openWorldHint) and a title and is never
destructive. A write tool declares only readOnlyHint false and a title: hosts treat
annotations as untrusted hints, so it never claims to be non-destructive and the MCP
defaults apply (author decision 2026-10-17). The values are pinned by the contract
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


def test_every_tool_declares_its_hints_and_title(tools):
    for name, tool in tools.items():
        ann = tool.get("annotations")
        assert isinstance(ann, dict), f"{name}: missing annotations"
        assert isinstance(ann.get("readOnlyHint"), bool), f"{name}: readOnlyHint not a bool"
        if ann["readOnlyHint"]:
            for hint in _HINTS:
                assert isinstance(ann.get(hint), bool), f"{name}: {hint} not a bool"
        assert isinstance(ann.get("title"), str) and ann["title"], f"{name}: no title"


def test_read_only_tools_are_never_destructive(tools):
    for name, tool in tools.items():
        ann = tool["annotations"]
        if ann["readOnlyHint"]:
            assert ann["destructiveHint"] is False, name


def test_write_tools_claim_nothing_beyond_not_read_only(tools):
    writers = {n: t["annotations"] for n, t in tools.items() if not t["annotations"]["readOnlyHint"]}
    assert "aegis_report_outcome" in writers
    for name, ann in writers.items():
        assert set(ann) == {"readOnlyHint", "title"}, f"{name}: {sorted(ann)}"

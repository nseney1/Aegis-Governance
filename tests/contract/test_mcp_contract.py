"""MCP contract snapshot (ADR 0005 AD-6): the live tools/list result must equal
tests/contract/mcp_tools.json, so any change to a tool name, description, schema or
annotation is a reviewed diff of that file.

Regenerate after an intended change, from the repository root:

    python3 -c "import json,aegis_mcp.server as s; s.handle_request({'jsonrpc':'2.0','id':0,'method':'initialize'}); print(json.dumps(s.handle_request({'jsonrpc':'2.0','id':1,'method':'tools/list'})['result'], indent=2, ensure_ascii=False))" > tests/contract/mcp_tools.json
"""
from __future__ import annotations

import json
from pathlib import Path

import aegis_mcp.server as server

SNAPSHOT = Path(__file__).with_name("mcp_tools.json")


def _live_tools_list(monkeypatch) -> dict:
    monkeypatch.setattr(server, "_session_id", None)
    server.handle_request({"jsonrpc": "2.0", "id": 0, "method": "initialize"})
    response = server.handle_request({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    # Round-trip through JSON so tuples and other in-memory types compare as the wire sees them.
    return json.loads(json.dumps(response["result"]))


def test_tools_list_matches_the_contract_snapshot(monkeypatch):
    expected = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    assert _live_tools_list(monkeypatch) == expected


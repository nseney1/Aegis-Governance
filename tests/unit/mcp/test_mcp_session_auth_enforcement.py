"""Behavioral tests for BUG-076: Authentication Bypass in MCP Server tools/call.

1. When AEGIS_REQUIRE_SESSION_TOKEN=1 is enabled, any tools/call request that omits
   _sessionToken must be rejected with -32002.
2. In default mode, an unauthenticated caller must NOT inherit the server's internal
   _session_token as their session ID (which previously allowed unauthenticated callers
   to redeem receipts issued to authenticated sessions).
"""
import pytest
from aegis_mcp import server


@pytest.fixture(autouse=True)
def reset_server_session(monkeypatch):
    """Ensure clean server session state before each test."""
    monkeypatch.setattr(server, "_session_token", None)
    monkeypatch.setattr(server, "_session_tokens", set())


def test_tools_call_rejects_missing_session_token_when_required(monkeypatch):
    """When AEGIS_REQUIRE_SESSION_TOKEN=1, tools/call without token must return -32002."""
    monkeypatch.setenv("AEGIS_REQUIRE_SESSION_TOKEN", "1")

    # 1. Initialize server
    init_req = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
    init_resp = server.handle_request(init_req)
    assert "result" in init_resp

    # 2. Call tool with NO session token provided
    call_req = {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/call",
        "params": {
            "name": "soma_list_cells",
            "arguments": {}
        }
    }
    call_resp = server.handle_request(call_req)

    assert "error" in call_resp, "Server permitted tool call without session token under AEGIS_REQUIRE_SESSION_TOKEN=1!"
    assert call_resp["error"]["code"] == -32002
    assert "session token required" in call_resp["error"]["message"].lower()


def test_tools_call_accepts_valid_session_token(monkeypatch):
    """tools/call with correct _sessionToken is accepted under AEGIS_REQUIRE_SESSION_TOKEN=1."""
    monkeypatch.setenv("AEGIS_REQUIRE_SESSION_TOKEN", "1")
    init_req = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
    init_resp = server.handle_request(init_req)
    token = init_resp["result"]["serverInfo"]["_sessionToken"]

    call_req = {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/call",
        "params": {
            "name": "soma_list_cells",
            "_sessionToken": token,
            "arguments": {}
        }
    }
    call_resp = server.handle_request(call_req)
    assert "error" not in call_resp or call_resp["error"]["code"] != -32002


def test_unauthenticated_caller_does_not_inherit_server_session_token(monkeypatch):
    """Unauthenticated caller must have active_session_id='default', NOT the server's private _session_token."""
    init_req = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
    init_resp = server.handle_request(init_req)
    server_token = init_resp["result"]["serverInfo"]["_sessionToken"]

    # Call with NO token
    call_req = {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/call",
        "params": {
            "name": "soma_list_cells",
            "arguments": {}
        }
    }
    # Intercept active_session_id in rate limit or execution
    captured_session_ids = []
    orig_check_rate_limit = server._check_rate_limit
    def spy_check(name, session_id=None):
        captured_session_ids.append(session_id)
        return orig_check_rate_limit(name, session_id=session_id)

    monkeypatch.setattr(server, "_check_rate_limit", spy_check)
    server.handle_request(call_req)

    assert server_token not in captured_session_ids, (
        f"Security violation: unauthenticated caller was assigned the server's private _session_token {server_token}!"
    )
    assert "default" in captured_session_ids

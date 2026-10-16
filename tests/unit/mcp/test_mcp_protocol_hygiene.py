"""aegis-mcp identity and JSON-RPC hygiene (host-matrix §3.5; v1 draft §3.5).

- Identity: the registration's AEGIS_CLIENT wins, else the exact clientInfo table from
  aegis_core.hosts (a prefix only for Claude Desktop's local-agent-mode-), else
  "generic"; never "gemini". Tool arguments cannot set it.
- ``initialize`` returns the bootstrap ``instructions`` and echoes a supported
  ``protocolVersion``; ``ping`` answers; ``server/discover`` is Method not found so hosts
  fall back to ``initialize``; responses to the server's own requests are routed, never
  answered with -32601; a deeply nested line is an error and the server keeps serving.
"""
from __future__ import annotations

import io
import json

import pytest

import aegis_mcp.server as server
from aegis_core.bootstrap import instructions_text


def _initialize(params=None, req_id=1):
    return server.handle_request({"jsonrpc": "2.0", "id": req_id, "method": "initialize", "params": params or {}})


def _serve(monkeypatch, capsys, lines):
    monkeypatch.setattr("sys.stdin", io.StringIO("".join(f"{line}\n" for line in lines)))
    rc = server.run_stdio_server()
    frames = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.strip()]
    return rc, frames


def _frame(req_id, method, params=None):
    msg = {"jsonrpc": "2.0", "id": req_id, "method": method}
    if params is not None:
        msg["params"] = params
    return json.dumps(msg)


@pytest.fixture
def home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.chdir(home)
    return home


# ── identity ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("client_name,host", [
    ("claude-code", "claude-code"),
    ("codex-mcp-client", "codex-cli"),
    ("antigravity-client", "antigravity"),
    ("local-agent-mode-3f9a", "claude-desktop"),
    ("gemini-cli-mcp-client", "gemini-cli"),
    ("Claude Code", "generic"),
    ("claude-ai", "generic"),
    ("gemini", "generic"),
    ("antigravity", "generic"),
    ("some-new-agent", "generic"),
    ("", "generic"),
])
def test_client_identity_comes_from_the_exact_host_table(client_name, host):
    _initialize({"clientInfo": {"name": client_name, "version": "9.9"}})
    assert server._client_platform == host


@pytest.mark.parametrize("params", [{}, {"clientInfo": "claude-code"}, {"clientInfo": {"name": 7}}, None])
def test_missing_or_malformed_client_info_is_generic(params):
    server.handle_request({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": params})
    assert server._client_platform == "generic"


def test_the_registration_env_wins_over_client_info(monkeypatch):
    monkeypatch.setenv("AEGIS_CLIENT", "codex-cli")
    _initialize({"clientInfo": {"name": "claude-code", "version": "2.1"}})
    assert server._client_platform == "codex-cli"
    assert (server._client_name, server._client_version) == ("claude-code", "2.1")


@pytest.mark.parametrize("value", ["gemini", "claude", "not-a-host"])
def test_an_unknown_registration_env_is_ignored(monkeypatch, capsys, value):
    monkeypatch.setenv("AEGIS_CLIENT", value)
    _initialize({"clientInfo": {"name": "antigravity-client"}})
    assert server._client_platform == "antigravity"
    assert f"AEGIS_CLIENT={value!r} names no known host" in capsys.readouterr().err


def test_client_host_name_and_version_are_server_owned():
    owned = server.SERVER_OWNED_KEYS
    assert {"client_host", "client_name", "client_version", "_client_name", "_client_version"} <= owned
    assert server.strip_server_owned({"client_host": "x", "client_name": "y", "client_version": "z", "files": []}) == {"files": []}


# ── initialize ───────────────────────────────────────────────────────────────

def test_initialize_returns_the_bootstrap_instructions():
    result = _initialize({"protocolVersion": "2025-06-18"})["result"]
    assert result["instructions"] == instructions_text()
    head = result["instructions"][:512]
    assert "aegis_scan" in head and "aegis_report_outcome" in head


@pytest.mark.parametrize("requested,answered", [
    ("2024-11-05", "2024-11-05"),
    ("2025-06-18", "2025-06-18"),   # codex-cli 0.162.1
    ("2025-11-25", "2025-11-25"),   # claude-code 2.1.295, antigravity
    ("2026-07-28", "2025-11-25"),   # newer than supported: the newest we speak
    ("2025-03-26", "2024-11-05"),   # batching era: the newest older version we speak
    ("2023-01-01", "2024-11-05"),
    ("not-a-date", "2024-11-05"),
    (None, "2024-11-05"),
    (20250618, "2024-11-05"),
])
def test_protocol_version_is_echoed_when_supported(requested, answered):
    params = {} if requested is None else {"protocolVersion": requested}
    assert _initialize(params)["result"]["protocolVersion"] == answered


# ── ping, discover, responses, notifications ─────────────────────────────────

def test_ping_answers_before_and_after_initialize():
    assert server.handle_request({"jsonrpc": "2.0", "id": "p1", "method": "ping"}) == {"jsonrpc": "2.0", "id": "p1", "result": {}}
    _initialize()
    assert server.handle_request({"jsonrpc": "2.0", "id": 9, "method": "ping", "params": {}})["result"] == {}


def test_server_discover_is_method_not_found_and_initialize_still_works(home, monkeypatch, capsys):
    discover = _frame(1, "server/discover", {"_meta": {"protocolVersion": "2026-07-28"}})
    rc, frames = _serve(monkeypatch, capsys, [discover, _frame(2, "initialize", {"protocolVersion": "2025-11-25"})])
    assert rc == 0
    assert frames[0] == {"jsonrpc": "2.0", "id": 1, "error": {"code": -32601, "message": "Method not found: server/discover"}}
    assert frames[1]["id"] == 2 and frames[1]["result"]["protocolVersion"] == "2025-11-25"


@pytest.mark.parametrize("message", [
    {"jsonrpc": "2.0", "id": "unknown-1", "result": {"roots": []}},
    {"jsonrpc": "2.0", "id": 5, "error": {"code": -32601, "message": "no"}},
    {"jsonrpc": "2.0", "id": None, "result": {}},
])
def test_a_response_from_the_client_is_routed_not_answered(home, monkeypatch, capsys, message):
    rc, frames = _serve(monkeypatch, capsys, [json.dumps(message), _frame(2, "ping")])
    assert rc == 0
    assert frames == [{"jsonrpc": "2.0", "id": 2, "result": {}}]


@pytest.mark.parametrize("method", ["notifications/cancelled", "notifications/progress", "notifications/whatever"])
def test_notifications_get_no_reply(home, monkeypatch, capsys, method):
    rc, frames = _serve(monkeypatch, capsys, [json.dumps({"jsonrpc": "2.0", "method": method, "params": {}}), _frame(2, "ping")])
    assert frames == [{"jsonrpc": "2.0", "id": 2, "result": {}}]


@pytest.mark.parametrize("method", ["resources/list", "resources/templates/list", "prompts/list"])
def test_unsupported_methods_codex_probes_are_method_not_found(method):
    _initialize()
    assert server.handle_request({"jsonrpc": "2.0", "id": 4, "method": method})["error"]["code"] == -32601


# ── robustness ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("line", [
    "[" * 100000 + "]" * 100000,
    '{"a": ' * 100000 + "1" + "}" * 100000,
], ids=["nested-arrays", "nested-objects"])  # the payload as an id overflows Windows' 32767-char env var
def test_a_deeply_nested_line_is_a_parse_error_and_the_server_keeps_serving(home, monkeypatch, capsys, line):
    rc, frames = _serve(monkeypatch, capsys, [line, _frame(2, "ping")])
    assert rc == 0
    assert frames[0]["id"] is None and frames[0]["error"]["code"] in (-32700, -32600)
    assert frames[1] == {"jsonrpc": "2.0", "id": 2, "result": {}}


def test_a_request_nested_just_below_the_parse_limit_is_answered(home, monkeypatch, capsys):
    deep = "[" * 400 + "]" * 400
    line = '{"jsonrpc": "2.0", "id": 3, "method": "ping", "params": {"x": ' + deep + "}}"
    rc, frames = _serve(monkeypatch, capsys, [line, _frame(4, "ping")])
    assert rc == 0
    assert [f["id"] for f in frames] == [3, 4]


@pytest.mark.parametrize("bad_id", [[1], {"a": 1}, True, [[[[]]]]])
def test_an_id_that_is_not_a_string_number_or_null_is_an_invalid_request(home, monkeypatch, capsys, bad_id):
    line = json.dumps({"jsonrpc": "2.0", "id": bad_id, "method": "ping"})
    rc, frames = _serve(monkeypatch, capsys, [line, _frame(2, "ping")])
    assert frames[0] == {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Invalid Request"}}
    assert frames[1]["id"] == 2


@pytest.mark.parametrize("method", [7, None, ["ping"]])
def test_a_method_that_is_not_a_string_is_an_invalid_request(home, monkeypatch, capsys, method):
    line = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method})
    rc, frames = _serve(monkeypatch, capsys, [line])
    assert frames == [{"jsonrpc": "2.0", "id": 1, "error": {"code": -32600, "message": "Invalid Request"}}]


# ── roots ────────────────────────────────────────────────────────────────────

def _roots_requests(frames):
    return [f for f in frames if f.get("method") == "roots/list"]


def test_roots_are_requested_after_initialized_when_the_client_declares_them(home, monkeypatch, capsys):
    init = _frame(1, "initialize", {"capabilities": {"roots": {"listChanged": True}}, "clientInfo": {"name": "claude-code"}})
    initialized = json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"})
    changed = json.dumps({"jsonrpc": "2.0", "method": "notifications/roots/list_changed"})
    rc, frames = _serve(monkeypatch, capsys, [init, initialized, changed])
    requests = _roots_requests(frames)
    assert len(requests) == 2
    assert all(isinstance(r["id"], str) and r["id"].startswith("aegis-roots-") for r in requests)
    assert requests[0]["id"] != requests[1]["id"]


def test_roots_are_not_requested_from_a_client_without_the_capability(home, monkeypatch, capsys):
    init = _frame(1, "initialize", {"capabilities": {}, "clientInfo": {"name": "codex-mcp-client"}})
    initialized = json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"})
    rc, frames = _serve(monkeypatch, capsys, [init, initialized])
    assert _roots_requests(frames) == []


def test_a_roots_response_becomes_the_host_roots(tmp_path):
    _initialize({"capabilities": {"roots": {}}})
    server.handle_request({"jsonrpc": "2.0", "method": "notifications/initialized"})
    (request,) = server.take_outbox()
    root = tmp_path / "proj"
    root.mkdir()
    reply = {"jsonrpc": "2.0", "id": request["id"], "result": {"roots": [{"uri": root.as_uri(), "name": "p"}, {"uri": "https://x"}]}}
    assert server.handle_request(reply) is None
    assert server._host_roots == (str(root),)


def test_a_response_to_an_unknown_request_changes_nothing():
    _initialize({"capabilities": {"roots": {}}})
    assert server.handle_request({"jsonrpc": "2.0", "id": "aegis-roots-99", "result": {"roots": [{"uri": "file:///x"}]}}) is None
    assert server._host_roots == ()

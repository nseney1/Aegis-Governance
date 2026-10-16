"""Attribution of what an MCP session does (host-matrix §3.8, ADR 0005 AD-9).

- Ledger rows carry the server-owned host id and session; the idempotency key is
  scoped by both, so two sessions that pick the same key never collide.
- aegis_scan appends one ``scan`` event per (session, files) to the activity log
  ``.aegis/state/activity.jsonl``; aegis_report_outcome's optional ``files`` append an
  ``edit`` event. ``aegis status --compliance`` reads them. Fitness never does.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import aegis_mcp.server as server
from aegis_core.yaml_engine.serializer import dump_frontmatter


@pytest.fixture
def ws(tmp_path, monkeypatch) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    root = tmp_path / "ws"
    rules = root / ".aegis" / "rules" / "traps"
    rules.mkdir(parents=True)
    fm = {"id": "trap-x", "type": "trap", "target_paths": ["src/*.py"], "hypothesis": "h", "prediction": "p"}
    (rules / "trap-x.md").write_text(dump_frontmatter(fm, body="Body\n"), encoding="utf-8")
    (root / "src").mkdir()
    (root / "src" / "a.py").write_text("a\n", encoding="utf-8")
    (root / "src" / "b.py").write_text("b\n", encoding="utf-8")
    monkeypatch.setattr(server, "_canonical_workspace", str(root))
    return root.resolve()


def _initialize(client="claude-code", version="2.1.295"):
    server.handle_request({"jsonrpc": "2.0", "id": 0, "method": "initialize",
                           "params": {"clientInfo": {"name": client, "version": version}}})
    return server._session_id


def _call(name, arguments, req_id=1):
    response = server.handle_request({"jsonrpc": "2.0", "id": req_id, "method": "tools/call",
                                      "params": {"name": name, "arguments": arguments}})
    return response["result"]["isError"], json.loads(response["result"]["content"][0]["text"])


def _jsonl(path: Path) -> list:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _ledger(ws: Path) -> list:
    return _jsonl(ws / ".aegis" / "state" / "ledger.jsonl")


def _activity(ws: Path) -> list:
    return _jsonl(ws / ".aegis" / "state" / "activity.jsonl")


# ── ledger rows ──────────────────────────────────────────────────────────────

def test_report_rows_carry_the_host_id_and_session(ws):
    session = _initialize()
    is_error, payload = _call("aegis_report_outcome", {"outcome": "tp", "rules_used": ["trap-x"], "idempotency_key": "r1"})
    assert not is_error, payload
    (row,) = _ledger(ws)
    assert (row["host"], row["session"], row["source"]) == ("claude-code", session, "mcp")


def test_the_idempotency_key_is_scoped_by_host_and_session(ws):
    first = _initialize()
    _call("aegis_report_outcome", {"outcome": "tp", "rules_used": ["trap-x"], "idempotency_key": "report-1"})
    _call("aegis_report_outcome", {"outcome": "tp", "rules_used": ["trap-x"], "idempotency_key": "report-1"}, 2)
    second = _initialize("codex-mcp-client")
    is_error, payload = _call("aegis_report_outcome", {"outcome": "fp", "rules_used": ["trap-x"], "idempotency_key": "report-1"}, 3)

    assert not is_error, payload
    rows = _ledger(ws)
    assert [(r["host"], r["session"], r["outcome"]) for r in rows] == [
        ("claude-code", first, "tp"), ("codex-cli", second, "fp"),
    ]
    assert rows[0]["key"] == f"claude-code/{first}/report-1"
    assert rows[1]["key"] == f"codex-cli/{second}/report-1"


def test_tool_arguments_cannot_set_the_client_identity(ws):
    _initialize("codex-mcp-client", "0.162.1")
    _call("aegis_report_outcome", {"outcome": "tp", "rules_used": ["trap-x"], "idempotency_key": "k",
                                   "client_host": "claude-code", "client_name": "x", "client_version": "y",
                                   "_client_name": "x", "_host": "claude-code", "host": "claude-code"})
    _call("aegis_scan", {"files": ["src/a.py"], "client_name": "spoof", "_client_version": "spoof"}, 2)
    (row,) = _ledger(ws)
    assert row["host"] == "codex-cli"
    (event,) = _activity(ws)
    assert (event["host"], event["client"]) == ("codex-cli", {"name": "codex-mcp-client", "version": "0.162.1"})


# ── scan events ──────────────────────────────────────────────────────────────

def test_a_scan_records_one_event_per_session_and_files(ws):
    session = _initialize()
    _call("aegis_scan", {"files": ["src/a.py", "src/b.py"]})
    _call("aegis_scan", {"files": ["src/b.py", "./src/a.py"]}, 2)
    _call("aegis_scan", {"files": ["src/a.py"]}, 3)
    later = _initialize()
    _call("aegis_scan", {"files": ["src/a.py"]}, 4)

    events = _activity(ws)
    assert [(e["event"], e["session"], e["files"]) for e in events] == [
        ("scan", session, ["src/a.py", "src/b.py"]),
        ("scan", session, ["src/a.py"]),
        ("scan", later, ["src/a.py"]),
    ]
    first = events[0]
    assert first["v"] == 1 and first["host"] == "claude-code" and first["binding"] == "pin"
    assert first["ts"].endswith("Z")
    assert _ledger(ws) == []  # scans never reach the outcome ledger


def test_a_scan_of_the_git_diff_records_the_diffed_files(ws, monkeypatch):
    from aegis_core import gitsafe

    monkeypatch.setattr(gitsafe, "changed_files", lambda cwd, mode="working", **kw: ["src/b.py"])
    _initialize()
    _call("aegis_scan", {})
    (event,) = _activity(ws)
    assert (event["files"], event["basis"]) == (["src/b.py"], "git_diff")


def test_a_failed_scan_records_nothing(ws):
    _initialize()
    is_error, _ = _call("aegis_scan", {"files": ["../escape.py"]})
    assert is_error
    assert _activity(ws) == []


def test_an_in_process_scan_without_a_session_records_nothing(ws):
    from aegis_mcp.tools import execute_tool

    execute_tool("aegis_scan", {"workspace": str(ws), "files": ["src/a.py"]})
    assert _activity(ws) == []


def test_an_unwritable_activity_log_never_fails_the_scan(ws, capsys):
    (ws / ".aegis" / "state").mkdir(parents=True)
    (ws / ".aegis" / "state" / "activity.jsonl").mkdir()  # cannot be appended to
    _initialize()
    is_error, payload = _call("aegis_scan", {"files": ["src/a.py"]})
    assert not is_error and payload["relevant_rules"]
    assert "scan event not recorded" in capsys.readouterr().err


# ── edit events from reports ─────────────────────────────────────────────────

def test_report_files_record_an_edit_event(ws):
    session = _initialize()
    is_error, payload = _call("aegis_report_outcome", {
        "outcome": "tp", "rules_used": ["trap-x"], "idempotency_key": "e1", "files": ["src/a.py", str(ws / "src" / "b.py")],
    })
    assert not is_error, payload
    (event,) = _activity(ws)
    assert (event["event"], event["session"], event["host"], event["files"]) == (
        "edit", session, "claude-code", ["src/a.py", "src/b.py"])
    # A retry of the same report records the edit once.
    _call("aegis_report_outcome", {"outcome": "tp", "rules_used": ["trap-x"], "idempotency_key": "e1",
                                   "files": ["src/a.py", "src/b.py"]}, 2)
    assert len(_activity(ws)) == 1


@pytest.mark.parametrize("files,error", [
    (["../outside.py"], "path traversal blocked"),
    ("src/a.py", "'files' must be a list of file paths"),
    ([1], "'files' must be a list of file paths"),
])
def test_bad_report_files_fail_the_report_and_write_nothing(ws, files, error):
    _initialize()
    is_error, payload = _call("aegis_report_outcome", {"outcome": "tp", "rules_used": ["trap-x"],
                                                       "idempotency_key": "bad", "files": files})
    assert is_error
    assert error in payload["error"]
    assert _ledger(ws) == [] and _activity(ws) == []


def test_the_report_schema_offers_optional_files():
    tool = next(t for t in server.TOOL_DEFINITIONS if t["name"] == "aegis_report_outcome")
    files = tool["inputSchema"]["properties"]["files"]
    assert files["type"] == "array" and files["items"] == {"type": "string"}
    assert "files" not in tool["inputSchema"]["required"]

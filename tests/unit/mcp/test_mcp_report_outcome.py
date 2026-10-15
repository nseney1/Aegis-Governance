"""aegis_report_outcome: one advisory ledger row per rule, attributed by the server.

A row records ``source: "mcp"`` plus the client host and the server session, both
owned by the server: nothing in the tool arguments can choose them. A report needs
an idempotency key, so a retried call is recorded once, even when the retry comes
from a new session after a reconnect. A report names at least one rule: an outcome
with no rule has nothing to credit.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import aegis_mcp.server as server
from aegis_mcp.tools import execute_tool

KEY_REQUIRED = (
    "'idempotency_key' is required: send a unique key per report so a retry is never recorded twice."
)
RULES_REQUIRED = (
    "'rules_used' must name at least one rule from aegis_scan: "
    "an outcome with no rule has nothing to credit."
)


def _workspace_with_rule(root: Path, rule: str = "trap-x") -> Path:
    rules = root / ".aegis" / "rules" / "traps"
    rules.mkdir(parents=True)
    (rules / f"{rule}.md").write_text(
        f"---\nid: {rule}\ntype: trap\nhypothesis: h\nprediction: p\n---\n# x\n",
        encoding="utf-8",
    )
    return root


def _rows(ws: Path) -> list:
    path = ws / ".aegis" / "evidence" / "signals.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


@pytest.fixture
def served(tmp_path, monkeypatch):
    """A server bound to a governed workspace and initialized by a claude-code client."""
    ws = _workspace_with_rule(tmp_path / "ws")
    monkeypatch.setattr(server, "_canonical_workspace", str(ws))
    monkeypatch.setattr(server, "_workspace_error", None)
    monkeypatch.setattr(server, "_session_id", None)
    monkeypatch.setattr(server, "_client_platform", server._client_platform)
    server._tool_call_times.clear()
    server.handle_request({
        "jsonrpc": "2.0", "id": 0, "method": "initialize",
        "params": {"clientInfo": {"name": "claude-code", "version": "1.0"}},
    })
    return ws


def _call(arguments, req_id=1):
    response = server.handle_request({
        "jsonrpc": "2.0", "id": req_id, "method": "tools/call",
        "params": {"name": "aegis_report_outcome", "arguments": arguments},
    })
    return response, json.loads(response["result"]["content"][0]["text"])


def test_row_records_source_host_and_server_session(served):
    response, payload = _call({"outcome": "success", "rules_used": ["trap-x"], "idempotency_key": "r-1"})
    assert response["result"]["isError"] is False, payload
    row, = _rows(served)
    assert (row["cell"], row["signal"], row["source"]) == ("trap-x", "tp", "mcp")
    assert row["metadata"]["host"] == "claude"
    assert row["metadata"]["session"] == server._session_id
    assert len(server._session_id) == 32


def test_tool_arguments_cannot_choose_host_session_source_or_workspace(served, tmp_path):
    other = _workspace_with_rule(tmp_path / "other")
    response, payload = _call({
        "outcome": "success",
        "rules_used": ["trap-x"],
        "idempotency_key": "spoof-1",
        "host": "ci",
        "session": "forged-session",
        "source": "ci",
        "workspace": str(other),
        "_host": "ci",
        "_session": "forged-session",
    })
    assert response["result"]["isError"] is False, payload
    row, = _rows(served)
    assert row["source"] == "mcp"
    assert row["metadata"]["host"] == "claude"
    assert row["metadata"]["session"] == server._session_id
    assert _rows(other) == []


def test_missing_idempotency_key_is_rejected_and_records_nothing(served):
    response, payload = _call({"outcome": "success", "rules_used": ["trap-x"]})
    assert response["result"]["isError"] is True
    assert payload == {"status": "FAIL", "error": KEY_REQUIRED}
    assert _rows(served) == []


@pytest.mark.parametrize("key, error", [
    ("", KEY_REQUIRED),
    ("   ", KEY_REQUIRED),
    (None, KEY_REQUIRED),
    # A value of the wrong type breaks the published schema and is named as such.
    (7, "Invalid 'idempotency_key': 7. Expected a string."),
])
def test_blank_or_non_string_idempotency_key_is_rejected(served, key, error):
    response, payload = _call({"outcome": "success", "rules_used": ["trap-x"], "idempotency_key": key})
    assert response["result"]["isError"] is True
    assert payload == {"status": "FAIL", "error": error}
    assert _rows(served) == []


def test_retry_with_the_same_key_is_recorded_once(served):
    args = {"outcome": "fp", "rules_used": ["trap-x"], "idempotency_key": "retry-1"}
    _call(args, req_id=1)
    response, payload = _call(args, req_id=2)
    assert response["result"]["isError"] is False, payload
    assert len(_rows(served)) == 1


@pytest.mark.parametrize("alias", ["cells_used", "rules", "rule_id", "cell_id"])
def test_legacy_argument_names_are_rejected(served, alias):
    response, payload = _call({"outcome": "success", alias: ["trap-x"], "idempotency_key": "alias-1"})
    assert response["result"]["isError"] is True
    assert payload == {
        "status": "FAIL",
        "error": f"Unknown argument(s) for aegis_report_outcome: ['{alias}']",
    }
    assert _rows(served) == []


@pytest.mark.parametrize("outcome,signal", [
    ("success", "tp"), ("tp", "tp"), ("pass", "tp"),
    ("failure", "fp"), ("fp", "fp"), ("fail", "fp"),
    ("partial", "trigger"),
])
def test_outcome_maps_to_ledger_signal(served, outcome, signal):
    _call({"outcome": outcome, "rules_used": ["trap-x"], "idempotency_key": f"k-{outcome}"})
    row, = _rows(served)
    assert row["signal"] == signal


def test_invalid_outcome_is_rejected(served):
    response, payload = _call({"outcome": "maybe", "rules_used": ["trap-x"], "idempotency_key": "k"})
    assert response["result"]["isError"] is True
    assert payload["error"] == (
        "Invalid 'outcome': 'maybe'. Expected one of "
        "['success', 'partial', 'failure', 'tp', 'fp', 'pass', 'fail']."
    )


def test_unknown_rule_name_is_rejected(served):
    response, payload = _call({"outcome": "tp", "rules_used": ["no-such-rule"], "idempotency_key": "k"})
    assert response["result"]["isError"] is True
    assert payload["error"] == "Unknown rule(s): ['no-such-rule']. Only existing rules can be reported."
    assert _rows(served) == []


def test_rules_used_must_be_a_list_of_names(served):
    response, payload = _call({"outcome": "tp", "rules_used": "trap-x", "idempotency_key": "k"})
    assert response["result"]["isError"] is True
    assert payload["error"] == "'rules_used' must be a list of rule names."


def test_in_process_call_without_a_server_is_attributed_to_no_host(tmp_path):
    ws = _workspace_with_rule(tmp_path)
    result = execute_tool("aegis_report_outcome", {
        "workspace": str(ws), "outcome": "tp", "rules_used": ["trap-x"], "idempotency_key": "local-1",
    })
    assert result["status"] == "recorded"
    row, = _rows(ws)
    assert row["source"] == "mcp"
    assert row["metadata"]["host"] is None
    assert row["metadata"]["session"] is None


def test_rate_limit_still_applies_to_report_outcome(served):
    limit = server._RATE_LIMITS["aegis_report_outcome"][0]
    for i in range(limit):
        _call({"outcome": "tp", "rules_used": ["trap-x"], "idempotency_key": f"rl-{i}"}, req_id=i)
    response = server.handle_request({
        "jsonrpc": "2.0", "id": 99, "method": "tools/call",
        "params": {"name": "aegis_report_outcome",
                   "arguments": {"outcome": "tp", "rules_used": ["trap-x"], "idempotency_key": "rl-x"}},
    })
    assert response["error"]["code"] == -32000
    assert response["error"]["message"].startswith("Rate limit exceeded for 'aegis_report_outcome'")


def _reconnect(client_name="claude-code", req_id=5):
    server.handle_request({"jsonrpc": "2.0", "id": req_id, "method": "initialize",
                           "params": {"clientInfo": {"name": client_name}}})


def test_retry_from_a_new_session_returns_the_original_record(served):
    args = {"outcome": "tp", "rules_used": ["trap-x"], "idempotency_key": "cross-session"}
    _, first = _call(args)
    first_session = server._session_id
    _reconnect()
    assert server._session_id != first_session

    response, payload = _call(args, req_id=6)

    assert response["result"]["isError"] is False, payload
    assert payload == first
    row, = _rows(served)
    assert row["metadata"]["session"] == first_session


@pytest.mark.parametrize("reconnect", [False, True])
def test_reusing_a_key_for_a_different_report_is_refused(served, reconnect):
    _call({"outcome": "tp", "rules_used": ["trap-x"], "idempotency_key": "reused"})
    if reconnect:
        _reconnect()

    response, payload = _call({"outcome": "fp", "rules_used": ["trap-x"], "idempotency_key": "reused"}, req_id=6)

    assert response["result"]["isError"] is True
    assert payload == {
        "status": "FAIL",
        "error": "'idempotency_key' 'reused' was already used for a different report: "
                 "send a new key for each new report.",
    }
    row, = _rows(served)
    assert row["signal"] == "tp"


@pytest.mark.parametrize("arguments", [
    {"outcome": "tp", "idempotency_key": "no-rules"},
    {"outcome": "tp", "idempotency_key": "no-rules", "rules_used": []},
])
def test_a_report_without_rules_is_rejected_and_records_nothing(served, arguments):
    response, payload = _call(arguments)
    assert response["result"]["isError"] is True
    assert payload == {"status": "FAIL", "error": RULES_REQUIRED}
    assert _rows(served) == []


def test_schema_requires_a_key_and_at_least_one_rule():
    tool = next(t for t in server.TOOL_DEFINITIONS if t["name"] == "aegis_report_outcome")
    schema = tool["inputSchema"]
    assert sorted(schema["required"]) == ["idempotency_key", "outcome", "rules_used"]
    assert schema["properties"]["rules_used"]["minItems"] == 1


@pytest.mark.parametrize("client_name,host", [
    ("claude-code", "claude"),
    ("antigravity-client", "gemini"),
    ("codex-mcp-client", "codex"),
    ("some-new-agent", "generic"),
    ("", "generic"),
])
def test_row_host_names_the_client_and_an_unknown_client_is_generic(served, client_name, host):
    _reconnect(client_name)
    response, payload = _call({"outcome": "tp", "rules_used": ["trap-x"], "idempotency_key": f"h-{client_name}"})
    assert response["result"]["isError"] is False, payload
    row, = _rows(served)
    assert row["metadata"]["host"] == host

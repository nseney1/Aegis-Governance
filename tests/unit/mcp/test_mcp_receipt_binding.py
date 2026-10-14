"""MCP receipt binding and canonical-workspace enforcement (v0.89 audit fixes).

v0.89.0 shipped two gaps in the receipt flow:

* The canonical-workspace injection sat after an unconditional ``return`` and
  never ran, so a caller could request and redeem a receipt whose arguments
  named a *different* Soma workspace and mutate it.
* Receipts were issued and verified with empty file and cell digests, so a
  change to the target file or to the governance cells between issuance and
  redemption did not invalidate the receipt.

These tests drive ``handle_request`` end to end with real tool execution: the
trust boundary is not mocked.
"""
import json
import os
import time

import pytest

import aegis_mcp.server as server
from aegis_core import receipts

STALE_RECEIPT = "Invalid, expired, or mismatched receipt."


def _make_workspace(root, cell_name):
    cells = root / ".aegis" / "rules" / "vacuoles"
    cells.mkdir(parents=True)
    (cells / f"{cell_name}.md").write_text(
        "---\n"
        f"id: {cell_name}\n"
        "type: vacuole\n"
        "hypothesis: Example hypothesis\n"
        "prediction: Example prediction\n"
        "---\n"
        "# Example\n",
        encoding="utf-8",
    )
    return root


@pytest.fixture
def workspaces(tmp_path, monkeypatch):
    canonical = _make_workspace(tmp_path / "canonical", "cell-canonical")
    other = _make_workspace(tmp_path / "other", "cell-other")
    monkeypatch.setattr(server, "_session_token", "session-test")
    monkeypatch.setattr(server, "_canonical_workspace", os.path.realpath(str(canonical)))
    monkeypatch.setattr(server, "_execution_enabled", True)
    monkeypatch.setenv("AEGIS_WORKSPACE", str(canonical))
    monkeypatch.delenv("AEGIS_ROOT", raising=False)
    server._tool_call_times.clear()
    receipts.clear_receipts()
    yield canonical, other
    receipts.clear_receipts()


def _call(name, arguments, req_id=1):
    return server.handle_request({
        "jsonrpc": "2.0", "id": req_id, "method": "tools/call",
        "params": {"name": name, "arguments": arguments},
    })


def _request_receipt(operation, arguments):
    resp = _call("aegis_request_receipt", {"operation": operation, "arguments": arguments})
    assert "result" in resp, resp
    return json.loads(resp["result"]["content"][0]["text"])["receipt"]


def _text(resp):
    return resp["result"]["content"][0]["text"]


# ── Canonical workspace enforcement ─────────────────────────────────────

def test_write_tool_cannot_be_redirected_to_another_workspace(workspaces):
    canonical, other = workspaces
    args = {
        "outcome": "success",
        "cells_used": ["cell-canonical"],
        "workspace": str(other),
        "idempotency_key": "canonical-workspace-test",
    }
    receipt = _request_receipt("aegis_report_outcome", args)
    resp = _call("aegis_report_outcome", dict(args, receipt=receipt))
    assert "result" in resp and not resp["result"]["isError"], resp
    assert (canonical / ".aegis" / "evidence" / "signals.jsonl").exists()
    assert not (other / ".aegis" / "evidence").exists(), (
        "write tool mutated a caller-selected workspace"
    )


def test_read_tool_ignores_client_workspace(workspaces):
    canonical, other = workspaces
    resp = _call("aegis_list_rules", {"workspace": str(other)})
    names = {c.get("_name") for c in json.loads(_text(resp))}
    assert "cell-canonical" in names
    assert "cell-other" not in names, "read tool served a caller-selected workspace"


def test_write_tool_fails_closed_without_canonical_workspace(workspaces, monkeypatch):
    monkeypatch.setattr(server, "_canonical_workspace", None)
    resp = _call("aegis_request_receipt",
                 {"operation": "aegis_report_outcome", "arguments": {"outcome": "success"}})
    assert "error" in resp, resp


# ── Receipt state binding ───────────────────────────────────────────────

def test_receipt_records_nonempty_state_digests(workspaces):
    canonical, _ = workspaces
    (canonical / "target.py").write_text("x = 1\n", encoding="utf-8")
    receipt = _request_receipt("aegis_propose_change",
                               {"file_path": "target.py", "proposed_content": "x = 2\n"})
    stored = receipts._receipt_store[receipt]
    assert stored["file_digest"], "receipt is not bound to the target file"
    assert stored["cell_digest"], "receipt is not bound to the governance cells"


def test_receipt_redeems_when_state_is_unchanged(workspaces):
    canonical, _ = workspaces
    (canonical / "target.py").write_text("x = 1\n", encoding="utf-8")
    args = {"file_path": "target.py", "proposed_content": "x = 2\n"}
    receipt = _request_receipt("aegis_propose_change", args)
    resp = _call("aegis_propose_change", dict(args, receipt=receipt))
    assert "result" in resp, resp


def test_receipt_is_stale_after_target_file_changes(workspaces):
    canonical, _ = workspaces
    target = canonical / "target.py"
    target.write_text("x = 1\n", encoding="utf-8")
    args = {"file_path": "target.py", "proposed_content": "x = 2\n"}
    receipt = _request_receipt("aegis_propose_change", args)
    target.write_text("x = 'changed after scan'\n", encoding="utf-8")
    resp = _call("aegis_propose_change", dict(args, receipt=receipt))
    assert resp.get("error", {}).get("message") == STALE_RECEIPT, resp


def test_receipt_is_stale_after_cells_change(workspaces):
    canonical, _ = workspaces
    args = {"outcome": "success", "cells_used": []}
    receipt = _request_receipt("aegis_report_outcome", args)
    cell = canonical / ".aegis" / "rules" / "vacuoles" / "cell-canonical.md"
    cell.write_text(cell.read_text(encoding="utf-8") + "\nedited\n", encoding="utf-8")
    resp = _call("aegis_report_outcome", dict(args, receipt=receipt))
    assert resp.get("error", {}).get("message") == STALE_RECEIPT, resp
    assert not (canonical / ".aegis" / "evidence" / "outcomes.jsonl").exists()


def test_receipt_flow_works_after_cell_edited_since_creation(workspaces):
    """BUG-035: a cell edited after creation made every receipt request fail
    on Windows with an internal error, so no write tool could run."""
    canonical, _ = workspaces
    cell = canonical / ".aegis" / "rules" / "vacuoles" / "cell-canonical.md"
    time.sleep(0.05)
    cell.write_text(cell.read_text(encoding="utf-8") + "\nedited\n", encoding="utf-8")
    args = {"outcome": "success", "cells_used": [], "idempotency_key": "bug-035"}
    receipt = _request_receipt("aegis_report_outcome", args)
    resp = _call("aegis_report_outcome", dict(args, receipt=receipt))
    assert "result" in resp and not resp["result"]["isError"], resp


def test_receipt_request_rejects_paths_outside_workspace(workspaces):
    resp = _call("aegis_request_receipt", {
        "operation": "aegis_propose_change",
        "arguments": {"file_path": "../other/escape.py", "proposed_content": ""},
    })
    assert "error" in resp, resp


def test_receipt_is_single_use(workspaces):
    args = {
        "outcome": "success",
        "cells_used": [],
        "idempotency_key": "single-use-test",
    }
    receipt = _request_receipt("aegis_report_outcome", args)
    first = _call("aegis_report_outcome", dict(args, receipt=receipt))
    assert "result" in first and not first["result"]["isError"], first
    second = _call("aegis_report_outcome", dict(args, receipt=receipt))
    assert "error" in second, "receipt was redeemed twice"


def test_receipt_burned_on_stale_digest_and_cannot_replay_when_reverted(workspaces):
    """S3 burn-before-compare invariant: presenting a receipt when target file digest
    mismatches burns the nonce in .aegis/receipts.jsonl so reverting the file cannot replay it."""
    canonical, _ = workspaces
    target = canonical / "target.py"
    target.write_text("x = 1\n", encoding="utf-8")
    args = {"file_path": "target.py", "proposed_content": "x = 2\n"}
    receipt = _request_receipt("aegis_propose_change", args)

    # Mutate file so digest mismatches on first presentation
    target.write_text("x = 999\n", encoding="utf-8")
    first = _call("aegis_propose_change", dict(args, receipt=receipt))
    assert first.get("error", {}).get("message") == STALE_RECEIPT
    assert (canonical / ".aegis" / "receipts.jsonl").is_file()

    # Revert file back to original state and attempt replay -> must fail because nonce was burned
    target.write_text("x = 1\n", encoding="utf-8")
    replay = _call("aegis_propose_change", dict(args, receipt=receipt))
    assert "error" in replay, "burned receipt was replayed after reverting file"


def test_receipt_burned_on_path_traversal_value_error_in_server(workspaces):
    """S3 burn-before-compare invariant: if _state_digests raises ValueError (e.g. path traversal)
    during redemption, server.py burns the receipt before returning -32602."""
    canonical, _ = workspaces
    args = {"outcome": "success", "cells_used": [], "idempotency_key": "burn-traversal"}
    receipt = _request_receipt("aegis_report_outcome", args)

    # Redeem with a path traversal file_path injected into arguments
    bad_call = _call("aegis_report_outcome", dict(args, file_path="../escape.py", receipt=receipt))
    assert bad_call.get("error", {}).get("code") == -32602

    # Attempting to redeem with the original valid arguments must now fail because receipt was burned
    replay = _call("aegis_report_outcome", dict(args, receipt=receipt))
    assert "error" in replay, "receipt was not burned after ValueError in server.py"


def test_receipt_digest_rejects_symlinked_cell(workspaces):
    from aegis_core.rule_inventory import CellInventoryError

    canonical, _ = workspaces
    target = canonical / '.aegis' / 'rules' / 'vacuoles' / 'cell-canonical.md'
    link = canonical / '.aegis' / 'rules' / 'vacuoles' / 'linked.md'
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip('symlinks are unavailable')

    with pytest.raises(CellInventoryError, match='symlink'):
        receipts.compute_rule_digest(str(canonical))

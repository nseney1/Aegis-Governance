"""Unit tests for v4.0.0 Wave 1 Lane C:
- 1-step receiptless telemetry reporting (aegis_report_outcome / aegis_capture_insight)
- Optional receipt validation (rejecting invalid/stale receipts when provided)
- Dynamic MCP client platform detection and ${SLOT.*} interpolation in aegis_scan
- Unified RuleInventory / load_parsed_rules and synced .aegis/rules/manifest.json
"""
from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path

import pytest

import aegis_mcp.server as server_module
from aegis_core.integrity import generate_manifest, save_manifest
from aegis_core.rule_inventory import (
    RuleInventory,
    RuleInventoryEntry,
    RuleMatch,
    find_matching_rules,
    load_parsed_rules,
)
from aegis_mcp.server import handle_request
from aegis_mcp.tools import TOOL_DEFINITIONS, execute_tool

REPO_ROOT = Path(__file__).resolve().parents[3]


def _make_workspace_with_rule(tmp_path: Path, rule_id: str = "invariant-tdd", body: str = "Use ${SLOT.TOOL_READ} with ${SLOT.MODEL_FAST}.\n") -> Path:
    rules_dir = tmp_path / ".aegis" / "rules" / "invariants"
    rules_dir.mkdir(parents=True, exist_ok=True)
    rule_file = rules_dir / f"{rule_id}.md"
    rule_file.write_text(
        f"---\n"
        f"id: {rule_id}\n"
        f"type: invariant\n"
        f"enforcement: gate\n"
        f"hypothesis: Always use ${'{SLOT.TOOL_READ}'} before editing.\n"
        f"prediction: Edits without ${'{SLOT.TOOL_READ}'} fail.\n"
        f"target_paths:\n"
        f"  - src/*.py\n"
        f"---\n"
        f"# {rule_id}\n\n"
        f"{body}",
        encoding="utf-8",
    )
    (tmp_path / ".aegis" / "evidence").mkdir(parents=True, exist_ok=True)
    (tmp_path / "src").mkdir(parents=True, exist_ok=True)
    (tmp_path / "src" / "app.py").write_text("x = 1\n", encoding="utf-8")
    return tmp_path


def test_one_step_report_outcome_with_rules_used_succeeds_without_receipt(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ws = _make_workspace_with_rule(tmp_path, "invariant-tdd")
    monkeypatch.setattr(server_module, "_canonical_workspace", str(ws))
    monkeypatch.setenv("AEGIS_WORKSPACE", str(ws))
    handle_request({"jsonrpc": "2.0", "id": 0, "method": "initialize"})

    # 1-step call WITHOUT calling aegis_request_receipt first
    resp = handle_request({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "aegis_report_outcome",
            "arguments": {
                "outcome": "success",
                "rules_used": ["invariant-tdd"],
                "idempotency_key": "k1",
                "tests_passed": True,
            },
        },
    })
    assert "result" in resp, resp
    assert resp["result"]["isError"] is False
    payload = json.loads(resp["result"]["content"][0]["text"])
    assert payload["status"] == "recorded"
    assert len(payload["records"]) == 1
    assert payload["records"][0]["cell"] == "invariant-tdd"

    # Also test 1-step call when idempotency_key is omitted (auto-defaults to UUID)
    resp_no_key = handle_request({
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/call",
        "params": {
            "name": "aegis_report_outcome",
            "arguments": {
                "outcome": "pass",
                "rules_used": ["invariant-tdd"],
            },
        },
    })
    assert "result" in resp_no_key, resp_no_key
    assert resp_no_key["result"]["isError"] is False
    payload_no_key = json.loads(resp_no_key["result"]["content"][0]["text"])
    assert payload_no_key["status"] == "recorded"


def test_report_outcome_with_invalid_receipt_still_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ws = _make_workspace_with_rule(tmp_path, "invariant-tdd")
    monkeypatch.setattr(server_module, "_canonical_workspace", str(ws))
    handle_request({"jsonrpc": "2.0", "id": 0, "method": "initialize"})

    resp = handle_request({
        "jsonrpc": "2.0",
        "id": 3,
        "method": "tools/call",
        "params": {
            "name": "aegis_report_outcome",
            "arguments": {
                "outcome": "success",
                "rules_used": ["invariant-tdd"],
                "idempotency_key": "k-bad",
                "receipt": "bad-receipt",
            },
        },
    })
    assert "error" in resp
    assert resp["error"]["code"] == -32600
    assert "Invalid, expired, or mismatched receipt." in resp["error"]["message"]


def test_initialize_detects_client_platform_and_interpolates_slots_in_scan(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ws = _make_workspace_with_rule(tmp_path, "invariant-tdd")
    monkeypatch.setattr(server_module, "_canonical_workspace", str(ws))
    monkeypatch.setenv("AEGIS_WORKSPACE", str(ws))

    # Initialize as claude-code
    handle_request({
        "jsonrpc": "2.0",
        "id": 10,
        "method": "initialize",
        "params": {
            "clientInfo": {"name": "claude-code", "version": "1.0"},
        },
    })
    assert server_module._client_platform == "claude"

    scan_resp = handle_request({
        "jsonrpc": "2.0",
        "id": 11,
        "method": "tools/call",
        "params": {
            "name": "aegis_scan",
            "arguments": {"files": ["src/app.py"]},
        },
    })
    assert "result" in scan_resp
    scan_data = json.loads(scan_resp["result"]["content"][0]["text"])
    assert "Read" in scan_data["guidance"]
    assert "haiku" in scan_data["guidance"]
    assert "${SLOT." not in scan_data["guidance"]

    # Re-initialize as default (gemini)
    handle_request({
        "jsonrpc": "2.0",
        "id": 12,
        "method": "initialize",
        "params": {
            "clientInfo": {"name": "antigravity-client", "version": "2.0"},
        },
    })
    assert server_module._client_platform == "gemini"


def test_repo_root_aegis_scan_loads_cleanly_without_integrity_warnings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AEGIS_WORKSPACE", str(REPO_ROOT))
    err_buf = io.StringIO()
    with contextlib.redirect_stderr(err_buf):
        res = execute_tool(
            "aegis_scan",
            {"workspace": str(REPO_ROOT), "files": ["aegis_mcp/server.py"]},
        )
    stderr_output = err_buf.getvalue()
    assert "excluding tampered rule" not in stderr_output
    assert "hash mismatch" not in stderr_output
    assert res["stats"]["total_rules"] >= 45


def test_load_parsed_rules_and_rule_inventory_primary_definitions(tmp_path: Path) -> None:
    rules = load_parsed_rules(REPO_ROOT)
    assert len(rules) >= 45
    sample = rules[0]
    for key in ("_name", "_path", "_body", "_full", "_digest"):
        assert key in sample

    ws = _make_workspace_with_rule(tmp_path, "invariant-tdd")
    matches = find_matching_rules(ws / ".aegis" / "rules", ["src/app.py"])
    assert len(matches) == 1
    m = matches[0]
    assert isinstance(m, RuleMatch)
    assert m.rule_id == "invariant-tdd"
    assert m.rule_type == "invariant"
    assert m.rule_path.endswith("invariant-tdd.md")
    assert m.cell_id == m.rule_id

    # Verify manifest dual keys (auto-sync was removed: review H1)
    manifest = generate_manifest(ws / ".aegis" / "rules")
    assert "rules" in manifest and "cells" in manifest
    assert manifest["rule_count"] == 1 and manifest["cell_count"] == 1
    save_manifest(ws, manifest)

    # Verify schema exposes rules_used and scaffold_rule
    report_def = next(t for t in TOOL_DEFINITIONS if t["name"] == "aegis_report_outcome")
    assert "rules_used" in report_def["inputSchema"]["properties"]
    insight_def = next(t for t in TOOL_DEFINITIONS if t["name"] == "aegis_capture_insight")
    assert "scaffold_rule" in insight_def["inputSchema"]["properties"]
    assert "rule_id" in insight_def["inputSchema"]["properties"]

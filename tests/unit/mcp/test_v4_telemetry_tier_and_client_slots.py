"""MCP client platform detection, ${SLOT.*} interpolation in aegis_scan, and the
unified RuleInventory / load_parsed_rules used by the server.
"""
from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path

import pytest

import aegis_mcp.server as server_module
from aegis_mcp.server import handle_request
from aegis_mcp.tools import execute_tool

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


def test_initialize_detects_client_platform_and_interpolates_slots_in_scan(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ws = _make_workspace_with_rule(tmp_path, "invariant-tdd")
    monkeypatch.setattr(server_module, "_canonical_workspace", str(ws))
    monkeypatch.setattr(server_module, "_session_id", None)
    monkeypatch.setattr(server_module, "_client_platform", server_module._client_platform)
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
    assert server_module._client_platform == "claude-code"

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

    # Re-initialize as Antigravity: its own host id, never "gemini"
    handle_request({
        "jsonrpc": "2.0",
        "id": 12,
        "method": "initialize",
        "params": {
            "clientInfo": {"name": "antigravity-client", "version": "2.0"},
        },
    })
    assert server_module._client_platform == "antigravity"


def test_unknown_client_gets_the_generic_slot_table_not_another_vendors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ws = _make_workspace_with_rule(tmp_path, "invariant-tdd")
    monkeypatch.setattr(server_module, "_canonical_workspace", str(ws))
    monkeypatch.setattr(server_module, "_session_id", None)
    monkeypatch.setattr(server_module, "_client_platform", server_module._client_platform)
    handle_request({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                    "params": {"clientInfo": {"name": "some-new-agent"}}})

    scan_resp = handle_request({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                                "params": {"name": "aegis_scan", "arguments": {"files": ["src/app.py"]}}})

    guidance = json.loads(scan_resp["result"]["content"][0]["text"])["guidance"]
    assert "read_file" in guidance and "fast-tier" in guidance
    assert "view_file" not in guidance and "flash" not in guidance


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



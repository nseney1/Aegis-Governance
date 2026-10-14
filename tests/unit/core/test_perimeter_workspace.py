"""Tests for Phase 16: Perimeter & Edge Workspace Adoption.

Verifies that:
1. aegis_sdk.Governance initializes with and exposes Workspace instances.
2. aegis_core.receipts functions accept Workspace instances and behave identically.
3. soma_mcp server and tools operate with strongly-typed Workspace instances.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import aegis_mcp.security as mcp_security
from aegis_core.receipts import (
    ReceiptStore,
    compute_cell_digest,
    compute_file_digest,
    issue_receipt,
    verify_receipt,
)
from aegis_core.workspace import Workspace
from aegis_mcp.tools import execute_tool
from aegis_sdk import Governance


@pytest.fixture
def mock_soma_workspace(tmp_path: Path) -> Path:
    """Create a minimal valid Soma workspace directory structure."""
    cells_dir = tmp_path / ".aegis" / "rules" / "walls"
    cells_dir.mkdir(parents=True)
    sample_cell = cells_dir / "sample_rule.md"
    sample_cell.write_text(
        "---\nname: sample-rule\ntype: wall\nenforcement: gate\n---\nRule content\n",
        encoding="utf-8",
    )
    metrics_dir = tmp_path / ".aegis" / "metrics"
    metrics_dir.mkdir(parents=True)
    tracked_file = tmp_path / "hello.py"
    tracked_file.write_text("print('hello')\n", encoding="utf-8")
    return tmp_path


class TestGovernanceWorkspacePorcelain:
    """Verifies aegis_sdk.Governance integration with Workspace."""

    def test_governance_init_with_path_creates_workspace(self, mock_soma_workspace: Path):
        gov = Governance(project_root=mock_soma_workspace)
        assert hasattr(gov, "workspace")
        assert isinstance(gov.workspace, Workspace)
        assert gov.workspace.root == mock_soma_workspace.resolve()
        assert gov.root == mock_soma_workspace.resolve()
        assert gov.rules_dir == mock_soma_workspace.resolve() / ".aegis" / "rules"
        assert gov.metrics_dir == mock_soma_workspace.resolve() / ".aegis" / "metrics"

    def test_governance_init_with_workspace_object(self, mock_soma_workspace: Path):
        ws = Workspace.confine(mock_soma_workspace)
        gov = Governance(project_root=ws)
        assert gov.workspace is ws
        assert gov.root == ws.root
        assert gov.rules_dir == ws.rules_dir
        assert gov.metrics_dir == ws.metrics_dir

    def test_governance_list_cells_with_workspace(self, mock_soma_workspace: Path):
        ws = Workspace.confine(mock_soma_workspace)
        gov = Governance(project_root=ws)
        cells = gov.list_cells()
        assert len(cells) == 1
        assert cells[0]["_name"] == "sample_rule"


class TestReceiptsWorkspaceInteroperability:
    """Verifies aegis_core.receipts handles Workspace value objects."""

    def test_compute_file_digest_with_workspace(self, mock_soma_workspace: Path):
        ws = Workspace.confine(mock_soma_workspace)
        digest_from_str = compute_file_digest(str(mock_soma_workspace), ["hello.py"])
        digest_from_ws = compute_file_digest(ws, ["hello.py"])
        assert digest_from_ws == digest_from_str
        assert len(digest_from_ws) == 64

    def test_compute_cell_digest_with_workspace(self, mock_soma_workspace: Path):
        ws = Workspace.confine(mock_soma_workspace)
        digest_from_str = compute_cell_digest(str(mock_soma_workspace))
        digest_from_ws = compute_cell_digest(ws)
        assert digest_from_ws == digest_from_str
        assert len(digest_from_ws) == 64

    def test_issue_and_verify_receipt_with_workspace(self, mock_soma_workspace: Path):
        ws = Workspace.confine(mock_soma_workspace)
        file_digest = compute_file_digest(ws, ["hello.py"])
        cell_digest = compute_cell_digest(ws)

        rid = issue_receipt(
            session_id="test_session",
            workspace=ws,
            operation="aegis_propose_change",
            args={"file_path": "hello.py"},
            file_digest=file_digest,
            cell_digest=cell_digest,
            ttl_seconds=60,
        )
        assert isinstance(rid, str)

        # Verify using Workspace instance
        valid = verify_receipt(
            receipt_id=rid,
            session_id="test_session",
            workspace=ws,
            operation="aegis_propose_change",
            args={"file_path": "hello.py"},
            file_digest=file_digest,
            cell_digest=cell_digest,
            consume=True,
        )
        assert valid is True

    def test_receipt_store_workspace_equivalence(self, mock_soma_workspace: Path):
        store = ReceiptStore()
        ws = Workspace.confine(mock_soma_workspace)
        rid = store.issue(
            session_id="sess",
            workspace=ws,
            operation="op",
            args={},
            file_digest="f",
            cell_digest="c",
        )
        # Verify passing string path matches receipt issued with Workspace
        assert store.verify(
            receipt_id=rid,
            session_id="sess",
            workspace=str(mock_soma_workspace.resolve()),
            operation="op",
            args={},
            file_digest="f",
            cell_digest="c",
            consume=False,
        ) is True


class TestMCPSecurityAndToolsWorkspace:
    """Verifies soma_mcp security and tool handlers with Workspace."""

    def test_security_module_reexports_workspace(self):
        assert hasattr(mcp_security, "Workspace")
        assert mcp_security.Workspace is Workspace

    def test_mcp_execute_tool_with_workspace_object(self, mock_soma_workspace: Path):
        ws = Workspace.confine(mock_soma_workspace)
        result = execute_tool("aegis_list_cells", {"workspace": ws})
        data = json.loads(result) if isinstance(result, str) else result
        assert isinstance(data, list)
        assert any(c.get("name") == "sample-rule" or c.get("_name") == "sample_rule" for c in data)

    def test_mcp_server_canonical_workspace_type(self, monkeypatch, mock_soma_workspace: Path):
        from aegis_mcp import server
        ws = Workspace.confine(mock_soma_workspace)
        monkeypatch.setattr(server, "_canonical_workspace", ws)
        # Verify _state_digests uses Workspace cleanly
        file_d, cell_d = server._state_digests({"file_path": "hello.py"})
        assert len(file_d) == 64
        assert len(cell_d) == 64

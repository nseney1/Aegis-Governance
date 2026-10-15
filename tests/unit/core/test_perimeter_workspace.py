"""Tests for Phase 16: Perimeter & Edge Workspace Adoption.

Verifies that:
1. aegis_sdk.Governance initializes with and exposes Workspace instances.
2. aegis_mcp tools operate with strongly-typed Workspace instances.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

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


class TestMCPToolsWorkspace:
    """Verifies MCP tool handlers with Workspace."""

    def test_mcp_execute_tool_with_workspace_object(self, mock_soma_workspace: Path):
        ws = Workspace.confine(mock_soma_workspace)
        result = execute_tool("aegis_list_rules", {"workspace": ws})
        data = json.loads(result) if isinstance(result, str) else result
        assert isinstance(data, list)
        assert any(c.get("name") == "sample-rule" or c.get("_name") == "sample_rule" for c in data)

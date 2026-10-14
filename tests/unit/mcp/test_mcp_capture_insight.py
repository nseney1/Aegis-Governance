from pathlib import Path
"""TDD tests for soma_capture_insight MCP tool handler.

Gate 1 return: MCP tool was shipped without tests (Gate 1 violation
caught by Tempest review).
"""
import json
import os
import sys
import pytest

# The MCP tools module uses execute_tool() as its entry point
REPO_ROOT = str(next(p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").exists()))


class TestMCPCaptureInsight:
    """Tests for the soma_capture_insight MCP tool handler."""

    def test_records_valid_insight(self, tmp_path, monkeypatch):
        """Valid insight returns status=recorded."""
        from aegis_mcp.tools import execute_tool

        workspace = str(tmp_path)
        os.makedirs(os.path.join(workspace, ".aegis", "rules"), exist_ok=True)
        monkeypatch.setattr("aegis_mcp.tools.resolve_workspace", lambda args=None: workspace)

        result = execute_tool("aegis_capture_insight", {
            "insight": "Check the aspect ratio",
            "context_files": ["images/sprites.py"],
            "category": "attention_gap",
        })

        assert result["status"] == "recorded"
        assert "insight" in result
        assert result["insight"]["insight"] == "Check the aspect ratio"

    def test_rejects_empty_files(self, tmp_path, monkeypatch):
        """Empty context_files returns an error."""
        from aegis_mcp.tools import execute_tool

        workspace = str(tmp_path)
        os.makedirs(os.path.join(workspace, ".aegis", "rules"), exist_ok=True)
        monkeypatch.setattr("aegis_mcp.tools.resolve_workspace", lambda args=None: workspace)

        result = execute_tool("aegis_capture_insight", {
            "insight": "Something",
            "context_files": [],
        })

        assert "error" in result

    def test_persists_to_jsonl(self, tmp_path, monkeypatch):
        """Insight is persisted to .aegis/human_insights.jsonl."""
        from aegis_mcp.tools import execute_tool

        workspace = str(tmp_path)
        os.makedirs(os.path.join(workspace, ".aegis", "rules"), exist_ok=True)
        monkeypatch.setattr("aegis_mcp.tools.resolve_workspace", lambda args=None: workspace)

        execute_tool("aegis_capture_insight", {
            "insight": "Test persistence",
            "context_files": ["a.py"],
        })

        jsonl_path = os.path.join(workspace, ".aegis", "human_insights.jsonl")
        assert os.path.exists(jsonl_path)
        with open(jsonl_path) as f:
            record = json.loads(f.readline())
        assert record["insight"] == "Test persistence"

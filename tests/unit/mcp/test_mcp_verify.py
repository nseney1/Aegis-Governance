from pathlib import Path
"""TDD Gate 1 tests for soma_verify_changes and soma_checkpoint MCP tools.

These tools provide MCP parity with the CLI commands (contract-mcp-cli-parity cell):
- soma_verify_changes: runs Layer 1 verification on specified files
- soma_checkpoint: runs deterministic quality checks on workspace
"""
import json
import os
import sys
import textwrap
import pytest

REPO_ROOT = str(next(p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").exists()))
sys.path.insert(0, REPO_ROOT)


# ── soma_verify_changes ──────────────────────────────────────────────────


class TestMCPVerifyChanges:
    """Tests for soma_verify_changes MCP tool handler."""

    def test_verify_changes_registered_in_execute_tool(self):
        """soma_verify_changes must be handled by execute_tool without raising ValueError."""
        from aegis_mcp.tools import execute_tool
        # Should not raise "Unknown tool" ValueError
        result = execute_tool("aegis_verify_changes", {"files": [], "workspace": "/tmp"})
        assert isinstance(result, dict)

    def test_verify_changes_clean_file_returns_pass(self, tmp_path, monkeypatch):
        """Clean Python file returns status=PASS."""
        from aegis_mcp.tools import execute_tool

        (tmp_path / ".aegis" / "rules").mkdir(parents=True)
        code_file = tmp_path / "clean.py"
        code_file.write_text(textwrap.dedent("""\
            def compute(a: int, b: int) -> int:
                return a + b

            def main():
                return compute(1, 2)
        """))

        monkeypatch.setattr("aegis_mcp.tools.resolve_workspace", lambda args=None: str(tmp_path))
        result = execute_tool("aegis_verify_changes", {
            "files": ["clean.py"],
            "workspace": str(tmp_path),
        })

        assert result["status"] == "PASS"
        assert "evidence" in result
        assert isinstance(result["evidence"], list)

    def test_verify_changes_defective_file_returns_fail(self, tmp_path, monkeypatch):
        """File with forbidden unguarded import returns status=FAIL."""
        from aegis_mcp.tools import execute_tool

        (tmp_path / ".aegis" / "rules").mkdir(parents=True)
        bad_file = tmp_path / "broken.py"
        bad_file.write_text("import nonexistent_forbidden_package_xyz\n")

        monkeypatch.setattr("aegis_mcp.tools.resolve_workspace", lambda args=None: str(tmp_path))
        result = execute_tool("aegis_verify_changes", {
            "files": ["broken.py"],
            "workspace": str(tmp_path),
        })

        assert result["status"] == "FAIL"

    def test_verify_changes_returns_summary_string(self, tmp_path, monkeypatch):
        """Result must contain a 'summary' string describing Layer 1 outcome."""
        from aegis_mcp.tools import execute_tool

        (tmp_path / ".aegis" / "rules").mkdir(parents=True)
        code_file = tmp_path / "simple.py"
        code_file.write_text("def hello(): return 'world'\n")

        monkeypatch.setattr("aegis_mcp.tools.resolve_workspace", lambda args=None: str(tmp_path))
        result = execute_tool("aegis_verify_changes", {
            "files": ["simple.py"],
            "workspace": str(tmp_path),
        })

        assert "summary" in result
        assert isinstance(result["summary"], str)
        assert "Layer 1" in result["summary"]

    def test_verify_changes_empty_files_returns_fail(self, tmp_path, monkeypatch):
        """Empty file list returns FAIL (empty list cannot pass verification)."""
        from aegis_mcp.tools import execute_tool

        (tmp_path / ".aegis" / "rules").mkdir(parents=True)
        monkeypatch.setattr("aegis_mcp.tools.resolve_workspace", lambda args=None: str(tmp_path))
        result = execute_tool("aegis_verify_changes", {
            "files": [],
            "workspace": str(tmp_path),
        })

        assert result["status"] == "FAIL"

    def test_verify_changes_includes_layer1_only_flag(self, tmp_path, monkeypatch):
        """Result must include layer1_only field reflecting the request."""
        from aegis_mcp.tools import execute_tool

        (tmp_path / ".aegis" / "rules").mkdir(parents=True)
        monkeypatch.setattr("aegis_mcp.tools.resolve_workspace", lambda args=None: str(tmp_path))
        result = execute_tool("aegis_verify_changes", {
            "files": [],
            "workspace": str(tmp_path),
            "layer1_only": True,
        })

        assert "layer1_only" in result


# ── soma_checkpoint ──────────────────────────────────────────────────────


class TestMCPCheckpoint:
    """Tests for soma_checkpoint MCP tool handler."""

    def test_checkpoint_registered_in_execute_tool(self, tmp_path, monkeypatch):
        """soma_checkpoint must be handled by execute_tool without raising ValueError."""
        from aegis_mcp.tools import execute_tool

        monkeypatch.setattr("aegis_mcp.tools.resolve_workspace", lambda args=None: str(tmp_path))
        result = execute_tool("aegis_checkpoint", {"workspace": str(tmp_path)})
        assert isinstance(result, dict)

    def test_checkpoint_clean_workspace_returns_pass(self, tmp_path, monkeypatch):
        """Empty workspace (no violations) returns status=PASS."""
        from aegis_mcp.tools import execute_tool

        (tmp_path / ".aegis" / "rules").mkdir(parents=True)
        monkeypatch.setattr("aegis_mcp.tools.resolve_workspace", lambda args=None: str(tmp_path))
        result = execute_tool("aegis_checkpoint", {"workspace": str(tmp_path)})

        assert result["status"] == "PASS"
        assert result["issue_count"] == 0

    def test_checkpoint_returns_issues_list(self, tmp_path, monkeypatch):
        """Result must contain an 'issues' list."""
        from aegis_mcp.tools import execute_tool

        (tmp_path / ".aegis" / "rules").mkdir(parents=True)
        monkeypatch.setattr("aegis_mcp.tools.resolve_workspace", lambda args=None: str(tmp_path))
        result = execute_tool("aegis_checkpoint", {"workspace": str(tmp_path)})

        assert "issues" in result
        assert isinstance(result["issues"], list)

    def test_checkpoint_nonexistent_workspace_returns_error(self, monkeypatch):
        """Nonexistent workspace directory returns error."""
        from aegis_mcp.tools import execute_tool

        monkeypatch.setattr("aegis_mcp.tools.resolve_workspace", lambda args=None: "/nonexistent/dir/xyz")
        result = execute_tool("aegis_checkpoint", {
            "workspace": "/nonexistent/dir/xyz",
        })

        assert "error" in result or result.get("status") == "FAIL"

    def test_checkpoint_workspace_with_issues_returns_fail(self, tmp_path, monkeypatch):
        """Workspace with hardcoded paths in src/ returns FAIL with issues."""
        from aegis_mcp.tools import execute_tool

        (tmp_path / ".aegis" / "rules").mkdir(parents=True)
        src = tmp_path / "src"
        src.mkdir()
        bad_file = src / "config.py"
        bad_file.write_text('DB_PATH = "/home/user/data/production.db"\n')

        monkeypatch.setattr("aegis_mcp.tools.resolve_workspace", lambda args=None: str(tmp_path))
        result = execute_tool("aegis_checkpoint", {"workspace": str(tmp_path)})

        assert result["status"] == "FAIL"
        assert result["issue_count"] > 0
        assert any(i["check"] == "hardcoded_paths" for i in result["issues"])

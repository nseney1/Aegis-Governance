from pathlib import Path
"""Security hardening tests for Soma MCP server.

Tests path confinement, rule-name validation and rate limiting. (The v3 HMAC rule
manifest is gone: D3. Rules are protected by git review and CI; aegis sync keeps an
unsigned index that only reports edits, tested in test_sync.py.)
"""
import os
import sys
import time

import pytest

REPO_ROOT = str(next(p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").exists()))
sys.path.insert(0, REPO_ROOT)

from aegis_core.workspace import confine_path, validate_rule_names
from aegis_core.workspace.base import Workspace


# ── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture
def soma_workspace(tmp_path):
    """Create a minimal valid Soma workspace."""
    cells_dir = tmp_path / ".aegis" / "rules" / "invariants"
    cells_dir.mkdir(parents=True)
    (cells_dir / "wall-test.md").write_text(
        "---\ntype: invariant\nenforcement: gate\nhypothesis: test\n---\nTest cell.\n"
    )
    evidence_dir = tmp_path / ".aegis" / "evidence"
    evidence_dir.mkdir(parents=True)
    return tmp_path


# ── Path Confinement: Workspace.confine ───────────────────────────────


class TestConfineWorkspace:
    def test_rejects_empty(self):
        """Empty string is not a valid workspace."""
        with pytest.raises(ValueError, match="must not be empty"):
            str(Workspace.confine("").root)

    def test_rejects_nonexistent(self):
        """Nonexistent path is rejected."""
        with pytest.raises(ValueError, match="does not exist"):
            str(Workspace.confine("/nonexistent/path/abc123").root)

    def test_rejects_non_soma_dir(self, tmp_path):
        """A directory without .aegis/rules/ is not a valid workspace."""
        with pytest.raises(ValueError, match="not a valid Aegis workspace"):
            str(Workspace.confine(str(tmp_path)).root)

    def test_accepts_valid_workspace(self, soma_workspace):
        """A directory with .aegis/rules/ is accepted."""
        result = str(Workspace.confine(str(soma_workspace)).root)
        assert os.path.isabs(result)
        assert os.path.isdir(os.path.join(result, ".aegis", "rules"))


# ── Path Confinement: confine_path ────────────────────────────────────


class TestConfinePath:
    def test_rejects_empty(self):
        """Empty file path is rejected."""
        with pytest.raises(ValueError, match="must not be empty"):
            confine_path("", "/any")

    def test_rejects_traversal(self, soma_workspace):
        """Path traversal with ../ is blocked."""
        with pytest.raises(ValueError, match="path traversal blocked"):
            confine_path("../../etc/passwd", str(soma_workspace))

    def test_rejects_absolute_escape(self, soma_workspace):
        """Absolute path outside workspace is blocked."""
        with pytest.raises(ValueError, match="path traversal blocked"):
            confine_path("/etc/passwd", str(soma_workspace))

    def test_rejects_workspace_root(self, soma_workspace):
        """Pointing at the workspace root itself is rejected."""
        with pytest.raises(ValueError, match="refusing to treat the workspace root"):
            confine_path(".", str(soma_workspace))

    @pytest.mark.skipif(
        not hasattr(os, "symlink"), reason="Symlinks not supported"
    )
    def test_rejects_symlink_escape(self, soma_workspace):
        """Symlink that resolves outside workspace is blocked."""
        outside = soma_workspace.parent / "outside_target"
        outside.mkdir()
        link = soma_workspace / "sneaky_link"
        try:
            os.symlink(str(outside), str(link))
        except OSError:
            pytest.skip("Cannot create symlink")
        with pytest.raises(ValueError, match="path traversal blocked"):
            confine_path("sneaky_link/secret.txt", str(soma_workspace))

    def test_accepts_valid_relative(self, soma_workspace):
        """Valid relative path inside workspace is accepted."""
        resolved, relative = confine_path("src/main.py", str(soma_workspace))
        assert relative == os.path.join("src", "main.py")
        assert resolved.endswith(os.path.join("src", "main.py"))

    def test_accepts_nested_path(self, soma_workspace):
        """Deeply nested relative path is accepted."""
        resolved, relative = confine_path("a/b/c/file.py", str(soma_workspace))
        assert relative == os.path.join("a", "b", "c", "file.py")

    def test_rejects_null_bytes(self, soma_workspace):
        with pytest.raises(ValueError, match="null bytes"):
            confine_path("src/file\x00.py", str(soma_workspace))

    @pytest.mark.parametrize(
        "dev_name",
        [
            "CON", "PRN", "AUX", "NUL", "COM1", "LPT9",
            "CON.txt", "sub/NUL.json", "aux.md", "com3.py",
            "CON.", "NUL ", "AUX.tar.gz",
        ],
    )
    def test_rejects_windows_device_names(self, soma_workspace, dev_name):
        with pytest.raises(ValueError, match="reserved Windows device name"):
            confine_path(dev_name, str(soma_workspace))

    def test_rejects_alternate_data_streams(self, soma_workspace):
        with pytest.raises(ValueError, match="alternate data stream"):
            confine_path("file.txt:stream", str(soma_workspace))

    def test_rejects_extended_device_namespaces(self, soma_workspace):
        with pytest.raises(ValueError, match="device namespace"):
            confine_path(r"\\?\C:\secret.txt", str(soma_workspace))

    @pytest.mark.parametrize(
        "safe_name",
        ["connect.py", "pronto.md", "components.py", "concurrent.py", "auxiliary.py", "nullify.py"],
    )
    def test_accepts_benign_names_with_device_substrings(self, soma_workspace, safe_name):
        resolved, relative = confine_path(safe_name, str(soma_workspace))
        assert relative == safe_name



# ── Cell Name Validation ──────────────────────────────────────────────


class TestValidateCellNames:
    def test_empty_list_returns_empty(self, soma_workspace):
        """Empty cell list always validates."""
        assert validate_rule_names([], str(soma_workspace)) == []

    def test_all_valid_returns_empty(self, soma_workspace):
        """Known cell names return no invalid entries."""
        result = validate_rule_names(["wall-test"], str(soma_workspace))
        assert result == []

    def test_unknown_names_returned(self, soma_workspace):
        """Unknown cell names are returned as invalid."""
        result = validate_rule_names(
            ["wall-test", "nonexistent-cell", "another-fake"],
            str(soma_workspace),
        )
        assert "nonexistent-cell" in result
        assert "another-fake" in result
        assert "wall-test" not in result

    def test_no_cells_dir_all_invalid(self, tmp_path):
        """When .aegis/rules/ doesn't exist, all names are invalid."""
        result = validate_rule_names(["any-name"], str(tmp_path))
        assert result == ["any-name"]


# ── Rate Limiting ─────────────────────────────────────────────────────


class TestRateLimiting:
    def setup_method(self):
        """Reset rate limiter state between tests."""
        from aegis_mcp import server

        server._tool_call_times.clear()

    def test_allows_within_limit(self):
        """Calls within the window limit are allowed."""
        from aegis_mcp.server import _RATE_LIMITS, _check_rate_limit

        limit = _RATE_LIMITS["aegis_report_outcome"][0]
        for _ in range(limit):
            assert _check_rate_limit("aegis_report_outcome") is True

    def test_blocks_over_limit(self):
        """Calls exceeding the window limit are blocked."""
        from aegis_mcp.server import _RATE_LIMITS, _check_rate_limit

        for _ in range(_RATE_LIMITS["aegis_report_outcome"][0]):
            _check_rate_limit("aegis_report_outcome")
        assert _check_rate_limit("aegis_report_outcome") is False

    def test_window_expires(self, monkeypatch):
        """Old entries are pruned when the window expires."""
        from aegis_mcp import server

        mock_time = [100.0]
        monkeypatch.setattr(time, "monotonic", lambda: mock_time[0])

        max_calls, window = server._RATE_LIMITS["aegis_report_outcome"]
        for _ in range(max_calls):
            server._check_rate_limit("aegis_report_outcome")
        assert server._check_rate_limit("aegis_report_outcome") is False

        # Advance past the window
        mock_time[0] = 100.0 + window + 1
        assert server._check_rate_limit("aegis_report_outcome") is True

    def test_unlimited_tools_always_pass(self):
        """Tools not in _RATE_LIMITS are never rate-limited."""
        from aegis_mcp.server import _check_rate_limit

        for _ in range(100):
            assert _check_rate_limit("aegis_scan") is True

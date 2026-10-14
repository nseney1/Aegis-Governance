from pathlib import Path
"""Security hardening tests for Soma MCP server.

Tests path confinement, enzyme import allowlisting, cell integrity
manifests, outcome validation, session token auth, and rate limiting.
"""
import os
import sys
import time

import pytest

REPO_ROOT = str(next(p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").exists()))
sys.path.insert(0, REPO_ROOT)

from aegis_mcp.security import confine_workspace, confine_path, validate_rule_names
from aegis_core.integrity import (
    generate_manifest,
    verify_manifest,
    load_manifest,
    save_manifest,
)


# ── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture
def soma_workspace(tmp_path):
    """Create a minimal valid Soma workspace."""
    cells_dir = tmp_path / ".aegis" / "rules" / "walls"
    cells_dir.mkdir(parents=True)
    (cells_dir / "wall-test.md").write_text(
        "---\ntype: wall\nhypothesis: test\n---\nTest cell.\n"
    )
    evidence_dir = tmp_path / ".aegis" / "evidence"
    evidence_dir.mkdir(parents=True)
    return tmp_path


# ── Path Confinement: confine_workspace ───────────────────────────────


class TestConfineWorkspace:
    def test_rejects_empty(self):
        """Empty string is not a valid workspace."""
        with pytest.raises(ValueError, match="must not be empty"):
            confine_workspace("")

    def test_rejects_nonexistent(self):
        """Nonexistent path is rejected."""
        with pytest.raises(ValueError, match="does not exist"):
            confine_workspace("/nonexistent/path/abc123")

    def test_rejects_non_soma_dir(self, tmp_path):
        """A directory without .aegis/rules/ is not a valid workspace."""
        with pytest.raises(ValueError, match="not a valid Aegis workspace"):
            confine_workspace(str(tmp_path))

    def test_accepts_valid_workspace(self, soma_workspace):
        """A directory with .aegis/rules/ is accepted."""
        result = confine_workspace(str(soma_workspace))
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


# ── Integrity Manifest ────────────────────────────────────────────────


class TestIntegrityManifest:
    def test_generate_manifest(self, soma_workspace):
        """Manifest includes all cell files with SHA-256 hashes."""
        cells_dir = str(soma_workspace / ".aegis" / "rules")
        manifest = generate_manifest(cells_dir)
        assert manifest["cell_count"] > 0
        for path, hash_val in manifest["cells"].items():
            assert hash_val.startswith("sha256:")
            assert len(hash_val) == len("sha256:") + 64  # hex digest length

    def test_verify_unmodified(self, soma_workspace):
        """Clean cells produce no verification issues."""
        cells_dir = str(soma_workspace / ".aegis" / "rules")
        manifest = generate_manifest(cells_dir)
        issues = verify_manifest(cells_dir, manifest)
        assert issues == []

    def test_verify_detects_modified(self, soma_workspace):
        """Modified cell content is detected as a hash mismatch."""
        cells_dir = str(soma_workspace / ".aegis" / "rules")
        manifest = generate_manifest(cells_dir)
        # Tamper with the cell
        cell_path = soma_workspace / ".aegis" / "rules" / "walls" / "wall-test.md"
        cell_path.write_text("---\ntype: wall\nhypothesis: TAMPERED\n---\nEvil.\n")
        issues = verify_manifest(cells_dir, manifest)
        types = [i["type"] for i in issues]
        assert "modified" in types

    def test_verify_detects_added(self, soma_workspace):
        """New cell not in manifest is detected as unknown."""
        cells_dir = str(soma_workspace / ".aegis" / "rules")
        manifest = generate_manifest(cells_dir)
        # Add a rogue cell
        rogue = soma_workspace / ".aegis" / "rules" / "walls" / "wall-rogue.md"
        rogue.write_text("---\ntype: wall\nhypothesis: rogue\n---\nRogue.\n")
        issues = verify_manifest(cells_dir, manifest)
        types = [i["type"] for i in issues]
        assert "added" in types

    def test_verify_detects_removed(self, soma_workspace):
        """Cell in manifest but missing from disk is detected."""
        cells_dir = str(soma_workspace / ".aegis" / "rules")
        manifest = generate_manifest(cells_dir)
        # Delete the cell
        cell_path = soma_workspace / ".aegis" / "rules" / "walls" / "wall-test.md"
        cell_path.unlink()
        issues = verify_manifest(cells_dir, manifest)
        types = [i["type"] for i in issues]
        assert "removed" in types

    def test_load_manifest_returns_none_when_missing(self, tmp_path):
        """Missing manifest file returns None, not an error."""
        assert load_manifest(str(tmp_path)) is None

    def test_save_and_load_roundtrip(self, soma_workspace):
        """Manifest can be saved and loaded back identically."""
        cells_dir = str(soma_workspace / ".aegis" / "rules")
        original = generate_manifest(cells_dir)
        save_manifest(str(soma_workspace), original)
        loaded = load_manifest(str(soma_workspace))
        assert loaded is not None
        assert loaded["cells"] == original["cells"]
        assert loaded["cell_count"] == original["cell_count"]


# ── HMAC Key Management & Signing ─────────────────────────────────────


class TestKeyManagement:
    def test_generate_key_creates_file(self, soma_workspace):
        """Key generation creates .aegis/keys/manifest.key."""
        from aegis_core.integrity import generate_key

        key_path = generate_key(str(soma_workspace))
        assert os.path.isfile(key_path)
        # Key should be 32 bytes (256-bit) stored as hex
        with open(key_path, "r") as f:
            key_hex = f.read().strip()
        assert len(key_hex) == 64  # 32 bytes * 2 hex chars

    def test_generate_key_rejects_overwrite(self, soma_workspace):
        """Second key generation raises FileExistsError."""
        from aegis_core.integrity import generate_key

        generate_key(str(soma_workspace))
        with pytest.raises(FileExistsError):
            generate_key(str(soma_workspace))

    def test_rotate_key_backs_up_old(self, soma_workspace):
        """Key rotation creates .bak and new key differs."""
        from aegis_core.integrity import generate_key, rotate_key, load_key

        generate_key(str(soma_workspace))
        old_key = load_key(str(soma_workspace))
        rotate_key(str(soma_workspace))
        new_key = load_key(str(soma_workspace))
        assert old_key != new_key
        # Backup should exist
        bak_path = os.path.join(
            str(soma_workspace), ".aegis", "keys", "manifest.key.bak"
        )
        assert os.path.isfile(bak_path)

    def test_load_key_returns_none_when_missing(self, soma_workspace):
        """No key file returns None, not an error."""
        from aegis_core.integrity import load_key

        assert load_key(str(soma_workspace)) is None


class TestManifestSigning:
    def test_sign_manifest_deterministic(self, soma_workspace):
        """Same manifest + same key = same signature."""
        from aegis_core.integrity import generate_key, load_key, sign_manifest

        generate_key(str(soma_workspace))
        key = load_key(str(soma_workspace))
        cells_dir = str(soma_workspace / ".aegis" / "rules")
        manifest = generate_manifest(cells_dir)
        sig1 = sign_manifest(manifest, key)
        sig2 = sign_manifest(manifest, key)
        assert sig1 == sig2

    def test_sign_manifest_different_key(self, soma_workspace):
        """Different key = different signature."""
        from aegis_core.integrity import sign_manifest

        cells_dir = str(soma_workspace / ".aegis" / "rules")
        manifest = generate_manifest(cells_dir)
        key_a = b"key_a_secret_value_for_testing_1"
        key_b = b"key_b_secret_value_for_testing_2"
        sig_a = sign_manifest(manifest, key_a)
        sig_b = sign_manifest(manifest, key_b)
        assert sig_a != sig_b

    def test_verify_signature_valid(self, soma_workspace):
        """Valid signature verifies True."""
        from aegis_core.integrity import (
            generate_key, load_key, sign_manifest, verify_signature,
        )

        generate_key(str(soma_workspace))
        key = load_key(str(soma_workspace))
        cells_dir = str(soma_workspace / ".aegis" / "rules")
        manifest = generate_manifest(cells_dir)
        manifest["signature"] = sign_manifest(manifest, key)
        assert verify_signature(manifest, key) is True

    def test_verify_signature_tampered(self, soma_workspace):
        """Tampered manifest fails verification."""
        from aegis_core.integrity import (
            generate_key, load_key, sign_manifest, verify_signature,
        )

        generate_key(str(soma_workspace))
        key = load_key(str(soma_workspace))
        cells_dir = str(soma_workspace / ".aegis" / "rules")
        manifest = generate_manifest(cells_dir)
        manifest["signature"] = sign_manifest(manifest, key)
        # Tamper with cells
        manifest["cells"]["walls/rogue.md"] = "sha256:badhash"
        assert verify_signature(manifest, key) is False

    def test_verify_signature_non_string_rejected(self, soma_workspace):
        """Non-string signature fails verification safely."""
        from aegis_core.integrity import (
            generate_key, load_key, sign_manifest, verify_signature,
        )

        generate_key(str(soma_workspace))
        key = load_key(str(soma_workspace))
        cells_dir = str(soma_workspace / ".aegis" / "rules")
        manifest = generate_manifest(cells_dir)
        manifest["signature"] = 12345
        assert verify_signature(manifest, key) is False
        manifest["signature"] = ["not", "a", "string"]
        assert verify_signature(manifest, key) is False


    def test_save_manifest_auto_signs(self, soma_workspace):
        """save_manifest includes signature when key exists."""
        from aegis_core.integrity import generate_key

        generate_key(str(soma_workspace))
        cells_dir = str(soma_workspace / ".aegis" / "rules")
        manifest = generate_manifest(cells_dir)
        save_manifest(str(soma_workspace), manifest)
        loaded = load_manifest(str(soma_workspace))
        assert "signature" in loaded

    def test_unsigned_manifest_graceful(self, soma_workspace):
        """Manifest without signature works when no key exists."""
        cells_dir = str(soma_workspace / ".aegis" / "rules")
        manifest = generate_manifest(cells_dir)
        save_manifest(str(soma_workspace), manifest)
        loaded = load_manifest(str(soma_workspace))
        assert loaded is not None
        assert "signature" not in loaded




# ── Session Auth ──────────────────────────────────────────────────────


class TestSessionAuth:
    def test_read_tools_defined(self):
        """Read-only tools are classified."""
        from aegis_mcp.server import _READ_TOOLS

        assert "aegis_scan" in _READ_TOOLS
        assert "aegis_list_rules" in _READ_TOOLS

    def test_write_and_execute_tools_defined(self):
        """Write and execute tools are classified."""
        from aegis_mcp.server import _WRITE_TOOLS, _EXECUTE_TOOLS

        assert "aegis_report_outcome" in _WRITE_TOOLS
        assert "aegis_propose_change" in _EXECUTE_TOOLS

    def test_all_tool_definitions_classified(self):
        """Every tool in TOOL_DEFINITIONS appears in exactly one tier."""
        from aegis_mcp.server import _READ_TOOLS, _WRITE_TOOLS, _EXECUTE_TOOLS
        from aegis_mcp.tools import TOOL_DEFINITIONS

        all_tiers = _READ_TOOLS | _WRITE_TOOLS | _EXECUTE_TOOLS
        for tool_def in TOOL_DEFINITIONS:
            name = tool_def["name"]
            assert name in all_tiers, (
                f"Tool '{name}' is not classified in any permission tier"
            )


# ── Rate Limiting ─────────────────────────────────────────────────────


class TestRateLimiting:
    def setup_method(self):
        """Reset rate limiter state between tests."""
        from aegis_mcp import server

        server._tool_call_times.clear()

    def test_allows_within_limit(self):
        """Calls within the window limit are allowed."""
        from aegis_mcp.server import _check_rate_limit

        # soma_checkpoint has a limit of 3 per 60s
        assert _check_rate_limit("aegis_checkpoint") is True
        assert _check_rate_limit("aegis_checkpoint") is True
        assert _check_rate_limit("aegis_checkpoint") is True

    def test_blocks_over_limit(self):
        """Calls exceeding the window limit are blocked."""
        from aegis_mcp.server import _check_rate_limit

        for _ in range(3):
            _check_rate_limit("aegis_checkpoint")
        assert _check_rate_limit("aegis_checkpoint") is False

    def test_window_expires(self, monkeypatch):
        """Old entries are pruned when the window expires."""
        from aegis_mcp import server

        mock_time = [100.0]
        monkeypatch.setattr(time, "monotonic", lambda: mock_time[0])

        for _ in range(3):
            server._check_rate_limit("aegis_checkpoint")
        assert server._check_rate_limit("aegis_checkpoint") is False

        # Advance past the 60s window
        mock_time[0] = 200.0
        assert server._check_rate_limit("aegis_checkpoint") is True

    def test_unlimited_tools_always_pass(self):
        """Tools not in _RATE_LIMITS are never rate-limited."""
        from aegis_mcp.server import _check_rate_limit

        for _ in range(100):
            assert _check_rate_limit("aegis_scan") is True

"""Enforcement & Engine Script Hardening Tests (Phase 3).

Verifies cell_enforce.py generated bash hooks under set -u with empty patterns,
correct cell_signal.sh path, and soma_py CWD isolation.
"""
import os
import subprocess
import pytest
import sys
from pathlib import Path

from conftest import REPO_ROOT, require_bash, run

from aegis_core.enforcement import generate_precommit_check


def test_cell_enforce_empty_target_patterns_bash_syntax(tmp_path):
    """Generated bash hook with empty target_patterns must execute without set -u unbound variable error."""
    bash = require_bash()
    cell = {
        "_name": "test_empty_patterns",
        "type": "wall",
        "hypothesis": "Test hypothesis",
        "target_paths": []
    }
    hook_code = generate_precommit_check(cell, ".")
    assert "append_signal" in hook_code, "Hook code should use append_signal"

    # Write hook code to temp script inside tmp_path and execute under bash
    tmp_script = tmp_path / "test_hook.sh"
    tmp_script.write_text(hook_code, encoding="utf-8")
    proc = subprocess.run([bash, str(tmp_script)], capture_output=True, text=True)
    # Should exit 0 without any bash unbound variable error
    assert proc.returncode == 0
    assert "unbound variable" not in proc.stderr


def test_cell_enforce_handles_null_target_paths():
    """generate_precommit_check must handle target_paths=None without crashing."""
    from aegis_core.enforcement import generate_precommit_check
    cell = {
        "_name": "test-null-targets",
        "type": "wall",
        "hypothesis": "test",
        "target_paths": None,
    }
    check_code = generate_precommit_check(cell, "/tmp")
    assert "TARGET_PATTERNS=()" in check_code

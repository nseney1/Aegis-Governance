"""Tombstone regression tests for bugs in legacy shell/enzymes purged in v0.97.0.

These tests preserve BUG_REGISTRY traceability for historical defects whose
implementation was deleted in the v0.97.0 sunset phase, asserting that the
purged legacy scripts remain absent from the codebase.
"""
from __future__ import annotations

import os
from pathlib import Path
import pytest
from conftest import REPO_ROOT

ROOT = Path(REPO_ROOT)


def test_bug_010_home_isolation():
    """BUG-010: resolve_home isolation in legacy common.sh."""
    assert not (ROOT / "enzymes" / "common.sh").exists()


def test_bug_021_uninstall_confinement_dotdot():
    """BUG-021: uninstall.sh dotdot path traversal escape."""
    assert not (ROOT / "install" / "uninstall.sh").exists()


def test_bug_036_uninstall_msys_paths():
    """BUG-036: cygpath handling under Git Bash in uninstall.sh."""
    assert not (ROOT / "install" / "uninstall.sh").exists()


def test_bug_037_python_resolution():
    """BUG-037: python.exe fallback in soma_python.sh."""
    assert not (ROOT / "enzymes" / "soma_python.sh").exists()


def test_bug_038_enzyme_console_encoding():
    """BUG-038: Unicode stdout encoding in standalone enzyme scripts."""
    assert not (ROOT / "enzymes").exists()


def test_bug_042_immune_sweep_env():
    """BUG-042: AEGIS_DATA_DIR unbound variable in immune_sweep.sh."""
    assert not (ROOT / "enzymes" / "immune_sweep.sh").exists()


def test_bug_043_manifestless_uninstall():
    """BUG-043: manifestless uninstall confinement in uninstall.sh."""
    assert not (ROOT / "install" / "uninstall.sh").exists()


def test_bug_044_shell_isolation():
    """BUG-044: python -c current directory isolation in install.sh."""
    assert not (ROOT / "install" / "install.sh").exists()


def test_bug_045_settings_cleanup_symlink():
    """BUG-045: symlinked claude settings cleanup in uninstall.sh."""
    assert not (ROOT / "install" / "uninstall.sh").exists()


def test_bug_055_session_close_order():
    """BUG-055: session_close.sh execution order before outcome engine."""
    assert not (ROOT / "enzymes" / "session_close.sh").exists()


def test_bug_059_post_session_hook_heredoc():
    """BUG-059: unquoted heredoc interpolation in post_session_hook.sh."""
    assert not (ROOT / "enzymes" / "post_session_hook.sh").exists()


def test_bug_062_shell_upward_traversal():
    """BUG-062: upward directory traversal in cell_create.sh and cell_signal.sh."""
    assert not (ROOT / "enzymes" / "cell_create.sh").exists()


def test_bug_063_uninstall_sed_rules():
    """BUG-063: uninstall.sh sed rule deletion pattern."""
    assert not (ROOT / "install" / "uninstall.sh").exists()


def test_bug_019_epoch_migration_purged():
    """BUG-019: epoch migration purged in v0.103.0."""
    assert not (ROOT / "aegis_cli" / "migration.py").exists()


def test_bug_025_migration_lock_purged():
    """BUG-025: migration locks purged in v0.103.0."""
    assert not (ROOT / "aegis_cli" / "migration.py").exists()


def test_bug_014_powershell_installer_purged():
    """BUG-014: Legacy powershell installer purged in v0.97.0."""
    assert not (ROOT / "install" / "install.ps1").exists()


def test_bug_029_mcp_generators_purged():
    """BUG-029: Legacy shell mcp generators purged in v0.97.0."""
    assert not (ROOT / "install" / "install.sh").exists()


def test_bug_031_manifestless_uninstall_purged():
    """BUG-031: Legacy manifestless uninstall purged in v0.97.0."""
    assert not (ROOT / "install" / "uninstall.sh").exists()


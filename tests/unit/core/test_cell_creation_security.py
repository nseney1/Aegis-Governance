"""Tests for Maelstrom Round 2 hardening & security audit findings."""
import json
import os
import sys
from pathlib import Path
import pytest

from conftest import run, require_bash, symlink_or_skip

REPO_ROOT = next(p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").exists())

# Ensure REPO_ROOT is in sys.path
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def test_load_cell_uses_created_field(tmp_path):
    """load_cell must read 'created' field from cell frontmatter."""
    from aegis_sdk.cells import load_cell
    cell_file = tmp_path / ".aegis" / "rules" / "vacuoles" / "created-test.md"
    cell_file.parent.mkdir(parents=True, exist_ok=True)
    cell_file.write_text("""---
id: created-test
type: vacuole
hypothesis: test
created: "2025-01-01T00:00:00Z"
---
body
""", encoding="utf-8")
    cell = load_cell("created-test", cells_dir=str(tmp_path / ".aegis" / "rules"))
    assert cell.created_date == "2025-01-01T00:00:00Z" or getattr(cell.created_date, "year", None) == 2025

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

def test_pathcheck_on_path_handles_windows_colons():
    """on_path with sep=';' should not corrupt Windows drive paths containing colons."""
    from aegis_cli.pathcheck import on_path
    path_env = r"C:\Python312\Scripts;C:\Windows\System32"
    assert on_path(r"C:\Python312\Scripts", path_env, sep=";", casefold=True)

def test_publish_workflow_isolates_release_assets():
    """publish.yml must isolate github release asset uploads to a separate job."""
    workflow = (REPO_ROOT / ".github" / "workflows" / "publish.yml").read_text(encoding="utf-8")
    assert "release-assets:" in workflow
    assert "RELEASE_TAG:" in workflow
    assert "|| true" not in workflow

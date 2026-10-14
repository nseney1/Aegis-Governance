"""End-to-end integration tests for ambient health evolution in Soma Oracle (Phase 13: v0.110.0).

Verifies the resolution of the reviewer critique:
- Cold-start: soma oracle reports 100% unobserved.
- Ambient verification (soma verify / soma_verify_changes) automatically creates
  fitness evidence without explicit soma_report_outcome calls.
- Subsequent soma oracle run shows cells transitioned to healthy / active.
- soma harvest --git bootstraps baseline from git history.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess

import pytest

from soma_core.somayaml import dump_frontmatter


def _init_git_repo(ws: Path) -> None:
    subprocess.run(["git", "init"], cwd=ws, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=ws, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=ws, check=True, capture_output=True)


def _commit_file(ws: Path, filename: str, content: str, msg: str) -> None:
    file_path = ws / filename
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(content, encoding="utf-8")
    subprocess.run(["git", "add", filename], cwd=ws, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", msg], cwd=ws, check=True, capture_output=True)


def _create_cell(ws: Path, cell_id: str, target_paths: list[str]) -> Path:
    cells_dir = ws / ".soma" / "cells" / "vacuoles"
    cells_dir.mkdir(parents=True, exist_ok=True)
    cell_path = cells_dir / f"{cell_id}.md"
    fm = {
        "id": cell_id,
        "type": "vacuole",
        "enforcement": "advisory",
        "target_paths": target_paths,
        "hypothesis": f"Hypothesis for {cell_id}",
    }
    cell_path.write_text(dump_frontmatter(fm, body=f"# {cell_id}\n"), encoding="utf-8")
    return cell_path


@pytest.fixture
def clean_project(tmp_path: Path) -> Path:
    ws = tmp_path / "project"
    ws.mkdir()
    _init_git_repo(ws)
    (ws / ".soma" / "evidence").mkdir(parents=True)
    return ws


def test_oracle_transitions_from_unobserved_after_ambient_verification(clean_project: Path):
    """Running soma verify on changed files must transition matched cells from unobserved to healthy in soma oracle."""
    from soma_core.arbitration import generate_checkpoint
    from soma_cli.verify import run_verify

    # Setup 2 cells
    _create_cell(clean_project, "cell-math", ["math/*.py"])
    _create_cell(clean_project, "cell-crypto", ["crypto/*.py"])

    # 1. Before verification: 100% unobserved
    report1 = generate_checkpoint(str(clean_project))
    assert report1["total_cells"] == 2
    assert len(report1["classifications"].get("unobserved", [])) == 2

    # 2. Touch and verify math/calc.py
    math_file = clean_project / "math" / "calc.py"
    math_file.parent.mkdir(parents=True, exist_ok=True)
    math_file.write_text('__all__ = ["add"]\n\ndef add(a, b): return a + b\n', encoding="utf-8")

    args = argparse.Namespace(
        files=["math/calc.py"],
        layer1_only=True,
        dry_run=False,
        repo_root=str(clean_project),
        workspace=str(clean_project),
        plan=None,
        plan_file=None,
        provider=None,
    )
    rc = run_verify(args)
    assert rc == 0

    # 3. After ambient verification: cell-math is now healthy!
    report2 = generate_checkpoint(str(clean_project))
    assert report2["total_cells"] == 2
    unobserved_ids = [c["cell_id"] for c in report2["classifications"].get("unobserved", [])]
    healthy_ids = [c["cell_id"] for c in report2["classifications"].get("healthy", [])]

    assert "cell-math" in healthy_ids
    assert "cell-math" not in unobserved_ids
    assert "cell-crypto" in unobserved_ids
    assert report2["healthy_count"] >= 1


def test_oracle_transitions_from_unobserved_after_git_harvest(clean_project: Path):
    """Running soma harvest --git must transition historical cells out of unobserved."""
    from soma_core.arbitration import generate_checkpoint
    from aegis_core.outcomes import harvest_git_history

    _create_cell(clean_project, "cell-service", ["service/*.py"])
    _commit_file(clean_project, "service/user.py", "class User: pass\n", "feat: add user service")

    # 1. Cold start
    report1 = generate_checkpoint(str(clean_project))
    assert "cell-service" in [c["cell_id"] for c in report1["classifications"].get("unobserved", [])]

    # 2. Harvest git history
    res = harvest_git_history(clean_project, limit=10, dry_run=False)
    assert res.get("commits_inspected", 0) >= 1

    # 3. Post-harvest
    report2 = generate_checkpoint(str(clean_project))
    healthy_ids = [c["cell_id"] for c in report2["classifications"].get("healthy", [])]
    assert "cell-service" in healthy_ids

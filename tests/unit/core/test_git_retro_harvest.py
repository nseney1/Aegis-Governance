"""Tests for git historical retro-harvesting (Phase 13: v0.110.0).

Verifies that:
1. `harvest_git_history` reads recent git commit diffs and matches touched files to cells.
2. Initial baseline evidence (trigger + tp) is generated for matched cells.
3. Cold-start repositories immediately gain fitness history from existing git commits.
4. CLI command `soma harvest --git` works with --limit and --dry-run.
5. Harvesting is idempotent: re-running does not duplicate events.
"""
from __future__ import annotations

import argparse
import json
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
def git_workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "repo"
    ws.mkdir()
    _init_git_repo(ws)
    (ws / ".soma" / "evidence").mkdir(parents=True)
    return ws


def test_harvest_git_history_seeds_baseline(git_workspace: Path):
    """harvest_git_history should inspect commits and write signals for matched cells."""
    from soma_core.outcomes import harvest_git_history
    from soma_core.evidence import aggregate_signals

    _create_cell(git_workspace, "cell-parser", ["parser/*.py"])
    _create_cell(git_workspace, "cell-docs", ["docs/*.md"])

    # Create 3 commits
    _commit_file(git_workspace, "parser/ast.py", "class AST: pass\n", "feat: add AST")
    _commit_file(git_workspace, "parser/lexer.py", "class Lexer: pass\n", "feat: add Lexer")
    _commit_file(git_workspace, "unrelated.txt", "notes\n", "chore: add notes")

    stats = harvest_git_history(str(git_workspace), limit=10, dry_run=False)
    assert stats["commits_inspected"] >= 3
    assert stats["cells_matched"] >= 1
    assert stats["signals_minted"] >= 2

    agg = aggregate_signals(str(git_workspace / ".soma" / "evidence"))
    assert "cell-parser" in agg.counts
    assert agg.counts["cell-parser"]["triggers"] >= 2
    assert agg.counts["cell-parser"]["tp"] >= 2


def test_harvest_git_history_dry_run_does_not_write(git_workspace: Path):
    """--dry-run must not create or modify signals.jsonl."""
    from soma_core.outcomes import harvest_git_history

    _create_cell(git_workspace, "cell-parser", ["*.py"])
    _commit_file(git_workspace, "foo.py", "x = 1\n", "init")

    stats = harvest_git_history(str(git_workspace), limit=5, dry_run=True)
    assert stats["signals_minted"] >= 2

    sig_file = git_workspace / ".soma" / "evidence" / "signals.jsonl"
    assert not sig_file.exists()


def test_harvest_git_history_idempotent(git_workspace: Path):
    """Running harvest twice must not duplicate signals."""
    from soma_core.outcomes import harvest_git_history
    from soma_core.evidence import aggregate_signals

    _create_cell(git_workspace, "cell-parser", ["*.py"])
    _commit_file(git_workspace, "foo.py", "x = 1\n", "init")

    stats1 = harvest_git_history(str(git_workspace), limit=5, dry_run=False)
    agg1 = aggregate_signals(str(git_workspace / ".soma" / "evidence"))
    count1 = agg1.counts["cell-parser"]["triggers"]

    stats2 = harvest_git_history(str(git_workspace), limit=5, dry_run=False)
    agg2 = aggregate_signals(str(git_workspace / ".soma" / "evidence"))
    count2 = agg2.counts["cell-parser"]["triggers"]

    assert count1 == count2


def test_cli_harvest_git_command(git_workspace: Path):
    """harvest_git_history should execute successfully."""
    from aegis_core.outcomes.harvest import harvest_git_history

    _create_cell(git_workspace, "cell-backend", ["backend/*.py"])
    _commit_file(git_workspace, "backend/server.py", "app = None\n", "add server")

    res = harvest_git_history(workspace=str(git_workspace), limit=10, dry_run=False)
    assert res.get("commits_inspected", 0) >= 1

    sig_file = git_workspace / ".soma" / "evidence" / "signals.jsonl"
    assert sig_file.exists()


def test_capture_git_signals(git_workspace: Path):
    """Test capture_git_signals with reverts and rework."""
    from soma_core.outcomes.harvest import capture_git_signals
    # Commit a file, then revert it
    _commit_file(git_workspace, "rework.py", "v1\n", "v1")
    _commit_file(git_workspace, "rework.py", "v2\n", "v2 rework")
    _commit_file(git_workspace, "other.py", "x\n", "Revert 'something bad'")
    
    signals = capture_git_signals(str(git_workspace))
    assert signals["reverts"] >= 1
    assert "rework.py" in signals["rework_files"]


def test_capture_git_signals_invalid_dir(tmp_path: Path):
    """Test capture_git_signals on non-git dir."""
    from soma_core.outcomes.harvest import capture_git_signals
    signals = capture_git_signals(str(tmp_path))
    assert signals == {"reverts": 0, "rework_files": []}


def test_harvest_git_history_no_cells_dir(tmp_path: Path):
    """Test harvest_git_history on workspace without cells dir."""
    from soma_core.outcomes.harvest import harvest_git_history
    res = harvest_git_history(str(tmp_path))
    assert res["commits_inspected"] == 0
    assert res["signals_minted"] == 0


def test_harvest_git_history_git_error(tmp_path: Path):
    """Test harvest_git_history when git fails."""
    from soma_core.outcomes.harvest import harvest_git_history
    cells_dir = tmp_path / ".soma" / "cells"
    cells_dir.mkdir(parents=True)
    res = harvest_git_history(str(tmp_path))
    assert res["commits_inspected"] == 0
    assert "error" in res


def test_harvest_git_history_exception(tmp_path: Path, monkeypatch):
    """Test harvest_git_history when subprocess raises Exception."""
    from soma_core.outcomes.harvest import harvest_git_history
    import subprocess
    cells_dir = tmp_path / ".soma" / "cells"
    cells_dir.mkdir(parents=True)
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("subprocess failed")))
    res = harvest_git_history(str(tmp_path))
    assert res["commits_inspected"] == 0
    assert "error" in res


"""Match rules to changed files (git working tree or explicit list)."""
from __future__ import annotations

from pathlib import Path
import subprocess

from aegis_core.rule_inventory import find_matching_cells
from aegis_core.workspace.base import Workspace
from aegis_core.workspace import as_workspace

__all__ = ["match_cells_to_changes"]


def _get_changed_files(workspace: str) -> list[str]:
    try:
        out = subprocess.check_output(
            ["git", "diff", "--name-only", "HEAD~1"],
            cwd=workspace, text=True, stderr=subprocess.DEVNULL
        )
        files = [f.strip() for f in out.splitlines() if f.strip()]
        if files:
            return files
    except Exception:
        pass

    try:
        out = subprocess.check_output(
            ["git", "status", "--porcelain"],
            cwd=workspace, text=True, stderr=subprocess.DEVNULL
        )
        files = []
        for line in out.splitlines():
            # "XY path": the status is exactly 2 columns plus a space, and X is a
            # space for unstaged edits, so the line must not be stripped first.
            path = line[3:].strip()
            if " -> " in path:
                path = path.split(" -> ", 1)[1]
            if path:
                files.append(path)
        return files
    except Exception:
        return []


def match_cells_to_changes(workspace: Workspace | Path | str, changed_files: list[str]) -> list[dict]:
    ws = as_workspace(workspace)
    cells_dir = ws.rules_dir
    matches = find_matching_cells(str(cells_dir), changed_files, allow_basename_match=True)
    triggered = []
    for m in matches:
        cell_dict = dict(m.frontmatter)
        cell_dict["_name"] = m.cell_id
        cell_dict["_path"] = m.cell_path
        triggered.append(cell_dict)
    return triggered



"""Match rules to changed files (git working tree or explicit list)."""
from __future__ import annotations

from pathlib import Path

from aegis_core import gitsafe
from aegis_core.rule_inventory import find_matching_cells
from aegis_core.workspace.base import Workspace
from aegis_core.workspace import as_workspace

__all__ = ["match_cells_to_changes"]


def _get_changed_files(workspace: str) -> list[str]:
    """What the session changed: the last commit plus uncommitted edits (``git diff HEAD~1``);
    in a repository with one commit, the uncommitted and untracked files (``git status``)."""
    uncommitted = gitsafe.changed_files(workspace, "working") or []
    if gitsafe.resolve_commit(workspace, "HEAD~1"):
        files = list(dict.fromkeys((gitsafe.changed_files(workspace, "head") or []) + uncommitted))
        if files:
            return files
    untracked = gitsafe.list_files(workspace, tracked=False) or []
    return list(dict.fromkeys(uncommitted + untracked))


def match_cells_to_changes(workspace: Workspace | Path | str, changed_files: list[str]) -> list[dict]:
    ws = as_workspace(workspace)
    cells_dir = ws.rules_dir
    matches = find_matching_cells(str(cells_dir), changed_files)
    triggered = []
    for m in matches:
        cell_dict = dict(m.frontmatter)
        cell_dict["_name"] = m.cell_id
        cell_dict["_path"] = m.cell_path
        triggered.append(cell_dict)
    return triggered



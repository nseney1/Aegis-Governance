"""Match rules to changed files (git working tree or explicit list)."""
from __future__ import annotations

from pathlib import Path

from aegis_core import gitsafe
from aegis_core.match import matching_files
from aegis_core.rules import load_rules
from aegis_core.workspace.base import Workspace
from aegis_core.workspace import literal_workspace

__all__ = ["match_rules_to_changes"]


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


def _relative(root: Path, path: str) -> str:
    """Rule patterns are workspace-relative: an absolute path inside the workspace is made so."""
    candidate = Path(path)
    if candidate.is_absolute():
        try:
            return candidate.resolve().relative_to(Path(root).resolve()).as_posix()
        except (ValueError, OSError):
            return path
    return path


def match_rules_to_changes(workspace: Workspace | Path | str, changed_files: list[str]) -> list[dict]:
    """The served rules whose target_paths match ``changed_files``, as ``Rule.as_dict()``
    plus ``_matched_files``. One loader, one matcher (aegis_core.rules, aegis_core.match)."""
    ws = literal_workspace(workspace)
    files = [_relative(ws.root, f) for f in changed_files if f]
    out = []
    for rule in load_rules(ws).served:
        matched = matching_files(rule.target_paths, files)
        if matched:
            data = rule.as_dict()
            data["_matched_files"] = matched
            out.append(data)
    return out

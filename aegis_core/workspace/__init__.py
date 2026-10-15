"""Workspace resolution helpers over the Workspace value object (aegis_core.workspace.base).

Submodules own the rest: base (Workspace), git (GitWorkspace), discovery,
confinement, scaffold, hooks and layout. Import those names from there.
"""
from __future__ import annotations

import os
from pathlib import Path

from aegis_core.errors import PathTraversalError
from aegis_core.workspace.base import Workspace


def resolve_workspace(
    start: str | Path | os.PathLike[str] | Workspace | None = None,
    caller_file: str | Path | os.PathLike[str] | None = None,
    strict_env: bool = False,
) -> str:
    """Find the project root containing .aegis/rules/ or .aegis/."""
    return str(Workspace.resolve(start=start, caller_file=caller_file, strict_env=strict_env).root)


def resolve_workspace_path(
    start: str | Path | os.PathLike[str] | Workspace | None = None,
    caller_file: str | Path | os.PathLike[str] | None = None,
    strict_env: bool = False,
) -> Path:
    """Return workspace root as a resolved Path object."""
    return Workspace.resolve(start=start, caller_file=caller_file, strict_env=strict_env).root


def as_workspace(workspace: str | Path | os.PathLike[str] | Workspace | None = None) -> Workspace:
    """Coerce any workspace representation into a strongly-typed Workspace value object."""
    if isinstance(workspace, Workspace):
        return workspace
    if workspace:
        return Workspace.resolve(start=workspace)
    return Workspace.resolve()


def confine_workspace(untrusted_workspace: str | Path | os.PathLike[str] | Workspace) -> str:
    """Validate and confine a workspace path."""
    return str(Workspace.confine(untrusted_workspace).root)


def confine_path(
    untrusted_path: str | Path | os.PathLike[str],
    workspace: str | Path | os.PathLike[str] | Workspace,
) -> tuple[str, str]:
    """Resolve and confine a file path within a workspace."""
    if isinstance(workspace, Workspace):
        return workspace.confine_path(untrusted_path)
    p_str = str(untrusted_path) if untrusted_path is not None else ""
    if not p_str or not p_str.strip():
        raise PathTraversalError("file path must not be empty")
    return Workspace.resolve(start=workspace).confine_path(untrusted_path)


def validate_rule_names(
    rule_names: list[str],
    workspace: str | Path | os.PathLike[str] | Workspace,
) -> list[str]:
    """Validate that rule names reference rules that actually exist."""
    ws = workspace if isinstance(workspace, Workspace) else Workspace.resolve(start=workspace)
    return ws.validate_rule_names(rule_names)


__all__ = [
    "as_workspace",
    "confine_path",
    "confine_workspace",
    "resolve_workspace",
    "resolve_workspace_path",
    "validate_rule_names",
]

"""Shared workspace resolution and path containment for Soma (Layer 0 Core).

Modular package architecture providing:
- Workspace value object (base.py)
- GitWorkspace with zero-subprocess fast paths (git.py)
- Workspace discovery & compound fingerprinting (discovery.py)
- Path confinement and security boundaries (confinement.py)
- Scaffolding and initialization (scaffold.py)
- Git hook directory resolution (hooks.py)

Strictly zero-dependency: uses only Python standard library.
"""
from __future__ import annotations

import os
import warnings
from pathlib import Path

from aegis_core.errors import PathTraversalError
from aegis_core.workspace.base import Workspace
from aegis_core.workspace.confinement import (
    _WINDOWS_DEVICE_NAMES,
    confine_path_internal,
    validate_workspace_path,
)
from aegis_core.workspace.discovery import (
    _is_workspace_dir,
    is_soma_repo,
    resolve_workspace_root,
)
from aegis_core.workspace.git import GitWorkspace, _parse_worktree_porcelain
from aegis_core.workspace.hooks import _find_git_dirs, resolve_git_hooks_dir
from aegis_core.workspace.scaffold import scaffold_workspace


def resolve_workspace(
    start: str | Path | os.PathLike[str] | Workspace | None = None,
    caller_file: str | Path | os.PathLike[str] | None = None,
    strict_env: bool = False,
) -> str:
    """Find the project root containing .soma/cells/ or .soma/."""
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


def validate_cell_names(
    cell_names: list[str],
    workspace: str | Path | os.PathLike[str] | Workspace,
) -> list[str]:
    """Validate that cell names reference cells that actually exist."""
    ws = workspace if isinstance(workspace, Workspace) else Workspace.resolve(start=workspace)
    return ws.validate_cell_names(cell_names)


__all__ = [
    "GitWorkspace",
    "Workspace",
    "as_workspace",
    "confine_path",
    "confine_workspace",
    "is_soma_repo",
    "resolve_git_hooks_dir",
    "resolve_workspace",
    "resolve_workspace_path",
    "validate_cell_names",
    "_WINDOWS_DEVICE_NAMES",
    "_find_git_dirs",
    "_is_workspace_dir",
    "_parse_worktree_porcelain",
]

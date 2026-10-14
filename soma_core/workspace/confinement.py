"""Path confinement and security boundaries for Soma workspaces (Layer 0 Core).

Enforces cross-platform confinement, blocks directory traversal escapes, null bytes,
extended device namespace paths, alternate data streams, and Windows reserved device names.
Strictly zero-dependency: uses only Python standard library.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

from soma_core.errors import PathTraversalError, WorkspaceError, WorkspaceNotFoundError

_WINDOWS_DEVICE_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"}
    | {f"COM{i}" for i in range(1, 10)}
    | {f"LPT{i}" for i in range(1, 10)}
)


def confine_path_internal(
    workspace_root: Path,
    untrusted_path: str | Path | os.PathLike[str],
) -> tuple[str, str]:
    """Resolve and confine a file path within a workspace boundary.

    Returns (resolved_absolute, relative_to_workspace).
    Raises PathTraversalError if the path escapes the workspace boundary.
    """
    p_str = str(untrusted_path) if untrusted_path is not None else ""
    if not p_str or not p_str.strip():
        raise PathTraversalError("file path must not be empty")

    if "\x00" in p_str:
        raise PathTraversalError("null bytes are not permitted in file paths")

    if p_str.startswith(("\\\\?\\", "\\\\.\\", "//?/", "//./")):
        raise PathTraversalError("extended device namespace paths are not permitted")

    # Reject alternate data streams (e.g. file.txt:stream)
    if ":" in p_str:
        has_drive = re.match(r"^[a-zA-Z]:[\\/]", p_str)
        rest = p_str[2:] if has_drive else p_str
        if ":" in rest:
            raise PathTraversalError(f"alternate data stream syntax (':') is not permitted: {p_str!r}")

    # Reject reserved Windows device names
    for seg in re.split(r"[\\/]", p_str):
        if not seg:
            continue
        base = seg.rstrip(". ").split(".")[0].upper()
        if base in _WINDOWS_DEVICE_NAMES:
            raise PathTraversalError(f"reserved Windows device name not permitted: {p_str!r}")

    resolved_root = workspace_root.resolve()
    candidate = Path(os.path.join(str(resolved_root), p_str)).resolve()

    if candidate == resolved_root:
        raise PathTraversalError("refusing to treat the workspace root as a file")

    try:
        relative = candidate.relative_to(resolved_root)
    except ValueError:
        raise PathTraversalError(
            f"path traversal blocked: {p_str!r} resolves to {candidate} "
            f"which is outside the workspace {resolved_root}"
        )

    return str(candidate), str(relative)


def validate_workspace_path(
    untrusted_workspace: str | Path | os.PathLike[str],
) -> Path:
    """Validate that an untrusted workspace path exists and contains .soma/cells/.

    Returns the resolved Path object.
    Raises WorkspaceError / WorkspaceNotFoundError on invalid or malicious input.
    """
    if not untrusted_workspace or not str(untrusted_workspace).strip():
        raise WorkspaceError("workspace path must not be empty")

    resolved = os.path.realpath(str(untrusted_workspace))
    if not os.path.isdir(resolved):
        raise WorkspaceNotFoundError(f"workspace does not exist or is not a directory: {resolved}")

    aegis_rules = os.path.join(resolved, ".aegis", "rules")
    soma_cells = os.path.join(resolved, ".soma", "cells")
    soma_rules = os.path.join(resolved, ".soma", "rules")
    if not (os.path.isdir(aegis_rules) or os.path.isdir(soma_cells) or os.path.isdir(soma_rules)):
        raise WorkspaceError(f"not a valid Soma workspace (missing .soma/cells/ or .aegis/rules/): {resolved}")

    return Path(resolved)


__all__ = [
    "_WINDOWS_DEVICE_NAMES",
    "confine_path_internal",
    "validate_workspace_path",
]

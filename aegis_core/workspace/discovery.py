"""Workspace discovery and compound fingerprinting for Soma (Layer 0 Core).

Discovers project roots via the AEGIS_WORKSPACE pin, upward directory walks, and callers.
Provides compound fingerprinting (is_soma_repo) to distinguish Soma's own repository
from foreign repositories adopting Soma governance.
Strictly zero-dependency: uses only Python standard library.
"""
from __future__ import annotations

import os
from pathlib import Path

from aegis_core.config import env_workspace
from aegis_core.errors import WorkspaceError, WorkspaceNotFoundError
from aegis_core.workspace.binding import bounded_walk_up, denial
from aegis_core.workspace.layout import (
    AEGIS_DIRNAME,
    LEGACY_REPO_CONFS,
    LEGACY_SOMA_DIRNAME,
    LEGACY_UPGRADE_MARKERS,
    WorkspaceLayout,
    has_rules_dir,
    is_aegis_workspace,
)

LEGACY_SOMA_UPGRADE_MSG = (
    "Legacy .soma/ workspace detected at {path}. "
    "Aegis v3.0+ requires a .aegis/ workspace. "
    "Run 'aegis migrate' to see the conversion, then 'aegis migrate --apply'."
)


def _home_str() -> str:
    try:
        return str(Path.home())
    except Exception:
        return ""


UPGRADE_STATE_MSG = (
    "Unmigrated v3 state at {path}: {found}. Aegis v4 does not read it "
    "(the ledger, settings and keys stay unused). "
    "Run 'aegis migrate' to see the conversion, then 'aegis migrate --apply'."
)


def unconverted_rule_files(d: str | Path | os.PathLike[str]) -> list[Path]:
    """The rule files still in a v1/v2 rule directory of ``d`` (``.soma/cells/``,
    ``.soma/rules/``): every ``*.md`` but a README and anything under a dot-directory,
    as ``aegis migrate`` reads them. Aegis serves none of them."""
    layout = WorkspaceLayout(Path(d))
    found: list[Path] = []
    for folder in layout.legacy_rule_dirs:
        if not folder.is_dir():
            continue
        for path in sorted(folder.rglob("*.md")):
            relative = path.relative_to(folder).parts
            if path.name.lower() != "readme.md" and not any(part.startswith(".") for part in relative):
                found.append(path)
    return found


def unmigrated_state(d: str | Path | os.PathLike[str]) -> list[str]:
    """The v3 files and directories in workspace ``d`` that ``aegis migrate`` converts or
    retires and v4 never reads (repo-relative POSIX paths, in a fixed order): the v3
    ledger and its archives, the v2 ledger, aegis.conf, slots.yaml/config.yaml, keys,
    receipts and the signed manifest. Empty for a v4 workspace."""
    layout = WorkspaceLayout(Path(d))
    found = [f"{AEGIS_DIRNAME}/{rel}" for rel in LEGACY_UPGRADE_MARKERS if os.path.lexists(layout.legacy(rel))]
    found += [name for name in LEGACY_REPO_CONFS if os.path.lexists(layout.root / name)]
    if os.path.lexists(layout.legacy_predecessor_ledger):
        found.append(layout.legacy_predecessor_ledger.relative_to(layout.root).as_posix())
    return found


def refuse_unmigrated_v3(d: str | Path | os.PathLike[str]) -> None:
    """Raise an actionable WorkspaceError if directory contains an unmigrated .soma/ workspace:
    rule files left in its rule directories (even next to ``.aegis/``, where they would
    silently not be served), or, without ``.aegis/``, any ``.soma/`` at all."""
    d_str = str(Path(d).resolve())
    if unconverted_rule_files(d_str):
        raise WorkspaceError(LEGACY_SOMA_UPGRADE_MSG.format(path=d_str))
    if is_aegis_workspace(d_str):
        return
    soma = os.path.join(d_str, LEGACY_SOMA_DIRNAME)
    if os.path.isdir(os.path.join(soma, "cells")) or os.path.isdir(os.path.join(soma, "rules")):
        raise WorkspaceError(LEGACY_SOMA_UPGRADE_MSG.format(path=d_str))
    if d_str not in ("/tmp", "/var/tmp", _home_str()):
        if os.path.isdir(soma):
            raise WorkspaceError(LEGACY_SOMA_UPGRADE_MSG.format(path=d_str))


def _denied(d: str | Path | os.PathLike[str]) -> str | None:
    """Why ``d`` can never be a workspace ("home_directory", "filesystem_root"), or None.
    A path that cannot be resolved is denied as well: it is never bound."""
    try:
        return denial(Path(d).resolve())
    except (OSError, RuntimeError, ValueError):
        return "unresolvable"


def _is_workspace_dir(d: str) -> bool:
    """Check if directory contains a valid Aegis workspace marker (.aegis/rules or .aegis).

    Never ``$HOME`` or the filesystem root (AD-4): ``~/.aegis/rules`` is the personal
    read-only rule layer and ``~/.aegis`` the user plane, so neither marks a workspace.
    """
    if _denied(d):
        return False
    if has_rules_dir(d):
        return True
    return d not in ("/tmp", "/var/tmp") and is_aegis_workspace(d)


def resolve_workspace_root(
    start: str | Path | os.PathLike[str] | None = None,
    caller_file: str | Path | os.PathLike[str] | None = None,
    strict_env: bool = False,
) -> Path:
    """Find the project root containing .aegis/rules/ or .aegis/."""
    # 1. AEGIS_WORKSPACE, the operator's pin (D11): final, and never $HOME or the root
    aegis_ws = env_workspace()
    if aegis_ws:
        denied = _denied(aegis_ws)
        if denied:
            raise WorkspaceNotFoundError(
                f"AEGIS_WORKSPACE is set to {aegis_ws}, which is the {denied.replace('_', ' ')}"
                if denied != "unresolvable" else f"AEGIS_WORKSPACE is set to {aegis_ws}, which cannot be resolved"
            )
        if os.path.isdir(aegis_ws):
            refuse_unmigrated_v3(aegis_ws)
        if has_rules_dir(aegis_ws):
            return Path(aegis_ws).resolve()
        elif strict_env:
            raise WorkspaceNotFoundError(
                f"AEGIS_WORKSPACE is set to {aegis_ws} but no .aegis/rules found there (missing valid rules)."
            )
        elif os.path.isdir(aegis_ws):
            return Path(aegis_ws).resolve()

    # 3. Explicit start path walk-up, bounded like every walk below (see _walk_up)
    if start is not None:
        cand = os.path.abspath(str(start))
        d = cand if os.path.isdir(cand) else os.path.dirname(cand)
        refuse_unmigrated_v3(d)
        found = _walk_up(d)
        return found if found is not None else Path(d).resolve()

    # 4-5. The cwd, then up from it
    cwd = os.getcwd()
    refuse_unmigrated_v3(cwd)
    found = _walk_up(cwd)
    if found is not None:
        return found

    # 6. Walk up from caller_file (skipping vendor/ directories)
    if caller_file is not None:
        def _not_vendored(d: Path) -> bool:
            return _is_workspace_dir(str(d)) and "vendor" not in d.parts[:-1]

        found = bounded_walk_up(os.path.dirname(os.path.abspath(str(caller_file))), accept=_not_vendored)
        if found is not None:
            return found

    # 7. Fallback to CWD
    return Path(cwd).resolve()


def _walk_up(start: str) -> Path | None:
    """The nearest workspace from ``start`` upwards (AD-4's bounded walk-up): never above
    the git toplevel around ``start``, never ``$HOME`` or the filesystem root. A
    legacy ``.soma/`` met on the way raises, as before."""

    def accept(d: Path) -> bool:
        if _is_workspace_dir(str(d)):
            return True
        refuse_unmigrated_v3(d)
        return False

    return bounded_walk_up(start, accept=accept)


__all__ = [
    "LEGACY_SOMA_UPGRADE_MSG",
    "UPGRADE_STATE_MSG",
    "_is_workspace_dir",
    "refuse_unmigrated_v3",
    "resolve_workspace_root",
    "unconverted_rule_files",
    "unmigrated_state",
]

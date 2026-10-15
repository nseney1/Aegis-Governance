"""Workspace discovery and compound fingerprinting for Soma (Layer 0 Core).

Discovers project roots via the AEGIS_WORKSPACE pin, upward directory walks, and callers.
Provides compound fingerprinting (is_soma_repo) to distinguish Soma's own repository
from foreign repositories adopting Soma governance.
Strictly zero-dependency: uses only Python standard library.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

from aegis_core.config import env_workspace
from aegis_core.errors import WorkspaceError, WorkspaceNotFoundError
from aegis_core.workspace.layout import LEGACY_SOMA_DIRNAME, has_rules_dir, is_aegis_workspace

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


def check_legacy_soma_sentinel(d: str | Path | os.PathLike[str]) -> None:
    """Raise an actionable WorkspaceError if directory contains an unmigrated .soma/ workspace."""
    d_str = str(Path(d).resolve())
    if is_aegis_workspace(d_str):
        return
    soma = os.path.join(d_str, LEGACY_SOMA_DIRNAME)
    if os.path.isdir(os.path.join(soma, "cells")) or os.path.isdir(os.path.join(soma, "rules")):
        raise WorkspaceError(LEGACY_SOMA_UPGRADE_MSG.format(path=d_str))
    if d_str not in ("/tmp", "/var/tmp", _home_str()):
        if os.path.isdir(soma):
            raise WorkspaceError(LEGACY_SOMA_UPGRADE_MSG.format(path=d_str))


def _is_workspace_dir(d: str) -> bool:
    """Check if directory contains a valid Aegis workspace marker (.aegis/rules or .aegis)."""
    if has_rules_dir(d):
        return True
    if d not in ("/tmp", "/var/tmp", _home_str()):
        if is_aegis_workspace(d):
            return True
    return False


def is_aegis_repo(root: Path) -> bool:
    """Compound check to verify if a workspace root is the core Aegis repository.

    Requires:
    1. pyproject.toml containing non-commented name = 'aegis-guardrails' or 'aegis-governance'
    2. Both aegis_core/ and aegis_cli/ directories exist.
    """
    pyproject = root / "pyproject.toml"
    if not pyproject.is_file():
        return False

    try:
        content = pyproject.read_text(encoding="utf-8", errors="replace")
        if not re.search(
            r'^[ \t]*name[ \t]*=[ \t]*["\'](?:aegis-guardrails|(?:soma|aegis)-governance)["\']',
            content,
            re.MULTILINE,
        ):
            return False
    except OSError:
        return False

    has_core = (root / "aegis_core").is_dir()
    has_cli = (root / "aegis_cli").is_dir()
    return has_core and has_cli


def resolve_workspace_root(
    start: str | Path | os.PathLike[str] | None = None,
    caller_file: str | Path | os.PathLike[str] | None = None,
    strict_env: bool = False,
) -> Path:
    """Find the project root containing .aegis/rules/ or .aegis/."""
    # 1. AEGIS_WORKSPACE, the operator's pin (D11)
    aegis_ws = env_workspace()
    if aegis_ws:
        if os.path.isdir(aegis_ws):
            check_legacy_soma_sentinel(aegis_ws)
        if has_rules_dir(aegis_ws):
            return Path(aegis_ws).resolve()
        elif strict_env:
            raise WorkspaceNotFoundError(
                f"AEGIS_WORKSPACE is set to {aegis_ws} but no .aegis/rules found there (missing valid rules)."
            )
        elif os.path.isdir(aegis_ws):
            return Path(aegis_ws).resolve()

    # 3. Explicit start path walk-up
    if start is not None:
        cand = os.path.abspath(str(start))
        d = cand if os.path.isdir(cand) else os.path.dirname(cand)
        check_legacy_soma_sentinel(d)
        while d != os.path.dirname(d):
            if _is_workspace_dir(d):
                return Path(d).resolve()
            check_legacy_soma_sentinel(d)
            d = os.path.dirname(d)
        return Path(cand if os.path.isdir(cand) else os.path.dirname(cand)).resolve()

    # 4. Check CWD directly
    cwd = os.getcwd()
    check_legacy_soma_sentinel(cwd)
    if _is_workspace_dir(cwd):
        return Path(cwd).resolve()

    # 5. Walk up from CWD
    d = cwd
    while d != os.path.dirname(d):
        if _is_workspace_dir(d):
            return Path(d).resolve()
        check_legacy_soma_sentinel(d)
        d = os.path.dirname(d)

    # 6. Walk up from caller_file (skipping vendor/ directories)
    if caller_file is not None:
        d = os.path.dirname(os.path.abspath(str(caller_file)))
        while d != os.path.dirname(d):
            if (
                _is_workspace_dir(d)
                and "/vendor/" not in d
                and os.path.basename(os.path.dirname(d)) != "vendor"
            ):
                return Path(d).resolve()
            d = os.path.dirname(d)

    # 7. Fallback to CWD
    return Path(cwd).resolve()


__all__ = [
    "LEGACY_SOMA_UPGRADE_MSG",
    "_is_workspace_dir",
    "check_legacy_soma_sentinel",
    "is_aegis_repo",
    "resolve_workspace_root",
]

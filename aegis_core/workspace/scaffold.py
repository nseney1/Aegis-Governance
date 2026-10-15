"""Workspace scaffolding and initialization for Aegis (Layer 0 Core).

Creates canonical directory structure (.aegis/rules/{invariants,traps,gates}, .aegis/evidence, .aegis/metrics).
Guards against bare git repositories.
Strictly zero-dependency: uses only Python standard library.
"""
from __future__ import annotations

import os
from pathlib import Path
import tempfile

from aegis_core.errors import WorkspaceBareRepoError
from aegis_core.workspace.layout import RUNTIME_STATE_IGNORES

_GITIGNORE_HEADER = (
    "# Aegis machine-local runtime state. `aegis init` appends any missing entry\n"
    "# and keeps your own lines; negate an entry (!/evidence/) to commit it.\n"
)


def scaffold_workspace(
    root: Path,
    cells_dir: Path,
    evidence_dir: Path,
    metrics_dir: Path,
    minimal: bool = False,
    dry_run: bool = False,
) -> list[Path]:
    """Scaffold standard directory structure for Aegis governance.

    Creates .aegis/rules/ and .aegis/evidence/ (and .aegis/metrics/).
    Guards against bare git repositories.
    """
    if (
        (root / "HEAD").is_file()
        and (root / "config").is_file()
        and (root / "objects").is_dir()
        and not (root / ".git").exists()
    ):
        raise WorkspaceBareRepoError(
            f"Cannot scaffold aegis in a bare git repository: {root}"
        )

    dirs_to_create: list[Path] = [
        cells_dir / "invariants",
        evidence_dir,
    ]
    if not minimal:
        dirs_to_create.extend([
            cells_dir / "traps",
            cells_dir / "gates",
            metrics_dir,
        ])

    if not dry_run:
        for d in dirs_to_create:
            d.mkdir(parents=True, exist_ok=True)

    return dirs_to_create


def ensure_runtime_gitignore(aegis_dir: Path, dry_run: bool = False) -> str:
    """Make ``.aegis/.gitignore`` list every runtime-state entry; return what happened.

    Returns ``"created"``, ``"updated"``, ``"unchanged"``, ``"symlink"`` (left alone:
    appending would edit whatever file it points at) or ``"dry-run"``. Existing lines
    are never rewritten; an entry already present, or negated by the user, is not
    added again, so repeated runs are byte-identical.
    """
    path = Path(aegis_dir) / ".gitignore"
    if path.is_symlink():
        return "symlink"
    # surrogateescape: a user line in another encoding is written back byte-for-byte.
    existing = path.read_text(encoding="utf-8", errors="surrogateescape") if path.is_file() else None
    present = {line.strip().lstrip("!") for line in (existing or "").splitlines()}
    missing = [entry for entry in RUNTIME_STATE_IGNORES if entry not in present]
    if existing is not None and not missing:
        return "unchanged"
    if dry_run:
        return "dry-run"

    block = "".join(f"{entry}\n" for entry in missing)
    if existing is None:
        content = _GITIGNORE_HEADER + block
    else:
        sep = "" if existing == "" or existing.endswith("\n") else "\n"
        header = "" if _GITIGNORE_HEADER.splitlines()[0] in existing else _GITIGNORE_HEADER
        content = existing + sep + header + block

    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".gitignore.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", errors="surrogateescape", newline="") as fh:
            fh.write(content)
        if existing is not None:
            mode = path.stat().st_mode & 0o7777
        else:
            umask = os.umask(0)  # single-threaded CLI: no file creation can race this
            os.umask(umask)
            mode = 0o666 & ~umask
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return "created" if existing is None else "updated"


__all__ = ["ensure_runtime_gitignore", "scaffold_workspace"]

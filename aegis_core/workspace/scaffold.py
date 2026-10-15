"""Workspace scaffolding: the D12 directories and ``.aegis/.gitignore``.

Creates ``.aegis/rules/<type>/`` and ``.aegis/state/`` and refuses bare git
repositories. Standard library only.
"""
from __future__ import annotations

from pathlib import Path

from aegis_core.errors import WorkspaceBareRepoError
from aegis_core.storage import atomic_write_bytes
from aegis_core.workspace.layout import GITIGNORE_ENTRIES, WorkspaceLayout

_GITIGNORE_HEADER = (
    "# Aegis machine-local state. `aegis init` appends any missing entry\n"
    "# and keeps your own lines.\n"
)


def scaffold_workspace(layout: WorkspaceLayout, minimal: bool = False, dry_run: bool = False) -> list[Path]:
    """Create the D12 directories; return the directories that make up the layout.

    ``minimal`` scaffolds only ``rules/invariants/``; otherwise traps and gates too.
    """
    root = layout.root
    if (
        (root / "HEAD").is_file()
        and (root / "config").is_file()
        and (root / "objects").is_dir()
        and not (root / ".git").exists()
    ):
        raise WorkspaceBareRepoError(f"Cannot scaffold aegis in a bare git repository: {root}")

    dirs = [layout.rules_dir / "invariants", layout.state_dir]
    if not minimal:
        dirs[1:1] = [layout.rules_dir / "traps", layout.rules_dir / "gates"]
    if not dry_run:
        for d in dirs:
            d.mkdir(parents=True, exist_ok=True)
    return dirs


def ensure_runtime_gitignore(aegis_dir: Path, dry_run: bool = False) -> str:
    """Make ``.aegis/.gitignore`` list ``state/``; return what happened.

    Returns ``"created"``, ``"updated"``, ``"unchanged"``, ``"symlink"`` (left alone:
    appending would edit whatever file it points at) or ``"dry-run"``. Existing bytes
    are never rewritten, line endings included, and the appended block uses CRLF when
    the file already does; an entry already present, or negated by the user, is not
    added again, so repeated runs are byte-identical.
    """
    path = Path(aegis_dir) / ".gitignore"
    if path.is_symlink():
        return "symlink"
    # Decode bytes, not text mode: universal newlines would turn CRLF into LF on the
    # way back out. surrogateescape round-trips a line in another encoding untouched.
    existing = path.read_bytes().decode("utf-8", "surrogateescape") if path.is_file() else None
    eol = "\r\n" if existing and "\r\n" in existing else "\n"
    present = {line.strip().lstrip("!") for line in (existing or "").splitlines()}
    missing = [entry for entry in GITIGNORE_ENTRIES if entry not in present]
    if existing is not None and not missing:
        return "unchanged"
    if dry_run:
        return "dry-run"

    block = "".join(f"{entry}{eol}" for entry in missing)
    if existing is None:
        content = _GITIGNORE_HEADER + block
    else:
        sep = "" if existing == "" or existing.endswith("\n") else eol
        header = "" if _GITIGNORE_HEADER.splitlines()[0] in existing else _GITIGNORE_HEADER.replace("\n", eol)
        content = existing + sep + header + block
    atomic_write_bytes(path, content.encode("utf-8", "surrogateescape"))
    return "created" if existing is None else "updated"


__all__ = ["ensure_runtime_gitignore", "scaffold_workspace"]

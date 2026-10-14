"""Canonical, race-detecting inventory of governance cell files."""
from __future__ import annotations

import fnmatch
import hashlib
import os
from pathlib import Path
import stat
from dataclasses import dataclass
from typing import Iterable, List, Optional, Tuple


@dataclass(frozen=True)
class CellInventoryEntry:
    """One immutable cell snapshot captured during inventory."""

    relative_path: str
    absolute_path: str
    content: bytes
    digest: str
    size: int


@dataclass(frozen=True)
class CellInventory:
    """Stable entries and their aggregate content fingerprint."""

    entries: Tuple[CellInventoryEntry, ...]
    fingerprint: str


class CellInventoryError(RuntimeError):
    """The cell tree could not be inventoried safely and consistently."""

    def __init__(
        self,
        operation: str,
        path: str,
        message: str,
        cause: Optional[BaseException] = None,
    ) -> None:
        self.operation = operation
        self.path = os.path.abspath(path)
        self.cause = cause
        super().__init__(f"cell inventory {operation} failed for {self.path}: {message}")


# On Windows os.stat() reports st_ctime as the creation time while os.fstat()
# reports the last-change time, so a path stat and an fd stat of the same
# unchanged file disagree once it has ever been written (BUG-035). Creation
# time never moves on a rewrite anyway; st_ino, st_size and st_mtime_ns still
# catch replacement and modification there.
_COMPARE_CTIME = os.name != "nt"


def _stat_signature(info: os.stat_result) -> Tuple[int, int, int, int, int, int]:
    return (
        info.st_dev,
        info.st_ino,
        info.st_mode,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns if _COMPARE_CTIME else 0,
    )


def _identity_signature(info: os.stat_result) -> Tuple[int, int, int]:
    """Identity fields used for ancestors whose unrelated contents may change."""
    return (info.st_dev, info.st_ino, info.st_mode)


def _stat_path(path: str, operation: str = "stat") -> os.stat_result:
    try:
        return os.stat(path, follow_symlinks=False)
    except OSError as exc:
        raise CellInventoryError(operation, path, str(exc), exc) from exc


def _optional_stat(path: str) -> Optional[os.stat_result]:
    try:
        return os.stat(path, follow_symlinks=False)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise CellInventoryError("stat", path, str(exc), exc) from exc


def _require_directory(path: str, info: os.stat_result) -> None:
    if stat.S_ISLNK(info.st_mode):
        raise CellInventoryError("validate", path, "symlinked directory is not allowed")
    if not stat.S_ISDIR(info.st_mode):
        raise CellInventoryError("validate", path, "expected a directory")


def _read_stable_file(path: str, before: os.stat_result) -> bytes:
    if stat.S_ISLNK(before.st_mode):
        raise CellInventoryError("validate", path, "symlinked .md cell is not allowed")
    if not stat.S_ISREG(before.st_mode):
        raise CellInventoryError("validate", path, ".md cell is not a regular file")

    flags = os.O_RDONLY
    # Without O_BINARY, Windows opens in text mode: os.read() turns CRLF into
    # LF and stops at 0x1A, so the snapshot would not be the bytes on disk.
    flags |= getattr(os, "O_BINARY", 0)
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise CellInventoryError("open", path, str(exc), exc) from exc

    try:
        try:
            opened = os.fstat(fd)
        except OSError as exc:
            raise CellInventoryError("stat", path, str(exc), exc) from exc
        if _stat_signature(opened) != _stat_signature(before):
            raise CellInventoryError("read", path, "file changed before it was opened")

        chunks = []  # type: List[bytes]
        while True:
            try:
                chunk = os.read(fd, 65536)
            except OSError as exc:
                raise CellInventoryError("read", path, str(exc), exc) from exc
            if not chunk:
                break
            chunks.append(chunk)

        try:
            after_read = os.fstat(fd)
        except OSError as exc:
            raise CellInventoryError("stat", path, str(exc), exc) from exc
        if _stat_signature(after_read) != _stat_signature(opened):
            raise CellInventoryError("read", path, "file changed while it was read")
    finally:
        try:
            os.close(fd)
        except OSError:
            pass

    after_path = _stat_path(path)
    if _stat_signature(after_path) != _stat_signature(before):
        raise CellInventoryError("read", path, "file changed during inventory")
    return b"".join(chunks)


def _empty_inventory() -> CellInventory:
    digest = hashlib.sha256(b"soma-cell-inventory-v1\0").hexdigest()
    return CellInventory(entries=(), fingerprint=digest)


def inventory_cells(workspace: str) -> CellInventory:
    """Capture every ``.md`` below ``.aegis/rules`` or ``.soma/cells`` without following links.

    The returned content bytes are the same bytes used to calculate each entry
    digest and the aggregate fingerprint. Directory and file metadata are
    checked before and after capture so concurrent changes fail closed.
    """
    workspace_abs = os.path.abspath(os.fspath(workspace))
    aegis_dir = os.path.join(workspace_abs, ".aegis")
    aegis_rules_dir = os.path.join(aegis_dir, "rules")
    soma_dir = os.path.join(workspace_abs, ".soma")
    soma_rules_dir = os.path.join(soma_dir, "rules")
    soma_cells_dir = os.path.join(soma_dir, "cells")

    if os.path.isdir(aegis_rules_dir):
        parent_dir = aegis_dir
        cells_dir = aegis_rules_dir
    elif os.path.isdir(soma_rules_dir):
        parent_dir = soma_dir
        cells_dir = soma_rules_dir
    else:
        parent_dir = soma_dir
        cells_dir = soma_cells_dir

    workspace_info = _optional_stat(workspace_abs)
    if workspace_info is None:
        return _empty_inventory()
    _require_directory(workspace_abs, workspace_info)

    parent_info = _optional_stat(parent_dir)
    if parent_info is None:
        return _empty_inventory()
    _require_directory(parent_dir, parent_info)

    cells_info = _optional_stat(cells_dir)
    if cells_info is None:
        return _empty_inventory()
    _require_directory(cells_dir, cells_info)

    ancestor_identities = {
        workspace_abs: _identity_signature(workspace_info),
        parent_dir: _identity_signature(parent_info),
    }
    directory_signatures = {}  # type: dict[str, Tuple[int, int, int, int, int, int]]
    cell_paths = []  # type: List[str]

    def walk_error(exc: OSError) -> None:
        path = getattr(exc, "filename", None) or cells_dir
        raise CellInventoryError("list", path, str(exc), exc)

    try:
        walker = os.walk(cells_dir, topdown=True, followlinks=False, onerror=walk_error)
        for dirpath, dirnames, filenames in walker:
            dir_info = _stat_path(dirpath)
            _require_directory(dirpath, dir_info)
            directory_signatures[dirpath] = _stat_signature(dir_info)

            dirnames.sort()
            for dirname in dirnames:
                child = os.path.join(dirpath, dirname)
                child_info = _stat_path(child)
                if stat.S_ISLNK(child_info.st_mode):
                    raise CellInventoryError(
                        "validate", child, "symlinked directory is not allowed"
                    )
                if not stat.S_ISDIR(child_info.st_mode):
                    raise CellInventoryError("validate", child, "expected a directory")

            for filename in sorted(filenames):
                if filename.endswith(".md"):
                    cell_paths.append(os.path.join(dirpath, filename))
    except CellInventoryError:
        raise
    except OSError as exc:
        path = getattr(exc, "filename", None) or cells_dir
        raise CellInventoryError("list", path, str(exc), exc) from exc

    entries = []  # type: List[CellInventoryEntry]
    for path in sorted(cell_paths):
        before = _stat_path(path)
        content = _read_stable_file(path, before)
        digest = hashlib.sha256(content).hexdigest()
        relative = os.path.relpath(path, workspace_abs).replace(os.sep, "/")
        entries.append(CellInventoryEntry(
            relative_path=relative,
            absolute_path=os.path.abspath(path),
            content=content,
            digest=digest,
            size=len(content),
        ))

    for path, expected in ancestor_identities.items():
        current = _stat_path(path)
        if _identity_signature(current) != expected:
            raise CellInventoryError("list", path, "ancestor changed during inventory")
    for path, expected in directory_signatures.items():
        current = _stat_path(path)
        if _stat_signature(current) != expected:
            raise CellInventoryError("list", path, "directory changed during inventory")

    aggregate = hashlib.sha256(b"soma-cell-inventory-v1\0")
    for entry in entries:
        aggregate.update(entry.relative_path.encode("utf-8") + b"\0")
        aggregate.update(bytes.fromhex(entry.digest))
        aggregate.update(b"\0")
    return CellInventory(entries=tuple(entries), fingerprint=aggregate.hexdigest())


@dataclass(frozen=True)
class CellMatch:
    """Represents a cell whose target_paths matched changed files."""

    cell_id: str
    cell_type: str
    cell_path: str
    frontmatter: dict
    matched_files: Tuple[str, ...]
    first_matching_target: Optional[str] = None


def find_matching_cells(
    cells_dir: str | Path,
    changed_files: Iterable[str],
    repo_root: str = "",
    allow_basename_match: bool = True,
) -> List[CellMatch]:
    """Find all cells in cells_dir whose target_paths match changed_files."""
    from aegis_core.yaml import parse_frontmatter

    cells_path = Path(cells_dir)
    if not cells_path.is_dir():
        return []

    files_list = [f for f in changed_files if f]
    if not files_list:
        return []

    rel_modified: List[str] = []
    norm_root = str(repo_root).replace("\\", "/").rstrip("/") if repo_root else ""
    for f in files_list:
        norm_f = str(f).replace("\\", "/")
        if norm_root and norm_f.startswith(norm_root):
            rel = norm_f[len(norm_root):].lstrip("/")
        else:
            rel = norm_f.lstrip("/")
        rel_modified.append(rel)

    matches: List[CellMatch] = []
    for md_file in sorted(cells_path.rglob("*.md")):
        if md_file.name == "README.md":
            continue
        try:
            content = md_file.read_text(encoding="utf-8")
            fm = parse_frontmatter(content) or {}
        except Exception:
            continue

        raw_targets = fm.get("target_paths", [])
        if isinstance(raw_targets, str):
            raw_targets = [raw_targets]
        if not isinstance(raw_targets, list) or not raw_targets:
            continue

        cell_id = fm.get("id") or md_file.stem
        cell_type = fm.get("type", "unknown")

        matched_for_cell: List[str] = []
        first_target: Optional[str] = None

        for rel_file in rel_modified:
            file_matched = False
            for target in raw_targets:
                pat_norm = str(target).replace("\\", "/")
                if fnmatch.fnmatch(rel_file, pat_norm) or (
                    allow_basename_match and fnmatch.fnmatch(os.path.basename(rel_file), pat_norm)
                ):
                    file_matched = True
                    if first_target is None:
                        first_target = target
                    break
            if file_matched:
                matched_for_cell.append(rel_file)

        if matched_for_cell:
            matches.append(CellMatch(
                cell_id=cell_id,
                cell_type=cell_type,
                cell_path=str(md_file.resolve()),
                frontmatter=fm,
                matched_files=tuple(sorted(set(matched_for_cell))),
                first_matching_target=first_target,
            ))

    return matches


from aegis_core.yaml import parse_frontmatter

# Backward-compatible and canonical engineering aliases
RuleInventory = CellInventory
RuleInventoryEntry = CellInventoryEntry
RuleInventoryError = CellInventoryError
RuleMatch = CellMatch
inventory_rules = inventory_cells
find_matching_rules = find_matching_cells

__all__ = [
    "CellInventory",
    "CellInventoryEntry",
    "CellInventoryError",
    "CellMatch",
    "RuleInventory",
    "RuleInventoryEntry",
    "RuleInventoryError",
    "RuleMatch",
    "find_matching_cells",
    "find_matching_rules",
    "inventory_cells",
    "inventory_rules",
    "parse_frontmatter",
]



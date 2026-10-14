"""Cross-platform atomic storage utilities for Aegis Guardrails.

Provides crash-resilient atomic file writes via temporary files, directory fsync,
and exponential backoff retry on Windows sharing violations (WinError 32).
"""
from __future__ import annotations

import asyncio
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Iterable

from aegis_core.operations import Operations
from aegis_core.taxonomy import STORAGE_INITIAL_DELAY_SECONDS, STORAGE_MAX_RETRIES
from aegis_core.workspace.layout import WorkspaceLayout


def fsync_dir(directory: Path | str) -> None:
    """Best-effort directory fsync so file replacements survive power loss (POSIX)."""
    if os.name != "posix":
        return
    try:
        fd = os.open(str(directory), os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def _replace_with_retry(
    src: str,
    dst: str,
    max_retries: int = STORAGE_MAX_RETRIES,
    initial_delay: float = STORAGE_INITIAL_DELAY_SECONDS,
) -> None:
    """Replace destination with source, retrying on transient Windows sharing violations.

    On Windows, os.replace raises PermissionError with winerror 32 (ERROR_SHARING_VIOLATION)
    or 5 (ERROR_ACCESS_DENIED) when an indexer, antivirus, or reader holds the destination.
    With 8 attempts and initial_delay=0.01s, backoff reaches ~2.55s total budget.
    """
    delay = initial_delay
    for attempt in range(max_retries):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if attempt == max_retries - 1:
                raise
            time.sleep(delay)
            delay *= 2


def atomic_write_bytes(
    path: Path | str,
    data: bytes,
    max_retries: int = STORAGE_MAX_RETRIES,
    initial_delay: float = STORAGE_INITIAL_DELAY_SECONDS,
) -> None:
    """Atomically write binary data to path via a temporary file in the same directory.

    Guarantees:
    - Target directory is created if missing.
    - Write, flush, and fsync happen before the atomic replace.
    - Temporary file is cleaned up if any step fails.
    - Retries on Windows file locking conflicts.
    - Best-effort directory fsync on POSIX.
    """
    p = Path(path).resolve()
    p.parent.mkdir(parents=True, exist_ok=True)

    fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=f".{p.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        _replace_with_retry(tmp, str(p), max_retries=max_retries, initial_delay=initial_delay)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise

    fsync_dir(p.parent)


def atomic_write_text(
    path: Path | str,
    text: str,
    encoding: str = "utf-8",
    max_retries: int = STORAGE_MAX_RETRIES,
    initial_delay: float = STORAGE_INITIAL_DELAY_SECONDS,
) -> None:
    """Atomically write string text to path."""
    atomic_write_bytes(
        path=path,
        data=text.encode(encoding),
        max_retries=max_retries,
        initial_delay=initial_delay,
    )


def atomic_write_file(
    path: Path | str,
    content: str | bytes,
    encoding: str = "utf-8",
    max_retries: int = STORAGE_MAX_RETRIES,
    initial_delay: float = STORAGE_INITIAL_DELAY_SECONDS,
) -> None:
    """Polymorphic atomic write supporting either text string or raw bytes."""
    if isinstance(content, bytes):
        atomic_write_bytes(
            path=path,
            data=content,
            max_retries=max_retries,
            initial_delay=initial_delay,
        )
    else:
        atomic_write_text(
            path=path,
            text=str(content),
            encoding=encoding,
            max_retries=max_retries,
            initial_delay=initial_delay,
        )


async def async_atomic_write_text(
    path: Path | str,
    text: str,
    encoding: str = "utf-8",
    max_retries: int = STORAGE_MAX_RETRIES,
    initial_delay: float = STORAGE_INITIAL_DELAY_SECONDS,
) -> None:
    """Asynchronously and atomically write string text to path off the main event loop."""
    await asyncio.to_thread(
        atomic_write_text,
        path=path,
        text=text,
        encoding=encoding,
        max_retries=max_retries,
        initial_delay=initial_delay,
    )


def read_text_utf8(path: Path | str) -> str:
    """Read a text file with UTF-8 encoding, stripping BOM if present."""
    p = Path(path)
    return p.read_text(encoding="utf-8-sig")


def atomic_write_and_unlink(
    source_path: Path | str,
    target_path: Path | str,
    new_content: str,
) -> None:
    """Write new_content to target_path atomically and unlink source_path with rollback."""
    src = Path(source_path)
    dst = Path(target_path)
    atomic_write_text(dst, new_content)
    try:
        if src != dst and src.exists():
            src.unlink()
    except Exception:
        if dst.exists() and src.exists():
            try:
                os.remove(dst)
            except Exception as ex:
                raise RuntimeError(f"Rollback failed: duplicate rule remains at {dst}") from ex
        raise


class Storage:
    """Workspace-scoped storage manager composing Operations (S2)."""

    def __init__(self, workspace: Path | str | Any) -> None:
        self._ops = Operations(workspace)

    @property
    def ops(self) -> Operations:
        return self._ops

    @property
    def layout(self) -> WorkspaceLayout:
        return self._ops.layout

    @property
    def root(self) -> Path:
        return self._ops.root

    def read_text(self, path: Path | str, default: str = "") -> str:
        return self._ops.read_text(path, default=default)

    def write_text(self, path: Path | str, content: str) -> None:
        self._ops.write_text(path, content)

    def write_atomic(self, path: Path | str, content: str) -> None:
        self._ops.write_text(path, content)

    atomic_write = write_atomic

    def write_bytes(self, path: Path | str, data: bytes) -> None:
        self._ops.write_bytes(path, data)

    def read_jsonl(self, path: Path | str) -> list[dict[str, Any]]:
        return self._ops.read_jsonl(path)

    def append_jsonl(self, path: Path | str, record: dict[str, Any]) -> None:
        self._ops.append_jsonl(path, record)

    def write_jsonl(self, path: Path | str, records: Iterable[dict[str, Any]]) -> None:
        self._ops.write_jsonl(path, records)


__all__ = [
    "Storage",
    "async_atomic_write_text",
    "atomic_write_and_unlink",
    "atomic_write_bytes",
    "atomic_write_file",
    "atomic_write_text",
    "fsync_dir",
    "read_text_utf8",
]




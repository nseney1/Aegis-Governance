"""Cross-platform atomic storage utilities for Soma Governance.

Provides crash-resilient atomic file writes via temporary files, directory fsync,
and exponential backoff retry on Windows sharing violations (WinError 32).
"""
from __future__ import annotations

import asyncio
import os
import tempfile
import time
from pathlib import Path


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
    max_retries: int = 8,
    initial_delay: float = 0.01,
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
    max_retries: int = 8,
    initial_delay: float = 0.01,
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
    max_retries: int = 8,
    initial_delay: float = 0.01,
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
    max_retries: int = 8,
    initial_delay: float = 0.01,
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
    max_retries: int = 8,
    initial_delay: float = 0.01,
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


__all__ = [
    "async_atomic_write_text",
    "atomic_write_bytes",
    "atomic_write_file",
    "atomic_write_text",
    "fsync_dir",
    "read_text_utf8",
]


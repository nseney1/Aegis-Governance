"""L0 storage: the one workspace lock, atomic file writes and JSONL I/O (ADR 0005 AD-3).

Every write of Aegis state or rule files goes through this module, so the crash and
concurrency guarantees live in one place:

- ``locked(workspace)``: the single workspace lock, ``.aegis/state/lock``. It is
  re-entrant per thread, so nested acquisition never deadlocks, and its wait is
  bounded with an error that names the lock file.
- ``atomic_write_bytes``/``atomic_write_text``: write a temporary file next to the
  target, fsync it, then replace. An existing file keeps its mode; a new file gets
  the mode the umask gives (0o644 typically), not mkstemp's 0o600.
- ``append_jsonl``: one ``O_APPEND`` write and one fsync. A torn trailing line left by
  a crash is terminated first, so it cannot swallow the new row.
- ``read_jsonl``: decodes line by line (bytes, utf-8-sig); invalid lines are skipped
  and counted, never raised.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import json
import os
from pathlib import Path
import secrets
import stat
import threading
import time
from typing import Any, Dict, Iterable, Iterator, List, Optional, Tuple

from aegis_core.errors import LockTimeoutError
from aegis_core.taxonomy import (
    LOCK_MAX_BACKOFF_SECONDS,
    LOCK_RETRY_INTERVAL_SECONDS,
    LOCK_TIMEOUT_SECONDS,
    STORAGE_INITIAL_DELAY_SECONDS,
    STORAGE_MAX_RETRIES,
)
from aegis_core.workspace.layout import WorkspaceLayout

try:
    import fcntl
except ImportError:  # Windows
    fcntl = None  # type: ignore[assignment]

try:
    import msvcrt
except ImportError:  # POSIX
    msvcrt = None  # type: ignore[assignment]

__all__ = [
    "JsonlRead",
    "LockTimeoutError",
    "append_jsonl",
    "atomic_write_and_unlink",
    "atomic_write_bytes",
    "atomic_write_text",
    "fsync_dir",
    "locked",
    "read_jsonl",
]

_O_BINARY = getattr(os, "O_BINARY", 0)
_O_CLOEXEC = getattr(os, "O_CLOEXEC", 0)
# A new file's permission bits before the umask: the kernel applies the umask, so no
# process-wide os.umask() round trip (which races other threads) is needed.
_NEW_FILE_MODE = 0o666


# ── The one workspace lock ───────────────────────────────────────────────────

_GUARD = threading.Lock()
_THREAD_LOCKS: Dict[str, "threading.RLock"] = {}
_HELD = threading.local()  # .depth: {lock path: (depth, fd or None)}


def _reset_after_fork() -> None:
    # A forked child inherits RLocks that threads of the parent may hold: start clean.
    global _GUARD, _THREAD_LOCKS, _HELD
    _GUARD = threading.Lock()
    _THREAD_LOCKS = {}
    _HELD = threading.local()


if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_reset_after_fork)


def _thread_lock(key: str) -> "threading.RLock":
    with _GUARD:
        lock = _THREAD_LOCKS.get(key)
        if lock is None:
            lock = _THREAD_LOCKS[key] = threading.RLock()
        return lock


def _held() -> Dict[str, Tuple[int, Optional[int]]]:
    held = getattr(_HELD, "depth", None)
    if held is None:
        held = _HELD.depth = {}
    return held


def _try_os_lock(fd: int) -> bool:
    if fcntl is not None:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except OSError:
            return False
    if msvcrt is not None:
        try:
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            return True
        except OSError:
            return False
    # Neither primitive exists: the per-process thread lock is all there is.
    return True


def _os_unlock(fd: int) -> None:
    try:
        if fcntl is not None:
            fcntl.flock(fd, fcntl.LOCK_UN)
        elif msvcrt is not None:
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
    except OSError:
        pass


def _timeout_error(path: Path, timeout: float) -> LockTimeoutError:
    return LockTimeoutError(
        f"timed out after {timeout:g}s waiting for the Aegis workspace lock {path}: "
        "another aegis process or thread holds it",
        path=str(path),
    )


@contextmanager
def locked(workspace: Any, timeout: float = LOCK_TIMEOUT_SECONDS) -> Iterator[Path]:
    """Hold the workspace lock (``.aegis/state/lock``) for the duration of the block.

    ``workspace`` is a Workspace, a path or a string; every spelling of one root shares
    one lock. Re-entrant per thread: a nested ``locked()`` in the thread that holds it
    returns immediately. Raises LockTimeoutError, naming the lock file, when another
    thread or process holds it for longer than ``timeout`` seconds.
    """
    lock_path = WorkspaceLayout(Path(os.fspath(workspace)).resolve()).lock_file
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    key = os.path.realpath(lock_path)
    held = _held()
    depth, fd = held.get(key, (0, None))
    if depth:
        held[key] = (depth + 1, fd)
        try:
            yield lock_path
        finally:
            d, f = held[key]
            held[key] = (d - 1, f)
        return

    deadline = time.monotonic() + max(0.0, timeout)
    thread_lock = _thread_lock(key)
    if not thread_lock.acquire(timeout=max(0.0, timeout)):
        raise _timeout_error(lock_path, timeout)
    fd = None
    try:
        fd = os.open(key, os.O_RDWR | os.O_CREAT | _O_BINARY | _O_CLOEXEC, _NEW_FILE_MODE)
        interval = LOCK_RETRY_INTERVAL_SECONDS
        while not _try_os_lock(fd):
            if time.monotonic() >= deadline:
                raise _timeout_error(lock_path, timeout)
            time.sleep(interval)
            interval = min(interval * 1.5, LOCK_MAX_BACKOFF_SECONDS)
        held[key] = (1, fd)
        try:
            yield lock_path
        finally:
            held.pop(key, None)
            _os_unlock(fd)
    finally:
        if fd is not None:
            os.close(fd)
        thread_lock.release()


# ── Atomic writes ─────────────────────────────────────────────────────────────

def fsync_dir(directory: Path | str) -> None:
    """Best-effort directory fsync so a rename or a new file survives power loss (POSIX)."""
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


def _replace_with_retry(src: str, dst: str, max_retries: int, initial_delay: float) -> None:
    """os.replace, retrying the transient Windows sharing violations (WinError 32/5) an
    indexer or antivirus causes. 8 attempts from 0.01s back off to ~2.55s in total."""
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


def _write_all(fd: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        written = os.write(fd, view)
        view = view[written:]


def atomic_write_bytes(
    path: Path | str,
    data: bytes,
    max_retries: int = STORAGE_MAX_RETRIES,
    initial_delay: float = STORAGE_INITIAL_DELAY_SECONDS,
) -> None:
    """Replace ``path`` with ``data`` atomically: readers see the old or the new bytes.

    The parent directory is created if missing. An existing file keeps its permission
    bits; a new one gets ``0o666 & ~umask``. The temporary file is removed on failure.
    """
    target = Path(path).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        keep_mode: Optional[int] = stat.S_IMODE(os.stat(target).st_mode)
    except FileNotFoundError:
        keep_mode = None

    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | _O_BINARY | _O_CLOEXEC
    while True:
        tmp = str(target.parent / f".{target.name}.{secrets.token_hex(6)}.tmp")
        try:
            fd = os.open(tmp, flags, _NEW_FILE_MODE)
            break
        except FileExistsError:
            continue
    try:
        try:
            _write_all(fd, data)
            os.fsync(fd)
        finally:
            os.close(fd)
        if keep_mode is not None:
            os.chmod(tmp, keep_mode)
        _replace_with_retry(tmp, str(target), max_retries, initial_delay)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    fsync_dir(target.parent)


def atomic_write_text(
    path: Path | str,
    text: str,
    encoding: str = "utf-8",
    max_retries: int = STORAGE_MAX_RETRIES,
    initial_delay: float = STORAGE_INITIAL_DELAY_SECONDS,
) -> None:
    """atomic_write_bytes for text; the text is written byte for byte (no newline translation)."""
    atomic_write_bytes(path, text.encode(encoding), max_retries=max_retries, initial_delay=initial_delay)


def atomic_write_and_unlink(source_path: Path | str, target_path: Path | str, new_content: str) -> None:
    """Write ``new_content`` to ``target_path`` atomically, then remove ``source_path``.

    If the source cannot be removed the new target is removed again, so a rule never
    ends up in two places.
    """
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


# ── JSONL ─────────────────────────────────────────────────────────────────────

def _encode_rows(rows: Iterable[Dict[str, Any]]) -> bytes:
    lines = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError(f"a JSONL row must be a JSON object, got {type(row).__name__}")
        # ensure_ascii: the file stays valid UTF-8 whatever the strings hold (a lone
        # surrogate becomes an escape instead of an undecodable byte).
        lines.append(json.dumps(row, ensure_ascii=True, separators=(",", ":"), allow_nan=False))
    return "".join(line + "\n" for line in lines).encode("ascii")


def append_jsonl(path: Path | str, rows: Iterable[Dict[str, Any]]) -> int:
    """Append ``rows`` as JSON lines with one ``O_APPEND`` write and one fsync.

    Every row is serialized before anything is written, so a row that is not JSON
    serializable writes nothing (ValueError/TypeError). If the file ends in a torn line
    (no trailing newline, as a crash mid-write leaves it), a newline is written first:
    the torn bytes stay as one unreadable line and the new rows stay intact. Callers that
    need ordering or deduplication hold ``locked()``. Returns the number of rows written.
    """
    rows = list(rows)
    payload = _encode_rows(rows)
    if not rows:
        return 0
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    created = not os.path.lexists(target)
    fd = os.open(str(target), os.O_RDWR | os.O_APPEND | os.O_CREAT | _O_BINARY | _O_CLOEXEC, _NEW_FILE_MODE)
    try:
        size = os.fstat(fd).st_size
        if size:
            os.lseek(fd, size - 1, os.SEEK_SET)
            if os.read(fd, 1) != b"\n":
                payload = b"\n" + payload
        _write_all(fd, payload)
        os.fsync(fd)
    finally:
        os.close(fd)
    if created:
        fsync_dir(target.parent)
    return len(rows)


@dataclass(frozen=True)
class JsonlRead:
    """What read_jsonl found: the object rows (with their 1-based line numbers) and the rest.

    ``skipped_lines`` are complete lines that are not a UTF-8 JSON object. A final line
    without a newline that does not parse is ``torn_tail`` (a write in progress or a
    crash), not a skipped line. ``error`` is set when the file exists but cannot be read.
    """

    rows: List[Dict[str, Any]]
    line_numbers: List[int]
    skipped_lines: List[int]
    torn_tail: bool = False
    error: Optional[str] = None

    @property
    def skipped(self) -> int:
        return len(self.skipped_lines)


def _parse_line(raw: bytes) -> Optional[Dict[str, Any]]:
    try:
        value = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError, RecursionError):
        return None
    return value if isinstance(value, dict) else None


def read_jsonl(path: Path | str) -> JsonlRead:
    """Read a JSONL file; never raises for its content. A missing file reads as empty."""
    try:
        with open(path, "rb") as fh:
            data = fh.read()
    except FileNotFoundError:
        return JsonlRead([], [], [])
    except OSError as exc:
        return JsonlRead([], [], [], error=f"cannot read {path}: {exc.strerror or exc}")

    rows: List[Dict[str, Any]] = []
    numbers: List[int] = []
    skipped: List[int] = []
    torn = False
    lines = data.split(b"\n")
    last = len(lines) - 1
    for index, raw in enumerate(lines):
        if index == last and not raw:
            break  # the file ended with a newline
        raw = raw.rstrip(b"\r")
        if not raw.strip():
            continue
        row = _parse_line(raw)
        if row is not None:
            rows.append(row)
            numbers.append(index + 1)
        elif index == last:
            torn = True
        else:
            skipped.append(index + 1)
    return JsonlRead(rows, numbers, skipped, torn_tail=torn)

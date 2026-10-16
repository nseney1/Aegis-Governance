"""L0 storage: the one workspace lock, atomic file writes and JSONL I/O (ADR 0005 AD-3).

Every write of Aegis state or rule files goes through this module, so the crash and
concurrency guarantees live in one place:

- ``locked(workspace)``: the single workspace lock, ``.aegis/state/lock``. It is
  re-entrant per thread, so nested acquisition never deadlocks, and its wait is
  bounded with an error that names the lock file.
- ``shared_state_dir(workspace)``: ``<git common dir>/aegis``, the state every
  worktree of one repository shares (the events log), with the same symlink and
  outside-entry refusals, confined to the resolved common dir; ``.aegis/state`` outside
  git. ``shared_locked(workspace, name)`` holds a lock file there with the same
  primitive as ``locked``. Lock order: the workspace lock first; a shared lock is a
  leaf, so nothing else is taken while holding one (LockOrderError otherwise).
- ``state_dir(workspace)``: ``.aegis/state``, refused when it (or ``.aegis``, or any
  entry directly inside it: the ledger, the lock, a log, a backup) is a symlink or
  resolves outside the workspace, so machine-local state is never written through a
  link a commit planted (a tracked symlink is not hidden by the ``state/`` ignore
  entry). It also keeps ``state/.gitignore`` ("*"), so state never shows in
  ``git status`` even where ``.aegis/.gitignore`` lacks ``state/``.
- ``atomic_write_bytes``/``atomic_write_text``: write a temporary file next to the
  target, fsync it, then replace. An existing file keeps its mode; a new file gets
  the mode the umask gives (0o644 typically), not mkstemp's 0o600; ``mode`` sets it
  exactly (a private copy stays private).
- ``append_jsonl``: one ``O_APPEND`` write and one fsync, never through a symlink. A
  torn trailing line left by a crash is terminated first, so it cannot swallow the
  new row.
- ``read_jsonl``: decodes line by line (bytes, utf-8-sig); invalid lines are skipped
  and counted, never raised. It does not follow a symlink.
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
from typing import Any, Dict, Iterable, Iterator, List, Optional, Set

from aegis_core import gitsafe
from aegis_core.errors import AegisError, LockTimeoutError, PathTraversalError
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
    "LockOrderError",
    "LockTimeoutError",
    "append_jsonl",
    "atomic_write_and_unlink",
    "atomic_write_bytes",
    "atomic_write_text",
    "fsync_dir",
    "locked",
    "read_jsonl",
    "shared_locked",
    "shared_state_dir",
    "state_dir",
]

_O_BINARY = getattr(os, "O_BINARY", 0)
_O_CLOEXEC = getattr(os, "O_CLOEXEC", 0)
# POSIX: the open itself refuses a symlink, so a link swapped in after the lstat check
# is refused too. Windows has no O_NOFOLLOW; the lstat check is the guard there.
_O_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_O_NONBLOCK = getattr(os, "O_NONBLOCK", 0)
# A new file's permission bits before the umask: the kernel applies the umask, so no
# process-wide os.umask() round trip (which races other threads) is needed.
_NEW_FILE_MODE = 0o666


# ── The one workspace lock ───────────────────────────────────────────────────

class LockOrderError(AegisError, RuntimeError):
    """A lock was requested out of order: the workspace lock comes before any shared
    lock, and a shared lock is a leaf (two processes taking two locks in opposite
    orders would deadlock until a timeout)."""

    def __init__(self, message: str = "", code: str = "LOCK_ORDER", **kwargs: Any) -> None:
        super().__init__(message, code=code, **kwargs)


_GUARD = threading.Lock()
_THREAD_LOCKS: Dict[str, "threading.RLock"] = {}
# .keys: the lock keys this thread holds; .leaves: {lock key: path} of the shared locks among them
_HELD = threading.local()


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


def _held() -> Set[str]:
    held = getattr(_HELD, "keys", None)
    if held is None:
        held = _HELD.keys = set()
    return held


def _held_leaves() -> Dict[str, Path]:
    leaves = getattr(_HELD, "leaves", None)
    if leaves is None:
        leaves = _HELD.leaves = {}
    return leaves


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


def _timeout_error(path: Path, timeout: float, kind: str = "workspace") -> LockTimeoutError:
    return LockTimeoutError(
        f"timed out after {timeout:g}s waiting for the Aegis {kind} lock {path}: "
        "another aegis process or thread holds it",
        path=str(path),
    )


_EXTENDED_UNC, _EXTENDED = "\\\\?\\UNC\\", "\\\\?\\"


def _resolved(path: Path | str) -> str:
    """``path`` with every link resolved and without the Windows extended-length prefix.

    realpath, not Path.resolve(): it never raises (3.9 resolve raises RuntimeError on
    loops) and it resolves Windows junctions, which is_symlink() misses before 3.12.
    Windows realpath answers in the extended-length form (``\\\\?\\C:\\...``) when the
    path appears or disappears while it resolves it (another process creating
    ``.aegis/state``); that prefix is dropped.
    """
    real = os.path.realpath(path)
    if real.startswith(_EXTENDED_UNC):
        real = "\\\\" + real[len(_EXTENDED_UNC):]
    elif real.startswith(_EXTENDED):
        real = real[len(_EXTENDED):]
    return real


def _real(path: Path | str) -> str:
    """``path`` resolved (``_resolved``) in one spelling per location: normcase folds the
    case Windows ignores, so two spellings of one location compare equal."""
    return os.path.normcase(_resolved(path))


def _within(path: Path, root: Path) -> bool:
    real, base = _real(path), _real(root)
    return real == base or real.startswith(base.rstrip(os.sep) + os.sep)


def _link_error(path: Path) -> PathTraversalError:
    return PathTraversalError(
        f"refusing to use {path}: it is a symlink; aegis keeps workspace state only inside the workspace",
        path=str(path),
    )


def _outside_error(path: Path) -> PathTraversalError:
    return PathTraversalError(
        f"refusing to use {path}: it resolves outside the workspace; aegis keeps workspace "
        "state only inside the workspace",
        path=str(path),
    )


_STATE_GITIGNORE = b"# Aegis machine-local state; never committed.\n*\n"


def state_dir(workspace: Any) -> Path:
    """The workspace's ``.aegis/state`` directory, created if missing.

    Raises PathTraversalError when ``.aegis`` or ``.aegis/state`` is a symlink or
    otherwise resolves outside the workspace (nothing is created then), or when an entry
    directly inside ``.aegis/state`` is a symlink or resolves outside it (a Windows
    junction): the ledger, the lock, the logs and migration backups would be written
    wherever it points. Writes ``state/.gitignore`` ("*") when it is missing.
    """
    layout = WorkspaceLayout(Path(os.fspath(workspace)).resolve())
    for path in (layout.aegis_dir, layout.state_dir):
        if path.is_symlink():
            raise _link_error(path)
    if not _within(layout.state_dir, layout.root):  # a Windows junction is not a symlink
        raise _outside_error(layout.state_dir)
    layout.state_dir.mkdir(parents=True, exist_ok=True)
    with os.scandir(layout.state_dir) as entries:
        for entry in entries:
            if entry.is_symlink():
                raise _link_error(Path(entry.path))
            # Every entry, not only directories: a file here always resolves inside it.
            if not _within(Path(entry.path), layout.root):
                raise _outside_error(Path(entry.path))
    if not os.path.lexists(layout.state_gitignore):
        atomic_write_bytes(layout.state_gitignore, _STATE_GITIGNORE)
    return layout.state_dir


# ── Shared state: one directory for every worktree of a repository ───────────

_SHARED_DIR_NAME = "aegis"
_SHARED_DIR_MODE = 0o700


def _shared_link_error(path: Path, base: Path) -> PathTraversalError:
    return PathTraversalError(
        f"refusing to use {path}: it is a symlink; aegis keeps shared state only inside {base}",
        path=str(path),
    )


def _shared_outside_error(path: Path, base: Path) -> PathTraversalError:
    return PathTraversalError(
        f"refusing to use {path}: it resolves outside {base}; aegis keeps shared state only inside it",
        path=str(path),
    )


def _confined(directory: Path, base: Path, link_error, outside_error, entries: bool = True) -> None:
    """Refuse ``directory`` when it is a symlink, is not a directory, or resolves outside
    ``base``, and (``entries``) when an entry directly inside it is a symlink or a
    directory that resolves outside ``base``. A missing ``directory`` passes."""
    if directory.is_symlink():
        raise link_error(directory)
    if not os.path.lexists(directory):
        return
    if not _within(directory, base):  # a Windows junction is not a symlink
        raise outside_error(directory)
    if not directory.is_dir():
        raise PathTraversalError(f"refusing to use {directory}: it is not a directory", path=str(directory))
    if not entries:
        return
    with os.scandir(directory) as found:
        for entry in found:
            if entry.is_symlink():
                raise link_error(Path(entry.path))
            if entry.is_dir(follow_symlinks=False) and not _within(Path(entry.path), base):
                raise outside_error(Path(entry.path))


def shared_state_dir(workspace: Any, create: bool = True) -> Path:
    """Machine-local state every worktree of the workspace's repository shares:
    ``<git common dir>/aegis`` (realpath of ``git rev-parse --git-common-dir``, so a
    linked worktree answers the main ``.git``, never ``.git/worktrees/<name>``).

    Created mode 0o700 when ``create``; with ``create=False`` nothing is created and the
    path is returned whether or not it exists. Raises PathTraversalError (nothing is
    created) when ``<common>/aegis`` is a symlink, is not a directory or resolves outside
    the common dir, or when an entry directly inside it is a symlink or a directory that
    resolves outside it. Raises OSError when it cannot be listed or created. Outside a
    git repository, or when git cannot run, it is the workspace's ``.aegis/state`` with
    ``state_dir``'s refusals.
    """
    root = Path(os.fspath(workspace)).resolve()
    common = gitsafe.common_dir(root)
    if common is None:
        if create:
            return state_dir(root)
        layout = WorkspaceLayout(root)
        # state_dir()'s checks, without creating anything.
        _confined(layout.aegis_dir, layout.root, _link_error, _outside_error, entries=False)
        _confined(layout.state_dir, layout.root, _link_error, _outside_error)
        return layout.state_dir
    base = Path(_resolved(common))
    shared = base / _SHARED_DIR_NAME

    def link_error(path: Path) -> PathTraversalError:
        return _shared_link_error(path, base)

    def outside_error(path: Path) -> PathTraversalError:
        return _shared_outside_error(path, base)

    _confined(shared, base, link_error, outside_error)
    if create and not os.path.lexists(shared):
        try:
            shared.mkdir(mode=_SHARED_DIR_MODE)
        except FileExistsError:
            pass  # another worktree's process made it first; checked again below
        _confined(shared, base, link_error, outside_error)
    return shared


def _shared_lock_name(name: object) -> str:
    ok = (
        isinstance(name, str)
        and name.endswith(".lock")
        and name != ".lock"
        and not any(ch in name for ch in "/\\\0")
        and name not in (".", "..")
    )
    if not ok:
        raise ValueError(f"a shared lock is one file name ending in .lock, got {name!r}")
    return name  # type: ignore[return-value]


@contextmanager
def shared_locked(workspace: Any, name: str, timeout: float = LOCK_TIMEOUT_SECONDS) -> Iterator[Path]:
    """Hold the lock file ``<shared_state_dir>/<name>`` (e.g. ``events.lock``) for the block.

    The same primitive as ``locked`` (re-entrant per thread, bounded wait, the OS lock
    across processes and worktrees) on its own file, so it never waits on the workspace
    lock. It is a leaf: take it after the workspace lock, never before, and take no lock
    while holding it (LockOrderError). Raises ValueError for a ``name`` that is not one
    file name ending in ``.lock``, LockTimeoutError naming the lock file, and
    PathTraversalError when the shared state dir is not confined.
    """
    _shared_lock_name(name)
    directory = shared_state_dir(workspace)
    lock_path = directory / name
    key = os.path.join(_real(directory), name)
    with _hold(lock_path, key, timeout, shared=True) as path:
        yield path


def _open_regular(path: Path, flags: int) -> int:
    """``os.open`` that refuses a symlink at ``path`` and anything but a regular file.

    Raises PathTraversalError for a symlink (an existing one, or, on POSIX, one swapped
    in before the open) and for a FIFO, device or directory. A missing file is created
    when ``flags`` has O_CREAT.
    """
    try:
        st: Optional[os.stat_result] = os.lstat(path)
    except FileNotFoundError:
        st = None
    if st is not None and stat.S_ISLNK(st.st_mode):
        raise _link_error(path)
    if st is not None and not stat.S_ISREG(st.st_mode):
        raise PathTraversalError(f"refusing to use {path}: it is not a regular file", path=str(path))
    try:
        fd = os.open(str(path), flags | _O_NOFOLLOW | _O_BINARY | _O_CLOEXEC, _NEW_FILE_MODE)
    except OSError as exc:
        if os.path.islink(path):  # ELOOP (EMLINK on BSD): a link replaced it since the lstat
            raise _link_error(path) from exc
        raise
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise PathTraversalError(f"refusing to use {path}: it is not a regular file", path=str(path))
    except BaseException:
        os.close(fd)
        raise
    return fd


@contextmanager
def _hold(lock_path: Path, key: str, timeout: float, shared: bool) -> Iterator[Path]:
    """Hold the lock file ``lock_path`` (``key``: its one spelling) for the block:
    re-entrant per thread, a thread lock then the OS lock, bounded by ``timeout``.

    While another process holds it, the wait between tries starts at
    LOCK_RETRY_INTERVAL_SECONDS and grows by half each time, up to LOCK_MAX_BACKOFF_SECONDS.
    Raises LockTimeoutError, naming the lock file, when another thread or process holds
    it for longer than ``timeout`` seconds.

    ``shared`` marks a shared lock, which is a leaf: taking the workspace lock or another
    shared lock while this thread holds one raises LockOrderError before waiting.
    """
    held = _held()
    if key in held:
        # Re-entrant: this thread's outermost locked() holds the lock and releases it, so
        # a nested block keeps no count of its own.
        yield lock_path
        return

    leaves = _held_leaves()
    if leaves:
        holding = next(iter(leaves.values()))
        if shared:
            raise LockOrderError(
                f"lock order: a shared lock is a leaf; {lock_path} cannot be taken while holding {holding}"
            )
        raise LockOrderError(
            f"lock order: the Aegis workspace lock is taken before a shared lock, never while holding {holding}"
        )

    deadline = time.monotonic() + max(0.0, timeout)
    kind = "shared" if shared else "workspace"
    thread_lock = _thread_lock(key)
    if not thread_lock.acquire(timeout=max(0.0, timeout)):
        raise _timeout_error(lock_path, timeout, kind)
    fd = None
    try:
        fd = _open_regular(lock_path, os.O_RDWR | os.O_CREAT)
        interval = LOCK_RETRY_INTERVAL_SECONDS
        while not _try_os_lock(fd):
            if time.monotonic() >= deadline:
                raise _timeout_error(lock_path, timeout, kind)
            time.sleep(interval)
            interval = min(interval * 1.5, LOCK_MAX_BACKOFF_SECONDS)
        held.add(key)
        if shared:
            leaves[key] = lock_path
        try:
            yield lock_path
        finally:
            held.discard(key)
            leaves.pop(key, None)
            _os_unlock(fd)
    finally:
        if fd is not None:
            os.close(fd)
        thread_lock.release()


@contextmanager
def locked(workspace: Any, timeout: float = LOCK_TIMEOUT_SECONDS) -> Iterator[Path]:
    """Hold the workspace lock (``.aegis/state/lock``) for the duration of the block.

    ``workspace`` is a Workspace, a path or a string; every spelling of one root shares
    one lock. Re-entrant per thread: a nested ``locked()`` in the thread that holds it
    returns immediately. Raises LockTimeoutError, naming the lock file, when another
    thread or process holds it for longer than ``timeout`` seconds, PathTraversalError
    when the state directory is not confined (``state_dir``), and LockOrderError when
    this thread holds a shared lock (``shared_locked``).
    """
    layout = WorkspaceLayout(Path(os.fspath(workspace)).resolve())
    state = state_dir(layout.root)
    lock_path = layout.lock_file
    # state_dir() confined the directory; the lock file itself is opened by its own
    # name, never through what a link named "lock" points at. One spelling per location:
    # two keys for one lock file would make a nested locked() wait on itself.
    key = os.path.join(_real(state), lock_path.name)
    with _hold(lock_path, key, timeout, shared=False) as path:
        yield path


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
    mode: Optional[int] = None,
) -> None:
    """Replace ``path`` with ``data`` atomically: readers see the old or the new bytes.

    The parent directory is created if missing. ``mode`` sets the permission bits
    exactly (the umask does not apply); without it an existing file keeps its bits and
    a new one gets ``0o666 & ~umask``. The temporary file is removed on failure.
    """
    target = Path(path).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    keep_mode: Optional[int] = None if mode is None else stat.S_IMODE(mode)
    if keep_mode is None:
        try:
            keep_mode = stat.S_IMODE(os.stat(target).st_mode)
        except FileNotFoundError:
            pass

    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | _O_BINARY | _O_CLOEXEC
    # A file that ends with set bits starts private, so it is never looser in between.
    create_mode = _NEW_FILE_MODE if keep_mode is None else 0o600
    while True:
        tmp = str(target.parent / f".{target.name}.{secrets.token_hex(6)}.tmp")
        try:
            fd = os.open(tmp, flags, create_mode)
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
    serializable writes nothing (ValueError/TypeError). A symlink at ``path``, dangling
    or not, raises PathTraversalError and nothing is written. If the file ends in a torn line
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
    fd = _open_regular(target, os.O_RDWR | os.O_APPEND | os.O_CREAT)
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


def _parse_line(raw: bytes, errors: str) -> Optional[Dict[str, Any]]:
    try:
        value = json.loads(raw.decode("utf-8-sig", errors))
    except (UnicodeDecodeError, ValueError, RecursionError):
        return None
    return value if isinstance(value, dict) else None


def read_jsonl(path: Path | str, errors: str = "strict") -> JsonlRead:
    """Read a JSONL file; never raises for its content. A missing file reads as empty.

    ``errors`` is the UTF-8 error handler: ``"surrogatepass"`` reads what v3 wrote with
    it (a lone surrogate from a non-UTF-8 file name). A symlink, or anything but a
    regular file, is not read: ``error`` says why.
    """
    try:
        # O_NONBLOCK: opening a FIFO for reading would otherwise wait for a writer.
        fd = _open_regular(Path(path), os.O_RDONLY | _O_NONBLOCK)
    except FileNotFoundError:
        return JsonlRead([], [], [])
    except PathTraversalError as exc:
        return JsonlRead([], [], [], error=f"cannot read {path}: {exc}")
    except OSError as exc:
        return JsonlRead([], [], [], error=f"cannot read {path}: {exc.strerror or exc}")
    try:
        with os.fdopen(fd, "rb") as fh:
            data = fh.read()
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
        row = _parse_line(raw, errors)
        if row is not None:
            rows.append(row)
            numbers.append(index + 1)
        elif index == last:
            torn = True
        else:
            skipped.append(index + 1)
    return JsonlRead(rows, numbers, skipped, torn_tail=torn)

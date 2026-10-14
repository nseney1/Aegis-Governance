"""soma_core.locking — Cross-platform transactional resource locking.

Provides thread-safe and process-safe transactional locks with timeout fences
across Linux, macOS, and native Windows.
"""
from __future__ import annotations

import os
import sys
import time
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Generator, Optional

try:
    import fcntl
except ImportError:
    fcntl = None

try:
    import msvcrt
except ImportError:
    msvcrt = None

LOCK_DIRNAME = "locks"
_THREAD_LOCKS: dict[str, threading.RLock] = {}
_THREAD_LOCKS_GUARD = threading.Lock()
_THREAD_STATE = threading.local()



from soma_core.errors import LockTimeoutError


def _get_thread_lock(lock_path: str) -> threading.RLock:
    norm = os.path.abspath(lock_path)
    with _THREAD_LOCKS_GUARD:
        lock = _THREAD_LOCKS.get(norm)
        if lock is None:
            lock = threading.RLock()
            _THREAD_LOCKS[norm] = lock
        return lock


def _acquire_os_lock(fileno: int, timeout_sec: float) -> bool:
    start_time = time.monotonic()
    retry_interval = 0.01

    while True:
        if fcntl is not None:
            try:
                fcntl.flock(fileno, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return True
            except (BlockingIOError, OSError):
                pass
        elif msvcrt is not None:
            try:
                os.lseek(fileno, 0, os.SEEK_SET)
                msvcrt.locking(fileno, msvcrt.LK_NBLCK, 1)
                return True
            except OSError:
                pass
        else:
            # Fallback: process-local thread lock is held, OS lock unavailable
            return True

        if time.monotonic() - start_time >= timeout_sec:
            return False

        time.sleep(retry_interval)
        retry_interval = min(retry_interval * 1.5, 0.05)


def _release_os_lock(fileno: int) -> None:
    if fcntl is not None:
        try:
            fcntl.flock(fileno, fcntl.LOCK_UN)
        except OSError:
            pass
    elif msvcrt is not None:
        try:
            os.lseek(fileno, 0, os.SEEK_SET)
            msvcrt.locking(fileno, msvcrt.LK_UNLCK, 1)
        except OSError:
            pass


@contextmanager
def workspace_lock(
    workspace: str | Path,
    resource: str,
    timeout_sec: float = 5.0,
) -> Generator[Path, None, None]:
    """Acquire a cross-process and thread-safe lock for a workspace resource.

    Args:
        workspace: Path to governed project workspace.
        resource: Logical resource name (e.g. 'cells', 'evidence', 'jobs').
        timeout_sec: Maximum duration in seconds to wait before raising LockTimeoutError.

    Yields:
        Path to the active lock file.
    """
    ws = Path(workspace).resolve()
    if (ws / ".aegis").is_dir():
        locks_dir = ws / ".aegis" / LOCK_DIRNAME
    else:
        locks_dir = ws / ".soma" / LOCK_DIRNAME
    locks_dir.mkdir(parents=True, exist_ok=True)
    lock_file = locks_dir / f"{resource}.lock"
    str_path = str(lock_file)

    thread_lock = _get_thread_lock(str_path)
    start_time = time.monotonic()

    # Acquire in-process thread lock first
    acquired_thread = thread_lock.acquire(timeout=timeout_sec)
    if not acquired_thread:
        raise LockTimeoutError(
            f"Could not acquire lock for '{resource}' within {timeout_sec:.2f}s (thread contention)",
            resource=resource,
        )

    norm = os.path.abspath(str_path)
    held = getattr(_THREAD_STATE, "held_locks", None)
    if held is None:
        held = {}
        _THREAD_STATE.held_locks = held

    if norm in held:
        held[norm] += 1
        try:
            yield lock_file
        finally:
            held[norm] -= 1
            if held[norm] == 0:
                del held[norm]
            thread_lock.release()
        return

    fd = None
    acquired_os = False
    try:
        remaining_timeout = max(0.01, timeout_sec - (time.monotonic() - start_time))
        fd = os.open(str_path, os.O_CREAT | os.O_RDWR, 0o600)
        acquired_os = _acquire_os_lock(fd, remaining_timeout)
        if not acquired_os:
            raise LockTimeoutError(
                f"Could not acquire lock for '{resource}' within {timeout_sec:.2f}s (process contention)",
                resource=resource,
            )
        held[norm] = 1
        yield lock_file
    finally:
        held.pop(norm, None)
        if fd is not None:
            try:
                if acquired_os:
                    _release_os_lock(fd)
            finally:
                os.close(fd)
        thread_lock.release()


__all__ = [
    "LOCK_DIRNAME",
    "LockTimeoutError",
    "workspace_lock",
]


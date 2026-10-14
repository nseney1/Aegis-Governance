"""Tests for cross-platform transactional workspace locking (soma_core.locking)."""
from __future__ import annotations

import os
import sys
import time
import threading
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

import pytest

from soma_core.locking import (
    workspace_lock,
    LockTimeoutError,
    LOCK_DIRNAME,
)


class TestWorkspaceLock:
    """Test suite for transactional file and resource locking."""

    def test_basic_acquire_and_release(self, tmp_path: Path):
        """Lock can be acquired and released cleanly."""
        acquired = False
        with workspace_lock(tmp_path, "cells", timeout_sec=1.0):
            acquired = True
            lock_file = tmp_path / ".soma" / LOCK_DIRNAME / "cells.lock"
            assert lock_file.exists()
        assert acquired

    def test_timeout_when_lock_held(self, tmp_path: Path):
        """Holding a lock blocks a second attempt until timeout expires."""
        started_event = threading.Event()
        stop_event = threading.Event()

        def _holder():
            with workspace_lock(tmp_path, "test_resource", timeout_sec=2.0):
                started_event.set()
                stop_event.wait(timeout=3.0)

        t = threading.Thread(target=_holder)
        t.start()
        try:
            assert started_event.wait(timeout=2.0)
            with pytest.raises(LockTimeoutError, match="Could not acquire lock for 'test_resource'"):
                with workspace_lock(tmp_path, "test_resource", timeout_sec=0.2):
                    pytest.fail("Should have timed out")
        finally:
            stop_event.set()
            t.join()

    def test_concurrent_counter_integrity(self, tmp_path: Path):
        """Multiple threads modifying a file under workspace_lock produce no data loss."""
        counter_file = tmp_path / "counter.txt"
        counter_file.write_text("0", encoding="utf-8")
        num_increments = 50

        def _increment():
            for _ in range(num_increments):
                with workspace_lock(tmp_path, "counter", timeout_sec=5.0):
                    val = int(counter_file.read_text(encoding="utf-8").strip())
                    time.sleep(0.001)  # Artificially expand race condition window
                    counter_file.write_text(str(val + 1), encoding="utf-8")

        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = [executor.submit(_increment) for _ in range(4)]
            for f in futures:
                f.result()

        final_val = int(counter_file.read_text(encoding="utf-8").strip())
        assert final_val == 4 * num_increments

    def test_different_resources_do_not_block_each_other(self, tmp_path: Path):
        """Locks on different resources (e.g. 'cells' and 'evidence') do not contend."""
        with workspace_lock(tmp_path, "cells", timeout_sec=1.0):
            with workspace_lock(tmp_path, "evidence", timeout_sec=1.0):
                assert True

    def test_reentrant_acquire_same_thread(self, tmp_path: Path):
        """Reentrant lock acquisition within the same thread succeeds immediately."""
        with workspace_lock(tmp_path, "cells", timeout_sec=1.0) as lock1:
            with workspace_lock(tmp_path, "cells", timeout_sec=1.0) as lock2:
                assert lock1 == lock2

    def test_unacquired_lock_release_not_called_on_timeout(self, tmp_path: Path, monkeypatch):
        """If OS lock acquisition fails, _release_os_lock must not be called (guards Windows CRT)."""
        import soma_core.locking as locking_mod

        release_called = False

        def fake_acquire(fd, timeout):
            return False

        def fake_release(fd):
            nonlocal release_called
            release_called = True

        monkeypatch.setattr(locking_mod, "_acquire_os_lock", fake_acquire)
        monkeypatch.setattr(locking_mod, "_release_os_lock", fake_release)

        with pytest.raises(LockTimeoutError):
            with workspace_lock(tmp_path, "res_fail", timeout_sec=0.05):
                pass

        assert not release_called

    def test_aegis_workspace_lock_uses_aegis_locks(self, tmp_path: Path):
        """Lock in an .aegis workspace creates locks under .aegis/locks."""
        (tmp_path / ".aegis").mkdir()
        with workspace_lock(tmp_path, "rules", timeout_sec=1.0):
            lock_file = tmp_path / ".aegis" / LOCK_DIRNAME / "rules.lock"
            assert lock_file.exists()
            assert not (tmp_path / ".soma" / LOCK_DIRNAME / "rules.lock").exists()

    def test_soma_workspace_lock_fallback(self, tmp_path: Path):
        """Lock in a non-.aegis workspace creates locks under .soma/locks."""
        with workspace_lock(tmp_path, "cells", timeout_sec=1.0):
            lock_file = tmp_path / ".soma" / LOCK_DIRNAME / "cells.lock"
            assert lock_file.exists()
            assert not (tmp_path / ".aegis" / LOCK_DIRNAME / "cells.lock").exists()


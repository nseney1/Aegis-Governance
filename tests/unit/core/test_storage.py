"""Unit tests for aegis_core.storage atomic operations and retry backoff."""
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from aegis_core.storage import atomic_write_text, atomic_write_bytes


def test_atomic_write_text_creates_file(tmp_path: Path):
    target = tmp_path / "subdir" / "test.txt"
    atomic_write_text(target, "hello world\n")
    assert target.exists()
    assert target.read_text(encoding="utf-8") == "hello world\n"


def test_atomic_write_text_overwrites_existing(tmp_path: Path):
    target = tmp_path / "test.txt"
    target.write_text("initial content", encoding="utf-8")
    atomic_write_text(target, "updated content")
    assert target.read_text(encoding="utf-8") == "updated content"


def test_atomic_write_bytes(tmp_path: Path):
    target = tmp_path / "binary.dat"
    data = b"\x00\x01\x02\xff"
    atomic_write_bytes(target, data)
    assert target.read_bytes() == data


def test_atomic_write_retries_on_windows_permission_error(tmp_path: Path):
    target = tmp_path / "locked.txt"
    attempts = 0

    real_replace = os.replace

    def flaky_replace(src, dst):
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            # Simulate Windows WinError 32 ERROR_SHARING_VIOLATION
            err = PermissionError("[WinError 32] The process cannot access the file")
            err.winerror = 32
            raise err
        return real_replace(src, dst)

    with patch("os.replace", side_effect=flaky_replace):
        atomic_write_text(target, "eventually written", initial_delay=0.001)

    assert attempts == 3
    assert target.read_text(encoding="utf-8") == "eventually written"


def test_atomic_write_cleans_up_temp_on_failure(tmp_path: Path):
    target = tmp_path / "fail.txt"

    def fail_replace(src, dst):
        raise RuntimeError("Disk explosion")

    with patch("os.replace", side_effect=fail_replace):
        with pytest.raises(RuntimeError, match="Disk explosion"):
            atomic_write_text(target, "doomed", initial_delay=0.001)

    # No leftover .tmp files
    tmp_files = list(tmp_path.glob(".*.tmp")) + list(tmp_path.glob("*.tmp"))
    assert tmp_files == []


def test_atomic_write_retries_up_to_eight_times(tmp_path: Path):
    from aegis_core.storage import atomic_write_text

    target = tmp_path / "retry8.txt"
    attempts = 0
    real_replace = os.replace

    def flaky_replace_seven_times(src, dst):
        nonlocal attempts
        attempts += 1
        if attempts < 8:
            raise PermissionError("[WinError 32] Sharing violation")
        return real_replace(src, dst)

    with patch("os.replace", side_effect=flaky_replace_seven_times):
        atomic_write_text(target, "success on 8th attempt", initial_delay=0.0001)

    assert attempts == 8
    assert target.read_text(encoding="utf-8") == "success on 8th attempt"

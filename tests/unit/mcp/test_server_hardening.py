"""The MCP server marks itself non-dumpable on Linux (v4.3 T1 hardening): same-uid siblings
cannot read its memory or inject through /proc/<pid>/fd, whatever Yama says."""
from __future__ import annotations

import subprocess
import sys

import pytest

from aegis_mcp import server

PR_GET_DUMPABLE = 3
linux_only = pytest.mark.skipif(not sys.platform.startswith("linux"), reason="prctl is Linux")


@linux_only
def test_harden_process_clears_the_dumpable_flag_in_a_fresh_process():
    code = (
        "import ctypes\n"
        "from aegis_mcp import server\n"
        "libc = ctypes.CDLL(None, use_errno=True)\n"
        f"before = libc.prctl({PR_GET_DUMPABLE}, 0, 0, 0, 0)\n"
        "assert server.harden_process() is True\n"
        f"print(before, libc.prctl({PR_GET_DUMPABLE}, 0, 0, 0, 0))\n"
    )
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    assert done.stdout.split() == ["1", "0"]


def test_harden_process_is_a_no_op_off_linux(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    assert server.harden_process() is False


@linux_only
def test_a_failing_prctl_never_stops_the_server(monkeypatch):
    class Broken:
        def prctl(self, *_args):
            return -1

    monkeypatch.setattr("ctypes.CDLL", lambda *a, **k: Broken())
    assert server.harden_process() is False


@linux_only
def test_a_missing_libc_never_stops_the_server(monkeypatch):
    def boom(*_a, **_k):
        raise OSError("no libc")

    monkeypatch.setattr("ctypes.CDLL", boom)
    assert server.harden_process() is False


def test_the_stdio_server_hardens_the_process_before_serving(monkeypatch):
    calls = []
    monkeypatch.setattr(server, "harden_process", lambda: calls.append("hardened") or True)
    monkeypatch.setattr(sys, "stdin", iter(()))
    assert server.run_stdio_server() == 0
    assert calls == ["hardened"]

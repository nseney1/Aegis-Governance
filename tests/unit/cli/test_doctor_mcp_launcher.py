"""`soma doctor` MCP launcher check (C1).

MCP configs keep `"command": "python3"`. On Windows `python3` on PATH is often
the Microsoft Store App Installer stub: it exits 49 (or prints a Store message
with no output) instead of running Python, and the MCP server silently never
starts. Doctor resolves `python3` from PATH exactly as the host would and says
which of four states applies. Stubs live in a fake PATH directory.
"""
import os
import sys

import pytest

from aegis_cli.doctor import _check_mcp_launcher, probe_mcp_launcher

pytestmark = pytest.mark.skipif(os.name == "nt", reason="sh stubs need POSIX exec")


def make_stub(directory, body):
    directory.mkdir(parents=True, exist_ok=True)
    stub = directory / "python3"
    stub.write_text("#!/bin/sh\n" + body, encoding="utf-8")
    stub.chmod(0o755)
    return stub


def test_working_python_with_soma_mcp(tmp_path):
    d = tmp_path / "bin"
    make_stub(d, 'case "$*" in *aegis_mcp*) exit 0;; esac\necho 3\n')
    status, detail = probe_mcp_launcher(str(d))
    assert status == "ok", detail


def test_python3_missing(tmp_path):
    (tmp_path / "empty").mkdir()
    status, _ = probe_mcp_launcher(str(tmp_path / "empty"))
    assert status == "missing"


def test_store_stub_exit_49(tmp_path):
    d = tmp_path / "bin"
    make_stub(d, "exit 49\n")
    status, _ = probe_mcp_launcher(str(d))
    assert status == "store_stub"


def test_store_stub_message_without_output(tmp_path):
    d = tmp_path / "bin"
    make_stub(d, 'echo "Python was not found; run without arguments to install '
                 'from the Microsoft Store, or disable this shortcut" >&2\nexit 9009\n')
    status, _ = probe_mcp_launcher(str(d))
    assert status == "store_stub"


def test_soma_mcp_not_importable(tmp_path):
    d = tmp_path / "bin"
    make_stub(d, 'case "$*" in *aegis_mcp*) exit 1;; esac\necho 3\n')
    status, _ = probe_mcp_launcher(str(d))
    assert status == "no_aegis_mcp"


def test_broken_interpreter(tmp_path):
    d = tmp_path / "bin"
    make_stub(d, "echo boom >&2\nexit 2\n")
    status, _ = probe_mcp_launcher(str(d))
    assert status == "broken"


def test_hanging_interpreter_times_out(tmp_path):
    d = tmp_path / "bin"
    make_stub(d, "sleep 30\n")
    status, detail = probe_mcp_launcher(str(d), timeout=0.5)
    assert status == "broken" and "timed out" in detail


def test_probe_uses_isolated_flags(tmp_path):
    d = tmp_path / "bin"
    log = tmp_path / "args.log"
    make_stub(d, f'echo "$*" >> "{log}"\ncase "$*" in *aegis_mcp*) exit 0;; esac\necho 3\n')
    probe_mcp_launcher(str(d))
    calls = log.read_text(encoding="utf-8").splitlines()
    assert calls[0].startswith("-I -S -c"), calls
    assert "aegis_mcp" in calls[1] and "-I" not in calls[1].split(), calls


def test_store_stub_report_names_the_fix(tmp_path, capsys):
    d = tmp_path / "bin"
    make_stub(d, "exit 49\n")
    _check_mcp_launcher(path_env=str(d))
    out = capsys.readouterr().out
    assert "App execution aliases" in out
    assert "python.org" in out


def test_no_soma_mcp_report_gives_pip_guidance(tmp_path, capsys):
    d = tmp_path / "bin"
    make_stub(d, 'case "$*" in *aegis_mcp*) exit 1;; esac\necho 3\n')
    _check_mcp_launcher(path_env=str(d))
    assert "pip install" in capsys.readouterr().out

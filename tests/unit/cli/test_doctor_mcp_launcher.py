"""`aegis doctor` MCP launcher check (release review: packaging and seams findings).

Doctor reports the command `aegis init --host` registers from this install (the absolute
aegis-mcp script, else this interpreter in isolated mode) and compares it with the command
each host has registered. It runs neither: a registered argv comes from a file the user's
hosts keep, and one that uses ``-m`` or is not absolute is reported as an unsafe
registration with the command that replaces it. Stubs write a marker if anything runs them.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from aegis_cli import pathcheck
from aegis_cli.doctor import _check_mcp_launcher, probe_mcp_launcher
from aegis_cli.install_hosts import MCP_RUNNER

EXE = ".exe" if os.name == "nt" else ""


def stub(directory: Path, name: str, marker: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / (name + EXE)
    path.write_text(f'#!/bin/sh\necho ran >> "{marker}"\n', encoding="utf-8")
    path.chmod(0o755)
    return path


@pytest.fixture(autouse=True)
def no_interpreter_scripts(monkeypatch):
    """The sysconfig scripts directories of the interpreter running the tests may hold a
    real aegis-mcp; each test says which directories exist instead."""
    monkeypatch.setattr(pathcheck, "default_candidates", lambda: [])


def check(capsys, **kw) -> tuple:
    ok = _check_mcp_launcher(**kw)
    return ok, capsys.readouterr().out


def test_the_aegis_mcp_on_path_is_what_init_registers_and_it_is_not_run(tmp_path, capsys):
    marker = tmp_path / "ran"
    exe = stub(tmp_path / "bin", "aegis-mcp", marker)
    ok, out = check(capsys, path_env=str(tmp_path / "bin"))
    assert ok is True
    assert f"✅ MCP launcher: {exe}" in out and "what aegis init --host registers" in out
    assert not marker.exists()


def test_the_script_installed_with_this_interpreter_is_next(tmp_path, capsys, monkeypatch):
    marker = tmp_path / "ran"
    exe = stub(tmp_path / "scripts", "aegis-mcp", marker)
    monkeypatch.setattr(pathcheck, "default_candidates", lambda: [str(tmp_path / "scripts")])
    ok, out = check(capsys, path_env=str(tmp_path / "empty"))
    assert ok is True and f"MCP launcher: {exe}" in out
    assert not marker.exists()


def test_without_any_aegis_mcp_this_interpreter_runs_isolated(tmp_path, capsys):
    command, problems = probe_mcp_launcher(str(tmp_path / "empty"))
    assert command[:3] == [sys.executable, "-I", "-c"] and "-m" not in command
    assert problems == []
    ok, out = check(capsys, path_env=str(tmp_path / "empty"))
    assert ok is True and "isolated mode" in out
    # The v3 wording and remedy are gone: nothing is installed for a PATH python3.
    assert "python3 -m aegis_mcp" not in out and "pip install" not in out


@pytest.mark.parametrize("argv, why", [
    (["{py}", "-m", "aegis_mcp"], "it runs -m"),
    (["python3", "-m", "aegis_mcp"], "not an absolute path"),
    (["{py}", "-c", "from aegis_mcp.server import main; main()"], "-c without -I"),
])
def test_a_registration_that_imports_from_the_start_directory_is_unsafe_and_never_run(
        tmp_path, capsys, argv, why):
    marker = tmp_path / "ran"
    py = stub(tmp_path / "pybin", "python3", marker)
    stub(tmp_path / "bin", "aegis-mcp", marker)
    argv = [a.format(py=py) for a in argv]
    ok, out = check(capsys, path_env=str(tmp_path / "bin"), registered=[("codex-cli", argv)])
    assert ok is False
    assert "codex-cli" in out and "unsafe registration" in out and why in out
    assert "re-run aegis init --host codex-cli" in out
    assert not marker.exists()


def test_a_registered_command_that_is_gone_is_reported(tmp_path, capsys):
    marker = tmp_path / "ran"
    stub(tmp_path / "bin", "aegis-mcp", marker)
    gone = str(tmp_path / "old-venv" / "bin" / ("aegis-mcp" + EXE))
    ok, out = check(capsys, path_env=str(tmp_path / "bin"), registered=[("claude-code", [gone])])
    assert ok is False
    assert f"claude-code starts {gone}, which does not exist" in out and "re-run aegis init --host claude-code" in out


def test_a_registered_runner_whose_install_is_gone_is_reported(tmp_path, capsys):
    gone = str(tmp_path / "removed-site-packages")
    ok, out = check(capsys, path_env=str(tmp_path / "empty"),
                    registered=[("antigravity", [sys.executable, "-I", "-c", MCP_RUNNER, gone])])
    assert ok is False
    assert f"no aegis_mcp in {gone}" in out and "re-run aegis init --host antigravity" in out


def test_a_registration_from_another_install_is_reported(tmp_path, capsys):
    marker = tmp_path / "ran"
    current = stub(tmp_path / "bin", "aegis-mcp", marker)
    other = stub(tmp_path / "pipx" / "bin", "aegis-mcp", marker)
    ok, out = check(capsys, path_env=str(tmp_path / "bin"), registered=[("codex-cli", [str(other)])])
    assert ok is False
    assert f"codex-cli starts {other}, not this install's {current}" in out
    assert "re-run aegis init --host codex-cli" in out
    assert not marker.exists()


def test_registrations_of_this_install_pass_and_are_named(tmp_path, capsys):
    marker = tmp_path / "ran"
    exe = stub(tmp_path / "bin", "aegis-mcp", marker)
    ok, out = check(capsys, path_env=str(tmp_path / "bin"),
                    registered=[("codex-cli", [str(exe)]), ("claude-code", [str(exe)])])
    assert ok is True
    assert "registered for codex-cli, claude-code" in out
    assert not marker.exists()


def test_an_aegis_mcp_inside_the_workspace_is_named_as_such(tmp_path, capsys):
    ws = tmp_path / "ws"
    exe = stub(ws / ".venv" / "bin", "aegis-mcp", tmp_path / "ran")
    ok, out = check(capsys, path_env=str(ws / ".venv" / "bin"), workspace=ws)
    assert ok is True and f"{exe}, inside the workspace" in out

"""Tests for soma doctor health checks."""
from __future__ import annotations

import argparse
import os
import sys
from unittest.mock import patch

import pytest

from aegis_cli.doctor import (
    _check_cli_resolvable,
    _check_python_version,
    _check_zero_dependencies,
    run_doctor,
)


# ── Individual check tests ──────────────────────────────────────────────────


def test_doctor_python_version_passes():
    """On any 3.9+ interpreter this must pass."""
    assert sys.version_info >= (3, 9), "Test suite requires Python ≥ 3.9"
    assert _check_python_version() is True


def test_doctor_zero_dependencies_check():
    """Zero-dependency frontmatter engine should be operational in test environment."""
    assert _check_zero_dependencies() is True


# ── Integration: full run_doctor ─────────────────────────────────────────────


def test_doctor_returns_zero_in_valid_env(tmp_path, monkeypatch):
    """run_doctor returns 0 when every check is mocked to pass."""
    # Set up a fake project with a recognized platform and evidence dir
    (tmp_path / ".gemini").mkdir()
    evidence = tmp_path / ".aegis" / "evidence"
    evidence.mkdir(parents=True)

    # Fake rules directory with at least one .md file
    rules_dir = tmp_path / "rules"
    rules_dir.mkdir()
    (rules_dir / "example.md").write_text("# rule")

    monkeypatch.chdir(tmp_path)

    # Mock get_rules_dir to return our fake rules dir
    with patch("aegis_cli.doctor.shutil.which", return_value="/usr/local/bin/soma"):
        with patch(
            "aegis_cli.init.get_rules_dir",
            return_value=rules_dir,
        ):
            args = argparse.Namespace()
            result = run_doctor(args)

    assert result == 0


def test_doctor_returns_one_on_failure(tmp_path, monkeypatch):
    """Monkeypatch sys.version_info to (3, 8) and verify exit code 1."""
    # Even with a valid environment, a failing Python version check → exit 1
    (tmp_path / ".gemini").mkdir()
    evidence = tmp_path / ".aegis" / "evidence"
    evidence.mkdir(parents=True)

    rules_dir = tmp_path / "rules"
    rules_dir.mkdir()
    (rules_dir / "example.md").write_text("# rule")

    monkeypatch.chdir(tmp_path)

    from collections import namedtuple
    _VersionInfo = namedtuple("version_info", "major minor micro releaselevel serial")
    fake_version = _VersionInfo(3, 8, 0, "final", 0)

    monkeypatch.setattr("aegis_cli.doctor.sys.version_info", fake_version)
    with patch("aegis_cli.doctor.shutil.which", return_value="/usr/local/bin/soma"), \
         patch("aegis_cli.init.get_rules_dir", return_value=rules_dir):
        args = argparse.Namespace()
        result = run_doctor(args)

    assert result == 1


# ── BUG-041: CLI not on PATH ─────────────────────────────────────────────────


@pytest.mark.skipif(os.name == "nt", reason="POSIX shell remedy; Windows path covered in test_pathcheck")
def test_cli_check_prints_zsh_remedy_when_unresolvable(tmp_path, monkeypatch, capsys):
    bindir = tmp_path / ".local" / "bin"
    bindir.mkdir(parents=True)
    (bindir / "soma").write_text("#!/bin/sh\n")
    monkeypatch.setenv("SHELL", "/usr/bin/zsh")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    monkeypatch.delenv("ZDOTDIR", raising=False)
    monkeypatch.setattr("aegis_cli.pathcheck.default_candidates", lambda: [str(bindir)])
    monkeypatch.setattr("aegis_cli.pathcheck.sys.platform", "linux")
    with patch("aegis_cli.doctor.shutil.which", return_value=None), \
         patch("aegis_cli.pathcheck.shutil.which", return_value=None):
        assert _check_cli_resolvable() is False
    out = capsys.readouterr().out
    assert "aegis CLI not found on PATH" in out
    assert "~/.zshrc" in out
    assert "python3 -m soma_cli" in out


def test_cli_check_silent_remedy_when_resolvable(capsys):
    with patch("aegis_cli.doctor.shutil.which", return_value="/usr/local/bin/aegis"):
        assert _check_cli_resolvable() is True
    out = capsys.readouterr().out
    assert "export PATH" not in out


def test_check_ast_drivers_native_when_no_slots(tmp_path, capsys):
    from aegis_cli.doctor import _check_ast_drivers
    assert _check_ast_drivers(tmp_path) is True
    out = capsys.readouterr().out
    assert "native Python stdlib" in out

    # config.json exists, but enables no packaged driver
    config = tmp_path / ".aegis" / "config.json"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text('{"v": 1, "hosts": ["codex-cli"]}')
    assert _check_ast_drivers(tmp_path) is True
    out2 = capsys.readouterr().out
    assert "native Python stdlib" in out2


def test_check_ast_drivers_with_valid_and_invalid_slots(tmp_path, capsys, monkeypatch):
    from aegis_cli.doctor import _check_ast_drivers
    home = tmp_path / "home"
    (home / ".aegis").mkdir(parents=True)
    (home / ".aegis" / "config.json").write_text('{"v": 1, "drivers": {"ts": "node runner.js"}}')
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    ws = tmp_path / "ws"
    ws.mkdir()
    tmp_path = ws

    # With both binaries resolvable
    with patch("aegis_cli.doctor.shutil.which", side_effect=lambda cmd: f"/bin/{cmd}"):
        assert _check_ast_drivers(tmp_path) is True
    out = capsys.readouterr().out
    assert "AST driver (.ts): node resolvable" in out

    # With missing binary
    with patch("aegis_cli.doctor.shutil.which", return_value=None):
        assert _check_ast_drivers(tmp_path) is False
    out = capsys.readouterr().out
    assert "not found on PATH" in out

    # An unreadable config is reported, not a crash
    (tmp_path / ".aegis").mkdir()
    (tmp_path / ".aegis" / "config.json").write_text("{corrupt")
    assert _check_ast_drivers(tmp_path) is False
    assert ".aegis/config.json is not valid JSON" in capsys.readouterr().out


def test_doctor_warns_when_ast_drivers_unresolvable(tmp_path, monkeypatch, capsys):
    (tmp_path / ".gemini").mkdir()
    evidence = tmp_path / ".aegis" / "evidence"
    evidence.mkdir(parents=True)
    rules_dir = tmp_path / "rules"
    rules_dir.mkdir()
    (rules_dir / "example.md").write_text("# rule")

    # H5: a repo config can only opt in to a packaged driver (here ts_ast.js, which
    # needs node); an arbitrary repo-defined driver command is dropped before doctor sees it.
    config = tmp_path / ".aegis" / "config.json"
    config.write_text('{"v": 1, "ast": {"packaged_drivers": ["ts"]}, "drivers": {"ts": "evil"}}')

    monkeypatch.chdir(tmp_path)
    with patch("aegis_cli.doctor.shutil.which", side_effect=lambda cmd, **kw: "/usr/local/bin/aegis" if cmd in ("aegis", "soma") else None), \
         patch("aegis_cli.init.get_rules_dir", return_value=rules_dir):
        args = argparse.Namespace()
        result = run_doctor(args)
    assert result == 0
    captured = capsys.readouterr().out
    assert "AST driver (.ts): executable 'node' not found on PATH" in captured


def test_check_ast_drivers_missing_driver_warns_and_fixes(tmp_path, capsys):
    from aegis_cli.doctor import _check_ast_drivers
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "index.ts").write_text("const x = 1;")

    # Without fix flag: warns and returns False
    assert _check_ast_drivers(tmp_path, fix=False) is False
    out = capsys.readouterr().out
    assert "unconfigured driver for detected source extension(s): .ts" in out
    assert "Run 'aegis doctor --fix' to provision" in out

    # With fix flag: auto-provisions and returns True
    assert _check_ast_drivers(tmp_path, fix=True) is True
    out = capsys.readouterr().out
    assert "Fixed: enabled the packaged AST drivers in .aegis/config.json for .ts" in out
    assert (tmp_path / ".aegis" / "config.json").is_file()


def test_check_ast_drivers_missing_extension_slot_warns_and_fixes(tmp_path, capsys):
    from aegis_cli.doctor import _check_ast_drivers
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.rs").write_text("fn main() {}")

    # Existing config enables ts but not rs
    config = tmp_path / ".aegis" / "config.json"
    config.parent.mkdir(parents=True)
    config.write_text('{"v": 1, "ast": {"packaged_drivers": ["ts"]}}')

    # Without fix: warns
    assert _check_ast_drivers(tmp_path, fix=False) is False
    out = capsys.readouterr().out
    assert "unconfigured driver for detected source extension(s): .rs" in out

    # With fix: provisions missing slot
    assert _check_ast_drivers(tmp_path, fix=True) is True
    out = capsys.readouterr().out
    assert "Fixed: enabled the packaged AST drivers in .aegis/config.json for .rs" in out
    assert '"rs"' in config.read_text()


def test_run_doctor_with_fix_flag(tmp_path, monkeypatch, capsys):
    (tmp_path / ".gemini").mkdir()
    evidence = tmp_path / ".aegis" / "evidence"
    evidence.mkdir(parents=True)
    rules_dir = tmp_path / "rules"
    rules_dir.mkdir()
    (rules_dir / "example.md").write_text("# rule")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "index.ts").write_text("console.log(1);")

    monkeypatch.chdir(tmp_path)
    with patch("aegis_cli.doctor.shutil.which", side_effect=lambda cmd, **kw: "/usr/local/bin/soma" if cmd == "soma" else "/bin/node"), \
         patch("aegis_cli.init.get_rules_dir", return_value=rules_dir):
        args = argparse.Namespace(fix=True)
        res = run_doctor(args)
    assert res == 0
    captured = capsys.readouterr().out
    assert "Fixed: enabled the packaged AST drivers" in captured
    assert (tmp_path / ".aegis" / "config.json").is_file()


def test_run_doctor_without_fix_flag_does_not_provision(tmp_path, monkeypatch, capsys):
    (tmp_path / ".gemini").mkdir()
    evidence = tmp_path / ".aegis" / "evidence"
    evidence.mkdir(parents=True)
    rules_dir = tmp_path / "rules"
    rules_dir.mkdir()
    (rules_dir / "example.md").write_text("# rule")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "index.ts").write_text("console.log(1);")

    monkeypatch.chdir(tmp_path)
    with patch("aegis_cli.doctor.shutil.which", side_effect=lambda cmd, **kw: "/usr/local/bin/soma" if cmd == "soma" else "/bin/node"), \
         patch("aegis_cli.init.get_rules_dir", return_value=rules_dir):
        args = argparse.Namespace()
        run_doctor(args)
    assert not (tmp_path / ".aegis" / "config.json").exists()
    out = capsys.readouterr().out
    assert "Run 'aegis doctor --fix' to provision" in out



def test_run_doctor_drivers_flag(tmp_path):
    with patch("aegis_cli.doctor._check_ast_drivers") as mock_check:
        mock_check.return_value = True
        args = argparse.Namespace(drivers=True, workspace=str(tmp_path), fix=False)
        assert run_doctor(args) == 0
        mock_check.assert_called_with(tmp_path, fix=False)

        mock_check.return_value = False
        args_fail = argparse.Namespace(drivers=True, workspace=str(tmp_path), fix=True)
        assert run_doctor(args_fail) == 1
        mock_check.assert_called_with(tmp_path, fix=True)


@pytest.mark.parametrize("flag", ["--fix-path", "--yes", "-y"])
def test_doctor_rejects_cut_fix_path_flags(flag, capsys):
    """D17: doctor never edits shell rc files; the PATH hint stays advisory."""
    from aegis_cli.cli import main

    with pytest.raises(SystemExit) as exc:
        main(["doctor", flag])
    assert exc.value.code == 2
    assert f"unrecognized arguments: {flag}" in capsys.readouterr().err


def _rust_project_with_python3_driver(tmp_path, monkeypatch):
    """A rust project plus a user-scope driver named by its legacy 'python3' selector."""
    proj = tmp_path / "proj"
    (proj / "src").mkdir(parents=True)
    (proj / "src" / "main.rs").write_text("fn main() {}")
    home = tmp_path / "home"  # outside the workspace, so it is user scope
    (home / ".aegis").mkdir(parents=True)
    (home / ".aegis" / "config.json").write_text('{"v": 1, "drivers": {"rs": "python3 .aegis/drivers/rust_ast.py"}}')
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    empty_bin = tmp_path / "empty-bin"
    empty_bin.mkdir()
    monkeypatch.setenv("PATH", str(empty_bin))
    return proj


def test_check_ast_drivers_python3_slot_resolves_without_python3_on_path(tmp_path, monkeypatch, capsys):
    """#144: python.org installs on Windows ship no python3.exe; the driver runs
    on the interpreter running aegis, so doctor must not report it broken."""
    from aegis_cli.doctor import _check_ast_drivers
    proj = _rust_project_with_python3_driver(tmp_path, monkeypatch)

    assert _check_ast_drivers(proj) is True
    out = capsys.readouterr().out
    assert "AST driver (.rs): python3 resolvable" in out
    assert sys.executable in out


def test_check_ast_drivers_python3_slot_unresolvable_without_any_interpreter(tmp_path, monkeypatch, capsys):
    from aegis_cli.doctor import _check_ast_drivers
    proj = _rust_project_with_python3_driver(tmp_path, monkeypatch)
    monkeypatch.setattr(sys, "executable", "")

    assert _check_ast_drivers(proj) is False
    assert "executable 'python3' not found on PATH" in capsys.readouterr().out


def test_check_precommit_hook_all_branches(tmp_path, capsys):
    from aegis_cli.doctor import _check_precommit_hook
    git_dir = tmp_path / ".git" / "hooks"
    git_dir.mkdir(parents=True)
    hook_file = git_dir / "pre-commit"

    # 1. Non-aegis hook
    hook_file.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    assert _check_precommit_hook(tmp_path) is None

    # 2. Current hook
    from aegis_cli.hooks.management import generate_hook_block
    hook_file.write_text("#!/bin/sh\n" + generate_hook_block(sys.executable), encoding="utf-8")
    assert _check_precommit_hook(tmp_path) is True
    assert "Pre-commit hook is current" in capsys.readouterr().out

    # 2b. Format 4 resolved aegis through PATH and the repo: outdated now
    hook_file.write_text("#!/bin/sh\n# >>> aegis pre-commit >>>\n# aegis-hook-format: 4\naegis check --hook\n# <<< aegis pre-commit <<<\n", encoding="utf-8")
    assert _check_precommit_hook(tmp_path) is False
    assert "Pre-commit hook uses an old block" in capsys.readouterr().out

    # 3. Old hook format
    hook_file.write_text("#!/bin/sh\n# >>> aegis pre-commit >>>\nsoma checkpoint --pre-commit\n# <<< aegis pre-commit <<<\n", encoding="utf-8")
    assert _check_precommit_hook(tmp_path) is False
    assert "Pre-commit hook uses an old block" in capsys.readouterr().out


def test_doctor_json_mode_and_warning_counts(tmp_path, monkeypatch, capsys):
    """v3.0.0: doctor supports --json, prints 'aegis doctor', tallies warnings, and includes Fix: lines."""
    import json

    (tmp_path / ".gemini").mkdir()
    (tmp_path / ".aegis" / "evidence").mkdir(parents=True)
    rules_dir = tmp_path / "rules"
    rules_dir.mkdir()

    monkeypatch.chdir(tmp_path)
    with patch("aegis_cli.doctor.shutil.which", return_value="/usr/local/bin/aegis"), \
         patch("aegis_cli.init.get_rules_dir", return_value=rules_dir):
        # 1. Text mode with missing rules -> fails with Fix: remediation and warning/fail summary
        rc_text = run_doctor(argparse.Namespace())
        assert rc_text == 1
        out_text = capsys.readouterr().out
        assert "aegis doctor — running health checks" in out_text
        assert "Fix:" in out_text
        assert "warning" in out_text and "failed" in out_text

        # 2. JSON mode -> valid JSON with zero ANSI codes
        (rules_dir / "example.md").write_text("# rule", encoding="utf-8")
        rc_json = run_doctor(argparse.Namespace(json=True))
        assert rc_json == 0
        raw_json = capsys.readouterr().out
        assert "\x1b[" not in raw_json
        payload = json.loads(raw_json)
        assert payload["ok"] is True
        assert payload["passed"] >= 6
        assert "warnings" in payload
        assert payload["failed"] == 0


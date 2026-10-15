"""Tests for soma doctor health checks."""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
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
        from aegis_cli.init import get_rules_dir as _orig  # noqa: F811
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

    # slots.yaml exists, but no ast_driver slots
    slots_file = tmp_path / ".aegis" / "slots.yaml"
    slots_file.parent.mkdir(parents=True, exist_ok=True)
    slots_file.write_text("slots:\n  other_slot: foo\n")
    assert _check_ast_drivers(tmp_path) is True
    out2 = capsys.readouterr().out
    assert "native Python stdlib" in out2


def test_check_ast_drivers_with_valid_and_invalid_slots(tmp_path, capsys):
    from aegis_cli.doctor import _check_ast_drivers
    slots_file = tmp_path / ".aegis" / "slots.yaml"
    slots_file.parent.mkdir(parents=True)
    slots_file.write_text("slots:\n  ast_driver_ts: node runner.js\n  ast_driver: default_bin\n")

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

    # Corrupt slots.yaml raising exception
    with patch("aegis_core.skills.slots.SlotRegistry.load", side_effect=Exception("corrupt")):
        assert _check_ast_drivers(tmp_path) is False


def test_doctor_warns_when_ast_drivers_unresolvable(tmp_path, monkeypatch, capsys):
    (tmp_path / ".gemini").mkdir()
    evidence = tmp_path / ".aegis" / "evidence"
    evidence.mkdir(parents=True)
    rules_dir = tmp_path / "rules"
    rules_dir.mkdir()
    (rules_dir / "example.md").write_text("# rule")

    # H5: a repo slots.yaml can only opt in to a packaged driver (here ts_ast.js, which
    # needs node); an arbitrary repo-defined driver command is dropped before doctor sees it.
    slots_file = tmp_path / ".aegis" / "slots.yaml"
    slots_file.write_text("slots:\n  ast_driver_ts: node .aegis/drivers/ts_ast.js\n")

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
    assert "unconfigured driver for detected source language" in out
    assert "Run 'aegis doctor --fix' to provision" in out

    # With fix flag: auto-provisions and returns True
    assert _check_ast_drivers(tmp_path, fix=True) is True
    out = capsys.readouterr().out
    assert "Fixed: Auto-provisioned AST drivers" in out
    assert (tmp_path / ".aegis" / "slots.yaml").is_file()


def test_check_ast_drivers_missing_extension_slot_warns_and_fixes(tmp_path, capsys):
    from aegis_cli.doctor import _check_ast_drivers
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.rs").write_text("fn main() {}")

    # Write existing slots without rs slot
    slots_file = tmp_path / ".aegis" / "slots.yaml"
    slots_file.parent.mkdir(parents=True)
    slots_file.write_text("slots:\n  ast_driver_ts: node runner.js\n")

    # Without fix: warns
    assert _check_ast_drivers(tmp_path, fix=False) is False
    out = capsys.readouterr().out
    assert "unconfigured driver for detected source extension(s): .rs" in out

    # With fix: provisions missing slot
    assert _check_ast_drivers(tmp_path, fix=True) is True
    out = capsys.readouterr().out
    assert "Fixed: Auto-provisioned missing AST driver slots" in out
    assert "ast_driver_rs" in slots_file.read_text()


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
    assert "Fixed: Auto-provisioned AST drivers" in captured
    assert (tmp_path / ".aegis" / "slots.yaml").is_file()


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
        res = run_doctor(args)
    assert not (tmp_path / ".aegis" / "slots.yaml").exists()
    out = capsys.readouterr().out
    assert "Run 'aegis doctor --fix' to provision" in out



def test_run_doctor_drivers_flag(tmp_path):
    with patch("aegis_cli.doctor._check_ast_drivers") as mock_check:
        mock_check.return_value = True
        args = argparse.Namespace(drivers=True, workspace=str(tmp_path), fix=False, fix_path=False, yes=False)
        assert run_doctor(args) == 0
        mock_check.assert_called_with(tmp_path, fix=False)

        mock_check.return_value = False
        args_fail = argparse.Namespace(drivers=True, workspace=str(tmp_path), fix=True, fix_path=False, yes=False)
        assert run_doctor(args_fail) == 1
        mock_check.assert_called_with(tmp_path, fix=True)


def test_doctor_command_contract():
    from aegis_cli.doctor import DoctorCommand
    cmd = DoctorCommand()
    parser = argparse.ArgumentParser()
    cmd.configure_parser(parser)
    parsed = parser.parse_args(["--fix", "--drivers", "--fix-path", "--yes"])
    assert parsed.fix is True
    assert parsed.drivers is True
    assert parsed.fix_path is True
    assert parsed.yes is True

    with patch("aegis_cli.doctor.run_doctor", return_value=0) as mock_run:
        assert cmd.execute(parsed) == 0
        mock_run.assert_called_once_with(parsed)


def _rust_project_with_python3_slot(tmp_path, monkeypatch):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.rs").write_text("fn main() {}")
    slots_file = tmp_path / ".aegis" / "slots.yaml"
    slots_file.parent.mkdir(parents=True)
    slots_file.write_text('slots:\n  ast_driver_rs: "python3 .aegis/drivers/rust_ast.py"\n')
    empty_bin = tmp_path / "empty-bin"
    empty_bin.mkdir()
    monkeypatch.setenv("PATH", str(empty_bin))


def test_check_ast_drivers_python3_slot_resolves_without_python3_on_path(tmp_path, monkeypatch, capsys):
    """#144: python.org installs on Windows ship no python3.exe; the slot runs
    on the interpreter running soma, so doctor must not report it broken."""
    from aegis_cli.doctor import _check_ast_drivers
    _rust_project_with_python3_slot(tmp_path, monkeypatch)

    assert _check_ast_drivers(tmp_path) is True
    out = capsys.readouterr().out
    assert "AST driver (.rs): python3 resolvable" in out
    assert sys.executable in out


def test_check_ast_drivers_python3_slot_unresolvable_without_any_interpreter(tmp_path, monkeypatch, capsys):
    from aegis_cli.doctor import _check_ast_drivers
    _rust_project_with_python3_slot(tmp_path, monkeypatch)
    monkeypatch.setattr(sys, "executable", "")

    assert _check_ast_drivers(tmp_path) is False
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
    hook_file.write_text("#!/bin/sh\n# >>> aegis pre-commit >>>\n# aegis-hook-format: 4\naegis check --hook\n", encoding="utf-8")
    assert _check_precommit_hook(tmp_path) is True
    assert "Pre-commit hook is current" in capsys.readouterr().out

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


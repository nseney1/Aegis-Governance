"""Unit tests for aegis check command (aegis_cli/check.py)."""
from __future__ import annotations

import argparse
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from aegis_cli.check import CheckCommand, run_check


def test_check_command_contract():
    cmd = CheckCommand()
    assert cmd.name == "check"
    assert "verify" in cmd.aliases
    assert "checkpoint" in cmd.aliases

    parser = argparse.ArgumentParser()
    cmd.configure_parser(parser)

    # Test argument parsing
    args = parser.parse_args(["foo.py", "--hook"])
    assert args.target_files == ["foo.py"]
    assert args.hook is True


def test_check_default_runs_layer1():
    args = argparse.Namespace(
        target_files=["foo.py"],
        files=None,
        hook=False,
        full=False,
        release=False,
        release_gate=False,
        checkpoint_only=False,
        plan=None,
        plan_file=None,
    )
    with patch("aegis_cli.check.run_verify", return_value=0) as mock_verify:
        rc = run_check(args)
        assert rc == 0
        assert args.files == ["foo.py"]
        assert args.layer1_only is True
        mock_verify.assert_called_once_with(args)


def test_check_full_runs_full_verification():
    args = argparse.Namespace(
        target_files=None,
        files=["a.py"],
        hook=False,
        full=True,
        release=False,
        release_gate=False,
        checkpoint_only=False,
    )
    with patch("aegis_cli.check.run_verify", return_value=0) as mock_verify:
        rc = run_check(args)
        assert rc == 0
        assert args.layer1_only is False
        mock_verify.assert_called_once_with(args)


def test_check_release_runs_release_gate():
    args = argparse.Namespace(
        target_files=None,
        files=None,
        hook=False,
        full=False,
        release=True,
        release_gate=False,
        checkpoint_only=False,
    )
    with patch("aegis_cli.check.run_verify", return_value=0) as mock_verify:
        rc = run_check(args)
        assert rc == 0
        assert args.release_gate is True
        mock_verify.assert_called_once_with(args)


def test_check_hook_mode():
    args = argparse.Namespace(
        target_files=None,
        files=None,
        hook=True,
        full=False,
        release=False,
        release_gate=False,
        checkpoint_only=False,
    )
    with patch("aegis_cli.check.run_checkpoint", return_value=0) as mock_cp, \
         patch("aegis_cli.check.run_verify", return_value=0) as mock_verify:
        rc = run_check(args)
        assert rc == 0
        assert args.hook is False
        assert args.layer1_only is True
        assert args.pre_commit is True
        mock_cp.assert_called_once_with(args)
        mock_verify.assert_called_once_with(args)


def test_check_checkpoint_only_mode():
    args = argparse.Namespace(
        target_files=None,
        files=None,
        hook=False,
        full=False,
        release=False,
        release_gate=False,
        checkpoint_only=True,
    )
    with patch("aegis_cli.check.run_checkpoint", return_value=0) as mock_cp:
        rc = run_check(args)
        assert rc == 0
        mock_cp.assert_called_once_with(args)


def test_check_supports_deep_and_all_flags():
    """v3.0.0: check supports --deep (alias for --full) and --all flags."""
    cmd = CheckCommand()
    parser = argparse.ArgumentParser()
    cmd.configure_parser(parser)
    parsed = parser.parse_args(["--deep", "--all"])
    assert parsed.full is True
    assert parsed.all_files is True


def test_check_json_mode_emits_valid_json_without_ansi(tmp_path, capsys):
    """v3.0.0: aegis check --json emits valid machine-parseable JSON with zero ANSI codes."""
    import json

    (tmp_path / ".aegis" / "rules").mkdir(parents=True)
    target = tmp_path / "sample.py"
    target.write_text("def add(a: int, b: int) -> int:\n    return a + b\n", encoding="utf-8")

    args = argparse.Namespace(
        target_files=["sample.py"],
        files=None,
        hook=False,
        full=False,
        release=False,
        release_gate=False,
        checkpoint_only=False,
        plan=None,
        plan_file=None,
        workspace=str(tmp_path),
        json=True,
        format="json",
    )
    rc = run_check(args)
    assert rc == 0
    raw = capsys.readouterr().out
    assert "\x1b[" not in raw
    payload = json.loads(raw)
    assert payload["passed"] is True
    assert payload["files"] == ["sample.py"]
    assert isinstance(payload["layer1"], list)


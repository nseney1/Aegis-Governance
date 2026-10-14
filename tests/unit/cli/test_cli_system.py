"""Unit tests for aegis system command (aegis_cli/system.py)."""
from __future__ import annotations

import argparse
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from aegis_cli.system import SystemCommand, run_system


def test_system_command_contract():
    cmd = SystemCommand()
    assert cmd.name == "system"
    assert "sys" in cmd.aliases

    parser = argparse.ArgumentParser()
    cmd.configure_parser(parser)

    # Test doctor
    args_doc = parser.parse_args(["doctor", "--fix", "--json"])
    assert args_doc.system_action == "doctor"
    assert args_doc.fix is True
    assert args_doc.json is True

    # Test hook
    args_hook = parser.parse_args(["hook", "install", "--force"])
    assert args_hook.system_action == "hook"
    assert args_hook.hook_subaction == "install"
    assert args_hook.force is True

    # Test drivers
    args_drv = parser.parse_args(["drivers", "--dry-run"])
    assert args_drv.system_action == "drivers"
    assert args_drv.dry_run is True

    # Test skills
    args_skl = parser.parse_args(["skills", "list"])
    assert args_skl.system_action == "skills"
    assert args_skl.skill_subaction == "list"


def test_system_default_runs_doctor():
    args = argparse.Namespace(system_action=None)
    with patch("aegis_cli.doctor.run_doctor", return_value=0) as mock_doc:
        rc = run_system(args)
        assert rc == 0
        mock_doc.assert_called_once_with(args)


def test_system_doctor_dispatch():
    args = argparse.Namespace(system_action="doctor")
    with patch("aegis_cli.doctor.run_doctor", return_value=0) as mock_doc:
        rc = run_system(args)
        assert rc == 0
        mock_doc.assert_called_once_with(args)


def test_system_hook_dispatch():
    args = argparse.Namespace(system_action="hook", hook_subaction="install")
    with patch("aegis_cli.hooks.run_hook", return_value=0) as mock_hook:
        rc = run_system(args)
        assert rc == 0
        assert args.hook_action == "install"
        mock_hook.assert_called_once_with(args)


def test_system_drivers_dispatch():
    args = argparse.Namespace(system_action="drivers")
    with patch("aegis_cli.detect.run_detect", return_value=0) as mock_detect:
        rc = run_system(args)
        assert rc == 0
        mock_detect.assert_called_once_with(args)


def test_system_skills_dispatch():
    args = argparse.Namespace(system_action="skills", skill_subaction="list")
    with patch("aegis_cli.skills.run_skill", return_value=0) as mock_skill:
        rc = run_system(args)
        assert rc == 0
        assert args.skill_action == "list"
        mock_skill.assert_called_once_with(args)

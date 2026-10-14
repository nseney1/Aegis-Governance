"""Behavioral tests for BUG-074: Command Safety Shell Interpreter Bypass via Bundled Flags.

Shell scripts invoked with bundled POSIX short flags (e.g. bash -lc, sh -ec, bash -xc)
must be unwrapped by unwrap_command_stage() so that inner destructive commands
(such as rm -rf /, git reset --hard, etc.) are properly inspected and flagged.
"""
import pytest
from aegis_core.command_safety import (
    CommandAnalyzer,
    REASON_RM_RF,
    REASON_GIT_RESET_HARD,
)


def test_bash_lc_bundled_flag_unwrapped():
    """bash -lc 'rm -rf /' must be unwrapped and flagged as destructive."""
    cmd = 'bash -lc "rm -rf /"'
    eval_result = CommandAnalyzer.evaluate(cmd)
    assert eval_result.is_destructive is True, f"Failed to detect destructive command in: {cmd}"
    assert eval_result.reason == REASON_RM_RF


def test_sh_ec_bundled_flag_unwrapped():
    """sh -ec 'git reset --hard' must be unwrapped and flagged as destructive."""
    cmd = 'sh -ec "git reset --hard"'
    eval_result = CommandAnalyzer.evaluate(cmd)
    assert eval_result.is_destructive is True, f"Failed to detect destructive command in: {cmd}"
    assert eval_result.reason == REASON_GIT_RESET_HARD


def test_zsh_xic_bundled_flag_unwrapped():
    """zsh -xic 'rm -rf /' must be unwrapped and flagged as destructive."""
    cmd = 'zsh -xic "rm -rf /"'
    eval_result = CommandAnalyzer.evaluate(cmd)
    assert eval_result.is_destructive is True, f"Failed to detect destructive command in: {cmd}"
    assert eval_result.reason == REASON_RM_RF


def test_safe_shell_bundled_flag_not_false_positive():
    """Benign commands with bundled flags should not be falsely marked destructive."""
    cmd = 'bash -lc "echo safe && ls -la"'
    eval_result = CommandAnalyzer.evaluate(cmd)
    assert eval_result.is_destructive is False

"""Behavioral tests for BUG-080: Missing CLI Output Sanitization & C1 Control Sequence Gaps.

sanitize_display() must filter 8-bit C1 control sequences (\x80-\x9f) and DCS escape
sequences. In addition, CLI error and warning streams must sanitize external inputs
(such as filenames from git or user arguments).
"""
import io
import sys
from unittest.mock import patch
import pytest

from aegis_cli import sanitize_display


def test_sanitize_display_c1_control_codes():
    """8-bit C1 control sequences (\x80-\x9f) such as \x9b must be stripped."""
    # \x9b is 8-bit CSI (Command Sequence Introducer), \x90 is DCS, \x9d is OSC
    malicious = "normal\x9b2Jtext\x90device\x9dwindow"
    sanitized = sanitize_display(malicious)
    assert "\x9b" not in sanitized
    assert "\x90" not in sanitized
    assert "\x9d" not in sanitized
    assert "normal" in sanitized
    assert "text" in sanitized


def test_sanitize_display_dcs_sequences():
    """Device Control String (DCS) sequences must be stripped."""
    malicious = "start\x1bP$qterm\x1b\\end"
    sanitized = sanitize_display(malicious)
    assert "\x1bP" not in sanitized
    assert "\x1b\\" not in sanitized
    assert "start" in sanitized
    assert "end" in sanitized


def test_verify_out_of_tree_warning_sanitized(capsys):
    """aegis_cli.verify.resolve_target_files must sanitize out-of-tree filenames printed to stderr."""
    from argparse import Namespace
    from aegis_cli.verify import resolve_target_files

    malicious_filename = "bad\x1b[2J\x9b31mfile.py"
    args = Namespace(files=[malicious_filename], repo_root="/tmp/fake_repo")

    with patch("os.path.realpath", side_effect=lambda p: "/outside/" + p):
        resolve_target_files(args)

    captured = capsys.readouterr()
    assert "\x1b[" not in captured.err, "Raw ANSI escape printed to stderr!"
    assert "\x9b" not in captured.err, "Raw C1 control code printed to stderr!"
    assert "bad" in captured.err

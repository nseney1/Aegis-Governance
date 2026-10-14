"""Behavioral tests for BUG-075: Destructive rm -rf Detection Bypass via Trailing Slashes.

evaluate_rm() must normalize paths and strip trailing slashes (e.g. ./, ../, ~/, /home/)
so that targets cannot evade dangerous directory deletion detection.
"""
import pytest
from aegis_core.command_safety import (
    CommandAnalyzer,
    REASON_RM_RF,
)


@pytest.mark.parametrize("target", [
    "./",
    ".//",
    "../",
    "..//",
    "~/",
    "/home/",
    "/root/",
    "/",
])
def test_rm_rf_trailing_slashes_detected(target):
    """rm -rf with trailing slashes must be flagged as destructive."""
    cmd = f"rm -rf {target}"
    eval_result = CommandAnalyzer.evaluate(cmd)
    assert eval_result.is_destructive is True, f"Failed to detect destructive command: {cmd}"
    assert eval_result.reason == REASON_RM_RF


def test_rm_rf_safe_subpath_not_flagged():
    """rm -rf on a specific named subfolder must not trigger root/home REASON_RM_RF."""
    cmd = "rm -rf ./build/dist/"
    eval_result = CommandAnalyzer.evaluate(cmd)
    # Removing ./build/dist/ is a standard build artifact cleanup, not root/home wipe
    assert eval_result.is_destructive is False

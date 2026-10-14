"""Behavioral tests for empty diff clean gate handling in verification runner."""
import pytest
from aegis_core.verification import runner


def test_gate_verdict_empty_results_passes():
    """gate_verdict([]) on an empty diff should evaluate as a clean pass (True), not a failure."""
    verdict = runner.gate_verdict([])
    assert verdict is True, "Empty verification evidence (no changed files) should be a clean pass."


def test_format_summary_empty_results():
    """format_summary([]) should format clean informational message."""
    summary = runner.format_summary([])
    assert "No changed files to verify" in summary or "0 checks run" in summary

from pathlib import Path
"""TDD tests for transcript_verifier.py — orchestrator-level claim verification.

Behavioral contract: the orchestrator reads subagent transcripts and
independently extracts metrics (pytest runs, pass/fail counts, file writes)
to verify subagent self-reported claims. Divergences between claimed and
verified results are flagged.
"""
import os
import sys
import json
import textwrap

import pytest

REPO_ROOT = str(next(p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").exists()))
sys.path.insert(0, REPO_ROOT)

from aegis_core.verification import ToolEvidence


class TestMetricExtraction:
    """Contract: extract_metrics parses transcript JSONL into objective counts."""

    def test_counts_pytest_runs(self, tmp_path):
        """Must count the number of distinct pytest invocations."""
        from aegis_core.verification.transcript_verifier import extract_metrics

        transcript = tmp_path / "transcript.jsonl"
        transcript.write_text('\n'.join([
            json.dumps({"step_index": 0, "source": "MODEL", "type": "WRITE_FILE", "status": "DONE", "content": "Created file mutation_tester.py"}),
            json.dumps({"step_index": 1, "source": "MODEL", "type": "RUN_COMMAND", "status": "DONE", "exit_code": 0, "content": "pytest tests/test_mutation.py\n6 passed in 2.0s"}),
        ]))

        metrics = extract_metrics(str(transcript))
        assert metrics.pytest_runs == 1

    def test_counts_multiple_pytest_runs(self, tmp_path):
        """Multiple pytest invocations should all be counted."""
        from aegis_core.verification.transcript_verifier import extract_metrics

        transcript = tmp_path / "transcript.jsonl"
        transcript.write_text('\n'.join([
            json.dumps({"step_index": 0, "source": "MODEL", "type": "WRITE_FILE", "status": "DONE", "content": "Created file"}),
            json.dumps({"step_index": 1, "source": "MODEL", "type": "RUN_COMMAND", "status": "DONE", "exit_code": 1, "content": "pytest\n2 failed, 2 passed"}),
            json.dumps({"step_index": 2, "source": "MODEL", "type": "WRITE_FILE", "status": "DONE", "content": "Fixed file"}),
            json.dumps({"step_index": 3, "source": "MODEL", "type": "RUN_COMMAND", "status": "DONE", "exit_code": 0, "content": "pytest\n4 passed"}),
        ]))

        metrics = extract_metrics(str(transcript))
        assert metrics.pytest_runs == 2

    def test_extracts_first_run_results(self, tmp_path):
        """Must capture pass/fail counts from the FIRST pytest run."""
        from aegis_core.verification.transcript_verifier import extract_metrics

        transcript = tmp_path / "transcript.jsonl"
        transcript.write_text('\n'.join([
            json.dumps({"step_index": 0, "source": "MODEL", "type": "RUN_COMMAND", "status": "DONE", "exit_code": 1, "content": "pytest\n2 failed, 4 passed"}),
            json.dumps({"step_index": 1, "source": "MODEL", "type": "RUN_COMMAND", "status": "DONE", "exit_code": 0, "content": "pytest\n6 passed"}),
        ]))

        metrics = extract_metrics(str(transcript))
        assert metrics.first_run_passed == 4
        assert metrics.first_run_failed == 2

    def test_extracts_final_run_results(self, tmp_path):
        """Must capture pass/fail counts from the LAST pytest run."""
        from aegis_core.verification.transcript_verifier import extract_metrics

        transcript = tmp_path / "transcript.jsonl"
        transcript.write_text('\n'.join([
            json.dumps({"step_index": 0, "source": "MODEL", "type": "RUN_COMMAND", "status": "DONE", "exit_code": 1, "content": "pytest\n2 failed, 4 passed"}),
            json.dumps({"step_index": 1, "source": "MODEL", "type": "RUN_COMMAND", "status": "DONE", "exit_code": 0, "content": "pytest\n6 passed"}),
        ]))

        metrics = extract_metrics(str(transcript))
        assert metrics.final_passed == 6
        assert metrics.final_failed == 0

    def test_counts_file_writes(self, tmp_path):
        """Must count write_to_file, replace_file_content, and multi_replace operations."""
        from aegis_core.verification.transcript_verifier import extract_metrics

        transcript = tmp_path / "transcript.jsonl"
        transcript.write_text('\n'.join([
            json.dumps({"step_index": 0, "source": "MODEL", "type": "WRITE_FILE", "status": "DONE", "content": "write_to_file created file"}),
            json.dumps({"step_index": 1, "source": "MODEL", "type": "RUN_COMMAND", "status": "DONE", "exit_code": 1, "content": "pytest\n2 failed"}),
            json.dumps({"step_index": 2, "source": "MODEL", "type": "EDIT_FILE", "status": "DONE", "content": "replace_file_content fixed bug"}),
            json.dumps({"step_index": 3, "source": "MODEL", "type": "EDIT_FILE", "status": "DONE", "content": "multi_replace fixed another bug"}),
            json.dumps({"step_index": 4, "source": "MODEL", "type": "RUN_COMMAND", "status": "DONE", "exit_code": 0, "content": "pytest\n4 passed"}),
        ]))

        metrics = extract_metrics(str(transcript))
        assert metrics.file_writes == 3

    def test_computes_fix_cycles(self, tmp_path):
        """fix_cycles = number of write operations AFTER the first failed test run."""
        from aegis_core.verification.transcript_verifier import extract_metrics

        transcript = tmp_path / "transcript.jsonl"
        transcript.write_text('\n'.join([
            json.dumps({"step_index": 0, "source": "MODEL", "type": "WRITE_FILE", "status": "DONE", "content": "Initial write"}),
            json.dumps({"step_index": 1, "source": "MODEL", "type": "RUN_COMMAND", "status": "DONE", "exit_code": 1, "content": "pytest\n2 failed, 2 passed"}),
            json.dumps({"step_index": 2, "source": "MODEL", "type": "EDIT_FILE", "status": "DONE", "content": "Fix 1"}),
            json.dumps({"step_index": 3, "source": "MODEL", "type": "EDIT_FILE", "status": "DONE", "content": "Fix 2"}),
            json.dumps({"step_index": 4, "source": "MODEL", "type": "RUN_COMMAND", "status": "DONE", "exit_code": 0, "content": "pytest\n4 passed"}),
        ]))

        metrics = extract_metrics(str(transcript))
        assert metrics.fix_cycles == 2

    def test_zero_fix_cycles_on_first_pass(self, tmp_path):
        """A lane that passes first try should have 0 fix cycles."""
        from aegis_core.verification.transcript_verifier import extract_metrics

        transcript = tmp_path / "transcript.jsonl"
        transcript.write_text('\n'.join([
            json.dumps({"step_index": 0, "source": "MODEL", "type": "WRITE_FILE", "status": "DONE", "content": "Created file"}),
            json.dumps({"step_index": 1, "source": "MODEL", "type": "RUN_COMMAND", "status": "DONE", "exit_code": 0, "content": "pytest\n6 passed"}),
        ]))

        metrics = extract_metrics(str(transcript))
        assert metrics.fix_cycles == 0
        assert metrics.first_run_passed == 6
        assert metrics.first_run_failed == 0


class TestClaimVerification:
    """Contract: verify_claim compares metrics against subagent self-report."""

    def test_honest_first_pass_verified(self, tmp_path):
        """When subagent claims first-pass and transcript confirms, verdict=True."""
        from aegis_core.verification.transcript_verifier import extract_metrics, verify_claim

        transcript = tmp_path / "transcript.jsonl"
        transcript.write_text('\n'.join([
            json.dumps({"step_index": 0, "source": "MODEL", "type": "WRITE_FILE", "status": "DONE", "content": "Created file"}),
            json.dumps({"step_index": 1, "source": "MODEL", "type": "RUN_COMMAND", "status": "DONE", "exit_code": 0, "content": "pytest\n6 passed"}),
        ]))

        metrics = extract_metrics(str(transcript))
        result = verify_claim(
            metrics=metrics,
            claimed_first_pass=True,
            claimed_tests_passed=6,
            agent_role="test_agent",
        )
        assert result.verdict is True
        assert "verified" in result.detail.lower() or "confirmed" in result.detail.lower()

    def test_false_first_pass_caught(self, tmp_path):
        """When subagent claims first-pass but had failures, verdict=False."""
        from aegis_core.verification.transcript_verifier import extract_metrics, verify_claim

        transcript = tmp_path / "transcript.jsonl"
        transcript.write_text('\n'.join([
            json.dumps({"step_index": 0, "source": "MODEL", "type": "WRITE_FILE", "status": "DONE", "content": "Created file"}),
            json.dumps({"step_index": 1, "source": "MODEL", "type": "RUN_COMMAND", "status": "DONE", "exit_code": 1, "content": "pytest\n2 failed, 4 passed"}),
            json.dumps({"step_index": 2, "source": "MODEL", "type": "EDIT_FILE", "status": "DONE", "content": "Fixed"}),
            json.dumps({"step_index": 3, "source": "MODEL", "type": "RUN_COMMAND", "status": "DONE", "exit_code": 0, "content": "pytest\n6 passed"}),
        ]))

        metrics = extract_metrics(str(transcript))
        result = verify_claim(
            metrics=metrics,
            claimed_first_pass=True,
            claimed_tests_passed=6,
            agent_role="test_agent",
        )
        assert result.verdict is False
        assert "2" in result.detail  # Should mention the actual failure count
        assert result.tool == "transcript_verifier"

    def test_inflated_test_count_caught(self, tmp_path):
        """When subagent claims more tests passed than actually did, verdict=False."""
        from aegis_core.verification.transcript_verifier import extract_metrics, verify_claim

        transcript = tmp_path / "transcript.jsonl"
        transcript.write_text('\n'.join([
            json.dumps({"step_index": 0, "source": "MODEL", "type": "WRITE_FILE", "status": "DONE", "content": "Created file"}),
            json.dumps({"step_index": 1, "source": "MODEL", "type": "RUN_COMMAND", "status": "DONE", "exit_code": 0, "content": "pytest\n4 passed"}),
        ]))

        metrics = extract_metrics(str(transcript))
        result = verify_claim(
            metrics=metrics,
            claimed_first_pass=True,
            claimed_tests_passed=6,  # Claims 6 but only 4 passed
            agent_role="test_agent",
        )
        assert result.verdict is False
        assert "4" in result.detail  # Should mention actual count


class TestRealTranscripts:
    """Validate against ACTUAL subagent transcripts from a prior session.

    Set SOMA_TEST_BRAIN_DIR to the Antigravity brain directory to enable.
    Skips automatically when transcripts are unavailable.
    """

    BRAIN_DIR = os.environ.get('SOMA_TEST_BRAIN_DIR', os.path.expanduser('~/.gemini/antigravity/brain'))
    LANE_A_ID = "9739cd63-0ab0-4f36-9551-9abc11d4a7cd"
    LANE_B_ID = "abbe31f4-341b-4b5d-a7b2-a0a06f004558"
    LANE_C_ID = "ffef2cc0-a0f0-46e0-9da5-678126093a73"

    @classmethod
    def _transcript_path(cls, conv_id):
        return os.path.join(cls.BRAIN_DIR, conv_id, '.system_generated', 'logs', 'transcript.jsonl')

    @pytest.mark.skipif(
        not os.path.exists(os.path.join(
            os.environ.get('SOMA_TEST_BRAIN_DIR', os.path.expanduser('~/.gemini/antigravity/brain')),
            "9739cd63-0ab0-4f36-9551-9abc11d4a7cd", '.system_generated', 'logs', 'transcript.jsonl')),
        reason="Lane A transcript not available"
    )
    def test_lane_a_was_genuine_first_pass(self):
        """Lane A (mutation_tester) claimed first-pass — verify from transcript."""
        from aegis_core.verification.transcript_verifier import extract_metrics

        metrics = extract_metrics(self._transcript_path(self.LANE_A_ID))
        assert metrics.pytest_runs == 1, f"Expected 1 pytest run, got {metrics.pytest_runs}"
        assert metrics.first_run_failed == 0, f"Expected 0 failures, got {metrics.first_run_failed}"
        assert metrics.fix_cycles == 0

    @pytest.mark.skipif(
        not os.path.exists(os.path.join(
            os.environ.get('SOMA_TEST_BRAIN_DIR', os.path.expanduser('~/.gemini/antigravity/brain')),
            "abbe31f4-341b-4b5d-a7b2-a0a06f004558", '.system_generated', 'logs', 'transcript.jsonl')),
        reason="Lane B transcript not available"
    )
    def test_lane_b_was_not_first_pass(self):
        """Lane B (branch_coverage) should show iteration — verify from transcript."""
        from aegis_core.verification.transcript_verifier import extract_metrics

        metrics = extract_metrics(self._transcript_path(self.LANE_B_ID))
        assert metrics.pytest_runs >= 2, f"Expected >=2 pytest runs, got {metrics.pytest_runs}"
        assert metrics.first_run_failed > 0, f"Expected failures on first run"
        assert metrics.fix_cycles > 0, f"Expected fix cycles > 0"

    @pytest.mark.skipif(
        not os.path.exists(os.path.join(
            os.environ.get('SOMA_TEST_BRAIN_DIR', os.path.expanduser('~/.gemini/antigravity/brain')),
            "ffef2cc0-a0f0-46e0-9da5-678126093a73", '.system_generated', 'logs', 'transcript.jsonl')),
        reason="Lane C transcript not available"
    )
    def test_lane_c_was_genuine_first_pass(self):
        """Lane C (immune_verify) claimed first-pass — verify from transcript."""
        from aegis_core.verification.transcript_verifier import extract_metrics

        metrics = extract_metrics(self._transcript_path(self.LANE_C_ID))
        assert metrics.pytest_runs == 1, f"Expected 1 pytest run, got {metrics.pytest_runs}"
        assert metrics.first_run_failed == 0, f"Expected 0 failures, got {metrics.first_run_failed}"
        assert metrics.fix_cycles == 0


class TestFix22aMissingFile:
    """Fix 2.2a: extract_metrics must not crash on missing transcript files."""

    def test_extract_metrics_missing_file_returns_empty(self):
        """Calling extract_metrics with a non-existent path should return empty SubagentMetrics."""
        from aegis_core.verification.transcript_verifier import extract_metrics, SubagentMetrics

        result = extract_metrics("/tmp/definitely_does_not_exist_transcript.jsonl")
        assert isinstance(result, SubagentMetrics)
        assert result.pytest_runs == 0
        assert result.first_run_passed == 0
        assert result.first_run_failed == 0
        assert result.final_passed == 0
        assert result.final_failed == 0
        assert result.file_writes == 0
        assert result.fix_cycles == 0


class TestFix22bWriteStepFalsePositive:
    """Fix 2.2b: _is_write_step must not match content-string mentions of tool names."""

    def test_write_step_ignores_content_mentions(self):
        """A PLANNER_RESPONSE mentioning 'write_to_file' in content should NOT count as a write."""
        from aegis_core.verification.transcript_verifier import _is_write_step

        step = {
            "type": "PLANNER_RESPONSE",
            "content": "I will use write_to_file to create the module.",
        }
        assert _is_write_step(step) is False

    def test_write_step_detects_tool_calls(self):
        """A step with tool_calls containing write_to_file must be detected as a write."""
        from aegis_core.verification.transcript_verifier import _is_write_step

        step = {
            "type": "TOOL_USE",
            "tool_calls": [{"name": "write_to_file"}],
            "content": "",
        }
        assert _is_write_step(step) is True


class TestFix22cCollectionErrors:
    """Fix 2.2c: _parse_test_counts must detect pytest collection errors."""

    def test_collection_error_returns_sentinel(self):
        """Content with 'collection error' must return (-1, -1) sentinel."""
        from aegis_core.verification.transcript_verifier import _parse_test_counts

        result = _parse_test_counts("ERROR collecting tests/test_foo.py - collection error")
        assert result == (-1, -1)

    def test_errors_marker_returns_sentinel(self):
        """Content with 'ERRORS' must return (-1, -1) sentinel."""
        from aegis_core.verification.transcript_verifier import _parse_test_counts

        result = _parse_test_counts("===== ERRORS =====\nImportError in test_bar.py")
        assert result == (-1, -1)


class TestFix22dMultiRunNoFalsePositive:
    """Fix 2.2d: multiple pytest runs with all passing should not flag divergence."""

    def test_multi_run_all_passing_no_divergence(self, tmp_path):
        """Two passing pytest runs with 0 fix cycles should verify as first-pass."""
        from aegis_core.verification.transcript_verifier import extract_metrics, verify_claim

        transcript = tmp_path / "transcript.jsonl"
        transcript.write_text('\n'.join([
            json.dumps({"step_index": 0, "source": "MODEL", "type": "WRITE_FILE", "status": "DONE", "content": "Created file"}),
            json.dumps({"step_index": 1, "source": "MODEL", "type": "RUN_COMMAND", "status": "DONE", "exit_code": 0, "content": "pytest tests/test_a.py\n6 passed in 1.0s"}),
            json.dumps({"step_index": 2, "source": "MODEL", "type": "RUN_COMMAND", "status": "DONE", "exit_code": 0, "content": "pytest tests/ -q\n6 passed in 2.0s"}),
        ]))

        metrics = extract_metrics(str(transcript))
        assert metrics.pytest_runs == 2
        assert metrics.fix_cycles == 0

        result = verify_claim(
            metrics=metrics,
            claimed_first_pass=True,
            claimed_tests_passed=6,
            agent_role="test_agent",
        )
        assert result.verdict is True, f"Expected True but got divergence: {result.detail}"


"""Transcript Verifier — orchestrator-level subagent claim verification.

Reads subagent JSONL transcripts and extracts objective metrics
(pytest runs, pass/fail counts, file writes, fix cycles) to
independently verify subagent self-reported claims.

This is the "trust but verify" layer: subagents report completion,
the orchestrator checks the tape.
"""
import json
import os
import re
from dataclasses import dataclass

from . import ToolEvidence


@dataclass
class SubagentMetrics:
    """Objective metrics extracted from a subagent transcript."""
    pytest_runs: int = 0
    first_run_passed: int = 0
    first_run_failed: int = 0
    final_passed: int = 0
    final_failed: int = 0
    file_writes: int = 0
    fix_cycles: int = 0  # writes after first failure
    human_insights_received: int = 0  # [HUMAN_INSIGHT] annotations from user


# Patterns to detect pytest result lines
_PASSED_RE = re.compile(r'(\d+)\s+passed')
_FAILED_RE = re.compile(r'(\d+)\s+failed')

# Step types that indicate file mutations
_WRITE_TYPES = {'WRITE_FILE', 'EDIT_FILE', 'CREATE_FILE'}

# Content patterns that indicate file write tool calls
_WRITE_PATTERNS = {'write_to_file', 'replace_file_content', 'multi_replace'}


def _is_pytest_step(step: dict) -> bool:
    """Check if a transcript step is a pytest invocation."""
    if step.get('type') != 'RUN_COMMAND':
        return False
    content = step.get('content', '')
    return 'pytest' in content and ('passed' in content or 'failed' in content or 'error' in content)


def _is_write_step(step: dict) -> bool:
    """Check if a transcript step is a file write operation."""
    step_type = step.get('type', '')
    if step_type in _WRITE_TYPES:
        return True
    # Check tool_calls metadata instead of content strings
    tool_calls = step.get('tool_calls', [])
    if isinstance(tool_calls, list):
        for tc in tool_calls:
            tool_name = tc.get('name', '') if isinstance(tc, dict) else ''
            if tool_name in _WRITE_PATTERNS:
                return True
    return False


def _parse_test_counts(content: str) -> tuple[int, int]:
    """Extract (passed, failed) counts from pytest output.

    Returns (-1, -1) when pytest collection errors are detected.
    """
    # Detect collection errors
    if any(marker in content for marker in ('collection error', 'ERRORS', 'CollectionError')):
        return (-1, -1)
    passed_match = _PASSED_RE.search(content)
    failed_match = _FAILED_RE.search(content)
    passed = int(passed_match.group(1)) if passed_match else 0
    failed = int(failed_match.group(1)) if failed_match else 0
    return passed, failed


def extract_metrics(transcript_path: str) -> SubagentMetrics:
    """Extract objective metrics from a subagent transcript JSONL file.

    Reads the transcript line by line, identifies pytest runs and
    file write operations, and computes derived metrics like fix_cycles.

    Args:
        transcript_path: Path to the transcript.jsonl file

    Returns:
        SubagentMetrics with all fields populated from the transcript
    """
    if not os.path.exists(transcript_path):
        return SubagentMetrics()  # Return empty metrics for missing transcripts

    metrics = SubagentMetrics()
    pytest_results: list[tuple[int, int]] = []  # (passed, failed) per run
    first_failure_seen = False
    writes_after_failure = 0

    with open(transcript_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                step = json.loads(line)
            except json.JSONDecodeError:
                continue

            # Count [HUMAN_INSIGHT] annotations from user
            if (step.get('type') == 'USER_INPUT' and
                    '[HUMAN_INSIGHT]' in step.get('content', '')):
                metrics.human_insights_received += 1

            if _is_pytest_step(step):
                content = step.get('content', '')
                passed, failed = _parse_test_counts(content)
                pytest_results.append((passed, failed))

                if failed > 0 and not first_failure_seen:
                    first_failure_seen = True

            elif _is_write_step(step):
                metrics.file_writes += 1
                if first_failure_seen:
                    writes_after_failure += 1

    metrics.pytest_runs = len(pytest_results)
    metrics.fix_cycles = writes_after_failure

    if pytest_results:
        metrics.first_run_passed, metrics.first_run_failed = pytest_results[0]
        metrics.final_passed, metrics.final_failed = pytest_results[-1]

    return metrics


def verify_claim(
    metrics: SubagentMetrics,
    claimed_first_pass: bool,
    claimed_tests_passed: int,
    agent_role: str,
) -> ToolEvidence:
    """Compare extracted metrics against a subagent's self-reported claims.

    Args:
        metrics: Objectively extracted transcript metrics
        claimed_first_pass: Whether the agent claimed first-pass success
        claimed_tests_passed: Number of tests the agent claimed passed
        agent_role: Name/role of the agent for reporting

    Returns:
        ToolEvidence with verdict=True if claims match transcript,
        False if any divergence detected
    """
    divergences = []

    # Check first-pass claim
    if claimed_first_pass and metrics.first_run_failed > 0:
        divergences.append(
            f"Claimed first-pass but transcript shows {metrics.first_run_failed} "
            f"failures on first run ({metrics.first_run_passed} passed, "
            f"{metrics.first_run_failed} failed)"
        )

    if claimed_first_pass and metrics.pytest_runs > 1 and metrics.fix_cycles > 0:
        divergences.append(
            f"Claimed first-pass but transcript shows {metrics.pytest_runs} "
            f"pytest runs with {metrics.fix_cycles} fix cycles"
        )

    # Check test count claim
    if claimed_tests_passed != metrics.final_passed:
        divergences.append(
            f"Claimed {claimed_tests_passed} tests passed but transcript "
            f"shows {metrics.final_passed} passed"
        )

    if divergences:
        return ToolEvidence(
            tool="transcript_verifier",
            target=agent_role,
            verdict=False,
            detail=f"CLAIM DIVERGENCE: {'; '.join(divergences)}",
        )

    return ToolEvidence(
        tool="transcript_verifier",
        target=agent_role,
        verdict=True,
        detail=(
            f"Claims verified: {metrics.final_passed} tests confirmed, "
            f"{metrics.pytest_runs} run(s), {metrics.fix_cycles} fix cycles"
        ),
    )

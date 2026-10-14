"""Evidence collector — correlates rule compliance with session outcomes.

Scans Antigravity/Claude transcript JSONL files for tool-call patterns
that indicate compliance or violation of governance rules. Aggregates
per-rule statistics for the evidence enrichment pipeline.

Security invariant: NEVER stores source code, file paths, or diff content.
Only aggregate integer metrics and ratios are produced.
"""

from __future__ import annotations

import json
import os
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

# Maximum number of directory levels a read can be above a write
# and still count as having "read" that file. Prevents repo-root
# grep from blanket-approving all writes.
_MAX_ANCESTOR_DISTANCE = 3


# ── Tool-call pattern definitions per rule ──────────────────────────

# Maps rule_id → detector function name
# Each detector receives a list of parsed transcript steps and returns
# a dict with compliant_count and non_compliant_count.

WRITE_TOOLS = frozenset({
    "replace_file_content",
    "multi_replace_file_content",
})

READ_TOOLS = frozenset({
    "view_file",
    "grep_search",
})


def _extract_tool_calls(steps: list[dict]) -> list[dict]:
    """Flatten all tool calls from transcript steps into a sequential list."""
    calls = []
    for step in steps:
        if not isinstance(step, dict):
            continue
        for tc in step.get("tool_calls", []):
            if not isinstance(tc, dict):
                continue
            name = tc.get("name", "")
            args = tc.get("args", {})
            if not isinstance(args, dict):
                continue
            # Extract ONLY the file path — never content
            raw_path = (
                args.get("TargetFile")
                or args.get("AbsolutePath")
                or args.get("SearchPath")
            )
            # Strip surrounding quotes from serialized arguments
            target_file = _sanitize_path(raw_path) if isinstance(raw_path, str) else None
            calls.append({
                "step_index": step.get("step_index", 0),
                "tool_name": name,
                "target_file": target_file,
            })
    return calls


def _check_read_before_write(steps: list[dict]) -> dict:
    """Check read-before-write compliance."""
    calls = _extract_tool_calls(steps)
    compliant = 0
    non_compliant = 0

    # Session-level set of files that have been read
    files_read: set[str] = set()

    for call in calls:
        target = call["target_file"]
        if not target:
            continue

        # Track reads
        if call["tool_name"] in READ_TOOLS:
            files_read.add(target)
            continue

        # Check writes
        if call["tool_name"] not in WRITE_TOOLS:
            continue

        # Check if any prior read covers this write target
        found_read = any(
            _paths_match(read_path, target)
            for read_path in files_read
        )

        if found_read:
            compliant += 1
        else:
            non_compliant += 1

    return {"compliant_count": compliant, "non_compliant_count": non_compliant}


def _paths_match(read_path: str, write_path: str) -> bool:
    """Check if a read path covers a write path."""
    rp = os.path.normpath(read_path)
    wp = os.path.normpath(write_path)

    # Exact match after normalization
    if rp == wp:
        return True

    # Reject root path reads unconditionally
    if rp in ("/", "."):
        return False

    # Directory ancestor check: read_path is a parent of write_path
    if wp.startswith(rp + os.sep):
        relative = os.path.relpath(wp, rp)
        distance = len(Path(relative).parts) - 1
        return distance <= _MAX_ANCESTOR_DISTANCE

    return False


# All write tools including new-file creation (used by TBI / hardcoded-paths)
_ALL_WRITE_TOOLS = WRITE_TOOLS | frozenset({"write_to_file"})

_TEST_FILE_RE = re.compile(
    r"(^|/)tests?/|_test\.py$|test_[^/]*\.py$",
)


def _is_test_file(path: str) -> bool:
    """Return True if *path* looks like a test file."""
    return bool(_TEST_FILE_RE.search(path))


def _check_test_before_implementation(steps: list[dict]) -> dict:
    """Check test-before-implementation compliance."""
    calls = _extract_tool_calls(steps)
    compliant = 0
    non_compliant = 0
    test_written = False

    for call in calls:
        target = call["target_file"]
        if not target:
            continue
        if call["tool_name"] not in _ALL_WRITE_TOOLS:
            continue
        if not target.endswith(".py"):
            continue

        if _is_test_file(target):
            test_written = True
        else:
            # Implementation file write
            if test_written:
                compliant += 1
            else:
                non_compliant += 1

    return {"compliant_count": compliant, "non_compliant_count": non_compliant}


_HARDCODED_PATH_RE = re.compile("/" + "home" + "/[^/]+/")


def _check_no_hardcoded_paths(steps: list[dict]) -> dict:
    """Check for hardcoded user-home paths in file write tool calls."""
    compliant = 0
    non_compliant = 0

    for step in steps:
        if not isinstance(step, dict):
            continue
        for tc in step.get("tool_calls", []):
            if not isinstance(tc, dict):
                continue
            name = tc.get("name", "")
            if name not in _ALL_WRITE_TOOLS:
                continue
            args = tc.get("args", {})
            if not isinstance(args, dict):
                continue

            raw_path = (
                args.get("TargetFile")
                or args.get("AbsolutePath")
                or ""
            )
            code = args.get("CodeContent", "")
            combined = f"{raw_path}\n{code}"

            if _HARDCODED_PATH_RE.search(combined):
                non_compliant += 1
            else:
                compliant += 1

    return {"compliant_count": compliant, "non_compliant_count": non_compliant}


# Registry of rule detectors
_DETECTORS: dict[str, Any] = {
    "read-before-write": _check_read_before_write,
    "test-before-implementation": _check_test_before_implementation,
    "no-hardcoded-paths": _check_no_hardcoded_paths,
}


def build_observation(
    compliance_result: dict,
    transcript_path: Path | str,
    rule_id: str,
) -> dict | None:
    """Bridge check_compliance output into aggregate_evidence input format."""
    c = compliance_result.get("compliant_count", 0)
    nc = compliance_result.get("non_compliant_count", 0)

    # Skip rules with no activity in this session
    if c == 0 and nc == 0:
        return None

    steps = _parse_transcript(Path(transcript_path))
    session_steps = len(steps)

    return {
        "rule_id": rule_id,
        "compliant": nc == 0,
        "session_steps": session_steps,
        "session_fpsr": 0.0,
    }


def check_compliance(transcript_path: Path | str, rule_id: str) -> dict:
    """Check a transcript for compliance with a specific rule."""
    transcript_path = Path(transcript_path)
    detector = _DETECTORS.get(rule_id)
    if detector is None:
        return {"compliant_count": 0, "non_compliant_count": 0}

    steps = _parse_transcript(transcript_path)
    return detector(steps)


def aggregate_evidence(observations: list[dict]) -> dict:
    """Aggregate per-session compliance observations into evidence stats."""
    if not observations:
        return {}

    by_rule: dict[str, list[dict]] = defaultdict(list)
    for obs in observations:
        by_rule[obs["rule_id"]].append(obs)

    evidence = {}
    for rule_id, obs_list in by_rule.items():
        compliant = [o for o in obs_list if o["compliant"]]
        non_compliant = [o for o in obs_list if not o["compliant"]]

        c_fpsr = (_mean([o["session_fpsr"] for o in compliant])
                  if compliant else None)
        nc_fpsr = (_mean([o["session_fpsr"] for o in non_compliant])
                   if non_compliant else None)
        c_steps = (_mean([o["session_steps"] for o in compliant])
                   if compliant else None)
        nc_steps = (_mean([o["session_steps"] for o in non_compliant])
                    if non_compliant else None)

        if c_steps and nc_steps and c_steps > 0:
            rework = nc_steps / c_steps
        else:
            rework = None

        n = len(obs_list)
        if n >= 10:
            confidence = "high"
        elif n >= 5:
            confidence = "medium"
        else:
            confidence = "low"

        evidence[rule_id] = {
            "samples": n,
            "compliant_fpsr": c_fpsr if c_fpsr is not None else 0,
            "non_compliant_fpsr": nc_fpsr if nc_fpsr is not None else 0,
            "compliant_avg_steps": c_steps if c_steps is not None else 0,
            "non_compliant_avg_steps": nc_steps if nc_steps is not None else 0,
            "rework_multiplier": rework if rework is not None else 0,
            "confidence": confidence,
        }

    return evidence


def _parse_transcript(path: Path) -> list[dict]:
    steps = []
    if not path.exists():
        return steps
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                parsed = json.loads(line)
                if isinstance(parsed, dict):
                    steps.append(parsed)
            except json.JSONDecodeError:
                continue
    return steps


def _sanitize_path(raw: str) -> str:
    return raw.strip().strip('"').strip("'").strip()


def _mean(values: list[float]) -> float:
    return sum(values) / len(values)


__all__ = [
    "READ_TOOLS",
    "WRITE_TOOLS",
    "aggregate_evidence",
    "build_observation",
    "check_compliance",
]

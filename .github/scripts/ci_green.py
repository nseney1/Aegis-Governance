#!/usr/bin/env python3
"""Pre-tag check: CI is green on the exact commit about to be tagged (ADR 0005 AD-10).

    python3 .github/scripts/ci_green.py <full-sha> [--workflow validate.yml]

Run it before `git tag`. It cannot be a step inside validate.yml: a job never
sees its own run's conclusion. Exit 0 only when GitHub reports at least one
run for that SHA and every one of them completed with conclusion "success";
1 when CI is not green (failed, cancelled, still running, or never ran); 2 for
a usage error or when gh is missing or fails. Standard library plus the gh CLI.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from typing import List, Optional

FULL_SHA = re.compile(r"^[0-9a-f]{40}$")
FIELDS = "conclusion,headSha,status,workflowName"


class GhError(Exception):
    """gh is missing, failed, or printed something that is not a run list."""


def _runs_for(sha: str, workflow: Optional[str]) -> list:
    argv = ["gh", "run", "list", "--commit", sha, "--json", FIELDS, "--limit", "100"]
    if workflow:
        argv += ["--workflow", workflow]
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=120)
    except FileNotFoundError:
        raise GhError("gh (GitHub CLI) not found on PATH; install it and run `gh auth login`")
    except subprocess.TimeoutExpired:
        raise GhError("gh run list did not answer within 120s")
    if proc.returncode != 0:
        raise GhError(f"gh run list failed (exit {proc.returncode}): {proc.stderr.strip()}")
    try:
        runs = json.loads(proc.stdout)
    except ValueError:
        raise GhError(f"could not parse gh output as JSON: {proc.stdout[:200]!r}")
    if not isinstance(runs, list):
        raise GhError(f"could not parse gh output as a list of runs: {proc.stdout[:200]!r}")
    # gh filters by --commit already; checking headSha again guards against a gh
    # that ignores the flag.
    return [r for r in runs if isinstance(r, dict) and r.get("headSha") == sha]


def _fail(code: int, message: str) -> int:
    print(f"ci_green: {message}", file=sys.stderr)
    return code


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Exit 0 only if CI is green on the exact commit.")
    parser.add_argument("sha", help="full 40-character commit SHA")
    parser.add_argument("--workflow", default=None, help="only consider runs of this workflow file")
    args = parser.parse_args(argv)

    if not FULL_SHA.match(args.sha):
        return _fail(2, f"expected a full 40-character commit SHA in lowercase hex, got {args.sha!r}")
    try:
        runs = _runs_for(args.sha, args.workflow)
    except GhError as exc:
        return _fail(2, str(exc))

    if not runs:
        return _fail(1, f"no CI run found for {args.sha}")
    not_green = [r for r in runs if r.get("status") != "completed" or r.get("conclusion") != "success"]
    if not_green:
        detail = ", ".join(
            f"{r.get('workflowName', '?')}: {r.get('conclusion') or r.get('status') or 'unknown'}"
            for r in not_green
        )
        return _fail(1, f"CI is not green on {args.sha} ({detail})")
    print(f"CI is green on {args.sha} ({len(runs)} run(s))")
    return 0


if __name__ == "__main__":
    sys.exit(main())

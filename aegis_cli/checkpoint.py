"""soma checkpoint — deterministic quality checks (no LLM required).

Checks:
- Test file coverage for implementation files
- Hardcoded absolute paths (/home, /Users, /tmp)
- Assertion density in test files
- Cell fitness scores from .soma/evidence ledger
- Cell convention enforcement (frontmatter, type/dir match)
- Arbitration evidence (un-bypassable review gate)

Supports --pre-commit (warn mode), --strict, --json, --workspace flags.

All check implementations live in aegis_core.verification.checkpoint_checks
to share logic with aegis_mcp without copy-paste.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from aegis_core.verification.checkpoint_checks import (
    CHECK_NAMES,
    run_all_checks,
)
from aegis_cli.base import CommandCategory, SomaCommand

__all__ = ["run_checkpoint", "CheckpointCommand"]


def run_checkpoint(args: argparse.Namespace) -> int:
    """Run deterministic quality checkpoint on a workspace.

    Args:
        args: Parsed CLI arguments with workspace, pre_commit, strict, json.

    Returns:
        Exit code: 0 for pass, 1 for failures.
    """
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    from aegis_core.workspace import Workspace

    ws = getattr(args, "ws", None)
    if ws is None:
        raw_ws = getattr(args, "workspace", None) or getattr(args, "_project_root", None)
        if raw_ws and not os.path.exists(str(raw_ws)):
            root = Path(raw_ws)
        else:
            ws = Workspace.resolve(raw_ws)
            root = ws.root
    else:
        root = ws.root
    workspace = str(root)

    pre_commit = getattr(args, "pre_commit", False)
    strict = getattr(args, "strict", False)
    require_arbitration = getattr(args, "require_arbitration", False)
    use_json = getattr(args, "json", False)

    # Validate workspace exists
    if not root.is_dir():
        msg = f"Error: workspace does not exist: {workspace}"
        if use_json:
            print(json.dumps({
                "status": "error",
                "passed": False,
                "checks": [],
                "issues": [{"check": "workspace", "message": msg}],
            }))
        else:
            print(msg, file=sys.stderr)
        return 1

    # Run all checks (from shared module)
    all_issues = run_all_checks(
        root, strict=strict, require_arbitration=require_arbitration
    )
    has_issues = len(all_issues) > 0

    # Determine exit code
    if has_issues:
        has_gate_issues = any(
            i.get("check") in ("arbitration_evidence", "paper_walls")
            or "wall enforcement" in i.get("message", "").lower()
            for i in all_issues
        )
        if require_arbitration or has_gate_issues or not pre_commit or strict:
            exit_code = 1
        else:
            exit_code = 0  # Warn mode only for non-gate issues
    else:
        exit_code = 0

    # Output
    if use_json:
        output = {
            "status": "failed" if has_issues else "passed",
            "passed": not has_issues,
            "checks": CHECK_NAMES,
            "issues": all_issues,
        }
        print(json.dumps(output, indent=2))
    else:
        if has_issues:
            warn_label = "[WARN]" if (pre_commit and not strict) else "[FAIL]"
            for issue in all_issues:
                print(f"{warn_label} {issue['message']}")
        else:
            print("checkpoint: all checks passed")

    return exit_code


class CheckpointCommand(SomaCommand):
    """Command to run deterministic quality checks."""

    name = "checkpoint"
    category = CommandCategory.WORKFLOW
    help = "Run deterministic quality checks"

    def configure_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--pre-commit",
            action="store_true",
            help="Warn mode: exit 0 even if issues found (unless --strict)",
        )
        parser.add_argument(
            "--strict",
            action="store_true",
            help="In pre-commit mode, exit 1 on issues",
        )
        parser.add_argument(
            "--require-arbitration",
            action="store_true",
            help="Require valid passing arbitration evidence without requiring full --strict",
        )

    def execute(self, args: argparse.Namespace) -> int:
        return run_checkpoint(args)

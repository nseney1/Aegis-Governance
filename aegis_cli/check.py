"""aegis check — Unified verification gate for AI coding agent changes.

Absorbs verify, checkpoint, and pathcheck into a single comprehensive command:
  aegis check               Fast Layer 1 verification on modified files (default)
  aegis check [files...]    Check specific files
  aegis check --hook        Fast pre-commit gate for git hooks
  aegis check --full        Full verification (Layer 1 deterministic + Layer 2 adversarial)
  aegis check --release     Release Gate 4.5 (validates signed SHIP receipt and allowlists)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, List, Optional

from aegis_cli.base import CommandCategory, AegisCommand
from aegis_cli.verify import (
    run_verify,
    resolve_target_files,
    resolve_task_plan,
    discover_test_evidence,
    verdict_to_exit_code,
    verify_release_gate,
)
from aegis_cli.checkpoint import run_checkpoint

__all__ = ["run_check", "CheckCommand"]


def run_check(args: argparse.Namespace) -> int:
    """Execute unified verification gate."""
    # Normalize positional files vs --files
    pos_files = getattr(args, "target_files", None)
    flag_files = getattr(args, "files", None)
    if pos_files and not flag_files:
        args.files = pos_files

    # Mode 1: Release Gate 4.5
    if getattr(args, "release", False) or getattr(args, "release_gate", False):
        args.release_gate = True
        return run_verify(args)

    # Mode 2: Git Pre-Commit Hook mode (--hook)
    if getattr(args, "hook", False):
        args.hook = False
        args.fast = True
        args.fast_mode = True
        args.layer1_only = True
        # If pre_commit is requested, also run checkpoint pre-commit checks
        args.pre_commit = True
        cp_ret = run_checkpoint(args)
        if cp_ret != 0:
            return cp_ret
        return run_verify(args)

    # Mode 3: Checkpoint mode (if explicitly requested via command == checkpoint, flag, or alias)
    cmd_name = getattr(args, "command", None)
    if cmd_name == "checkpoint" or getattr(args, "checkpoint_only", False) or (getattr(args, "pre_commit", False) and not getattr(args, "hook", False)):
        return run_checkpoint(args)

    # Mode 4: Full verification (--full)
    if getattr(args, "full", False):
        args.layer1_only = False
        return run_verify(args)

    # Mode 5: Default (Fast Layer 1 verification)
    if not getattr(args, "full", False) and not getattr(args, "plan", None) and not getattr(args, "plan_file", None):
        args.layer1_only = True
        args.fast = True
        args.fast_mode = True

    return run_verify(args)


class CheckCommand(AegisCommand):
    """Unified verification gate for AI coding agent changes."""

    name = "check"
    aliases = ("verify", "checkpoint")
    category = CommandCategory.WORKFLOW
    help = "Unified verification gate (checks invariants, rules, and outcomes)"

    def configure_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "target_files",
            nargs="*",
            default=None,
            metavar="FILES",
            help="Optional file(s) to verify (defaults to git modified/staged files)",
        )
        parser.add_argument(
            "--files",
            nargs="*",
            default=None,
            help="Explicit list of files to verify",
        )
        parser.add_argument(
            "--hook",
            action="store_true",
            help="Run pre-commit fast gate (used by git pre-commit hook)",
        )
        parser.add_argument(
            "--pre-commit",
            dest="pre_commit",
            action="store_true",
            help="Run pre-commit quality checkpoint checks",
        )
        parser.add_argument(
            "--all",
            dest="all_files",
            action="store_true",
            default=False,
            help="Check all workspace files",
        )
        parser.add_argument(
            "--require-arbitration",
            action="store_true",
            help="Require Layer 2 arbitration evidence",
        )
        parser.add_argument(
            "--full",
            "--deep",
            dest="full",
            action="store_true",
            help="Run full verification (Layer 1 deterministic + Layer 2 adversarial LLM pair)",
        )
        parser.add_argument(
            "--release",
            "--release-gate",
            dest="release_gate",
            action="store_true",
            help="Evaluate Release Gate 4.5 and verify signed SHIP arbitration receipt",
        )

        parser.add_argument(
            "--layer1-only",
            action="store_true",
            help="Run fast deterministic quality checks only (default)",
        )
        parser.add_argument(
            "--no-layer2",
            action="store_true",
            help="Explicitly disable Layer 2 adversarial verification",
        )
        parser.add_argument(
            "--strict",
            action="store_true",
            help="Enforce strict gating (fail on warnings or unobserved cells)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be checked without running or recording evidence",
        )
        parser.add_argument(
            "--plan",
            default=None,
            help="Task plan or prompt context for Layer 2 adversarial verification",
        )
        parser.add_argument(
            "--plan-file",
            default=None,
            help="Path to file containing task plan or prompt context",
        )
        parser.add_argument(
            "--provider",
            default=None,
            help="Inference provider to use (gemini, anthropic, openai, keyring, prompt)",
        )
        parser.add_argument(
            "--in-band",
            action="store_true",
            help="Generate an in-band charge sheet for conversational rebuttal (zero external API keys)",
        )
        parser.add_argument(
            "--checkpoint-only",
            action="store_true",
            help="Run deterministic quality checkpoint only",
        )

    def execute(self, args: argparse.Namespace) -> int:
        return run_check(args)


if __name__ == "__main__":  # pragma: no cover
    from aegis_cli.cli import main
    sys.exit(main(["check"] + sys.argv[1:]))

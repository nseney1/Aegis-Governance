"""aegis check — the verification gate for AI coding agent changes.

  aegis check [FILES...]              Layer 1: workspace checkpoint plus call_graph,
                                      import_guard and forbid_ast on FILES (default: files
                                      changed against HEAD, staged, or the branch base)
  aegis check --strict                also fail on checkpoint warnings
  aegis check --hook                  git pre-commit mode: Layer 1 only, never a model call
  aegis check --full --plan TEXT      add Layer 2: adversarial review by --llm-cmd
"""
from __future__ import annotations

import argparse
import sys

from aegis_cli.base import AegisCommand, CommandCategory
from aegis_cli.verify import run_verify

__all__ = ["CheckCommand", "run_check"]


def run_check(args: argparse.Namespace) -> int:
    """Execute `aegis check`."""
    return run_verify(args)


def _drop_inherited_option(parser: argparse.ArgumentParser, option: str) -> None:
    """Remove *option* inherited from a parent parser so this command can define its own.

    The global parser still defines `--format text|json|mermaid` until the CLI lane
    removes it (D5); `check` owns `--format text|json`. The parent's action object is
    shared by every subcommand, so it is unlinked here rather than modified.
    """
    action = parser._option_string_actions.get(option)
    if action is None:
        return
    for opt in action.option_strings:
        parser._option_string_actions.pop(opt, None)
    if action in parser._actions:
        parser._actions.remove(action)
    for group in parser._action_groups:
        if action in group._group_actions:
            group._group_actions.remove(action)


class CheckCommand(AegisCommand):
    """Unified verification gate for AI coding agent changes."""

    name = "check"
    category = CommandCategory.WORKFLOW
    help = "Verify changes: Layer 1 checks, plus a Layer 2 model review with --full"

    def configure_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "files",
            nargs="*",
            metavar="FILES",
            help="Files to check (default: changed against HEAD, staged, or against the branch base)",
        )
        parser.add_argument(
            "--hook",
            action="store_true",
            help="Git pre-commit mode: Layer 1 only, never a model call",
        )
        parser.add_argument(
            "--strict",
            action="store_true",
            help="Fail on checkpoint warnings too (missing tests, hardcoded paths, stub tests...)",
        )
        parser.add_argument(
            "--full",
            action="store_true",
            help="Add Layer 2: adversarial review of the change by the --llm-cmd model",
        )
        plan = parser.add_mutually_exclusive_group()
        plan.add_argument("--plan", metavar="TEXT", default=None, help="Task plan for Layer 2 (implies --full)")
        plan.add_argument(
            "--plan-file", metavar="PATH", default=None, help="File holding the task plan (implies --full)"
        )
        parser.add_argument(
            "--llm-cmd",
            metavar="CMD",
            default=None,
            help="Layer 2 model command, e.g. 'claude -p': gets the prompt on stdin, prints the reply "
            "(default: $AEGIS_LLM_CMD; never read from repository files)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be checked without running anything",
        )
        _drop_inherited_option(parser, "--format")
        parser.add_argument("--format", choices=("text", "json"), default="text", help="Output format")

    def execute(self, args: argparse.Namespace) -> int:
        return run_check(args)


if __name__ == "__main__":  # pragma: no cover
    from aegis_cli.cli import main
    sys.exit(main(["check"] + sys.argv[1:]))

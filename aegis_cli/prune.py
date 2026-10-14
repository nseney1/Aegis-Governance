"""soma prune — Prune extinct or apoptotic rules."""
from __future__ import annotations

import argparse

from aegis_cli.base import CommandCategory, SomaCommand

__all__ = ["run_prune", "PruneCommand"]


def run_prune(args: argparse.Namespace) -> int:
    """Prune extinct or apoptotic rules."""
    from aegis_core.lifecycle import prune_cells
    dry_run = getattr(args, "dry_run", False)
    execute = getattr(args, "execute", False)
    if dry_run:
        execute = False
    ws = getattr(args, "ws", None) or getattr(args, "workspace", None) or getattr(args, "_project_root", None)
    return prune_cells(workspace=ws, execute=execute)


class PruneCommand(SomaCommand):
    """Command to prune extinct or apoptotic rules."""

    name = "prune"
    category = CommandCategory.LIFECYCLE
    help = "Prune extinct or apoptotic rules"

    def configure_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show candidates without performing pruning (default: true)",
        )
        parser.add_argument(
            "--execute",
            action="store_true",
            help="Actually archive/prune matching rules",
        )

    def execute(self, args: argparse.Namespace) -> int:
        return run_prune(args)

"""aegis scan — which governance rules apply to these files.

The CLI twin of the MCP tool aegis_scan, and the command the AGENTS.md
bootstrap tells agents to run before editing (`aegis scan FILE`). Exit codes
are a contract: 0 when the scan ran (matches or not), 2 for a usage or
workspace error. With --json, stdout carries only the JSON document.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from aegis_cli.base import AegisCommand, CommandCategory
from aegis_core.errors import WorkspaceError

__all__ = ["ScanCommand", "run_scan"]

EXIT_SCANNED = 0
EXIT_USAGE = 2


def _workspace_relative(raw: str, root: Path) -> str:
    """Rule target_paths are relative to the workspace root; the operator types paths relative to cwd."""
    path = Path(raw)
    absolute = path if path.is_absolute() else Path.cwd() / path
    try:
        return Path(os.path.normpath(absolute)).relative_to(root).as_posix()
    except ValueError:
        return raw


def run_scan(args: argparse.Namespace) -> int:
    from aegis_core.workspace import Workspace

    raw_ws = getattr(args, "workspace", None)
    try:
        root = Workspace.resolve(raw_ws).root.resolve()
    except WorkspaceError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return EXIT_USAGE
    if not (root / ".aegis").is_dir():
        print(f"Error: not an Aegis workspace (no .aegis/ in {root}); run aegis init", file=sys.stderr)
        return EXIT_USAGE

    # Wave B2 moves the JIT engine into aegis_core; the CLI must not import aegis_mcp after that.
    from aegis_mcp.jit_engine import express

    files = [_workspace_relative(f, root) for f in args.files]
    result = express(str(root), changed_files=files)
    if getattr(args, "json", False):
        print(json.dumps(result, indent=2, default=str))
    else:
        print(result.get("guidance", ""))
    return EXIT_SCANNED


class ScanCommand(AegisCommand):
    """Show the governance rules that apply to the given files."""

    name = "scan"
    category = CommandCategory.WORKFLOW
    help = "Show which rules apply to the given files (run before editing them)"

    def configure_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("files", nargs="+", metavar="FILE", help="File(s) you are about to edit")

    def execute(self, args: argparse.Namespace) -> int:
        return run_scan(args)

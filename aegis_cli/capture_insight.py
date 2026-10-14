"""soma capture-insight — Capture human insights into evidence and scaffold Wall cells."""
from __future__ import annotations

import argparse
import json
import sys

from aegis_cli.base import CommandCategory, SomaCommand

__all__ = ["run_capture_insight", "CaptureInsightCommand"]


def run_capture_insight(args: argparse.Namespace) -> int:
    """Capture a human insight and persist it to JSONL, optionally scaffolding a Wall cell."""
    from aegis_core.insights import capture_insight

    ws = getattr(args, "ws", None)
    ws_path = str(ws.root) if ws is not None else (getattr(args, "workspace", None) or getattr(args, "_project_root", None) or ".")

    try:
        record = capture_insight(
            workspace=ws_path,
            insight=getattr(args, "insight", ""),
            context_files=getattr(args, "context_files", []),
            source_conversation=getattr(args, "source_conversation", None),
            category=getattr(args, "category", None),
            scaffold_wall=bool(getattr(args, "scaffold_wall", False)),
            wall_id=getattr(args, "wall_id", None),
        )
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if getattr(args, "json", False) or getattr(args, "format", None) == "json":
        print(json.dumps(record, indent=2))
    else:
        wall_msg = f" (scaffolded {record.get('wall_file')})" if record.get("wall_file") else ""
        print(f"Captured insight for {len(record.get('context_files', []))} files{wall_msg}.")
    return 0


class CaptureInsightCommand(SomaCommand):
    """Command to capture human insights into evidence and optionally scaffold a Wall cell."""

    name = "capture-insight"
    category = CommandCategory.LIFECYCLE
    help = "Capture human insight into evidence, optionally scaffolding a Wall cell"

    def configure_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--insight",
            "-i",
            type=str,
            required=True,
            help="Human insight or architectural decision",
        )
        parser.add_argument(
            "--context-files",
            "-c",
            nargs="+",
            required=True,
            help="Files related to this insight",
        )
        parser.add_argument(
            "--source-conversation",
            type=str,
            default=None,
            help="Optional conversation ID or transcript link",
        )
        parser.add_argument(
            "--category",
            type=str,
            default=None,
            help="Insight category (e.g. security, performance, convention)",
        )
        parser.add_argument(
            "--scaffold-wall",
            action="store_true",
            help="Scaffold a new Wall cell from this insight",
        )
        parser.add_argument(
            "--wall-id",
            type=str,
            default=None,
            help="Custom cell ID if scaffolding a Wall",
        )

    def execute(self, args: argparse.Namespace) -> int:
        return run_capture_insight(args)

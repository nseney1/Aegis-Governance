"""soma oracle — cell health classification and recommendations.

Wraps enzymes/oracle_checkpoint.py for CLI access, exposing cell
health diagnostics as a soma subcommand.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from aegis_cli.base import CommandCategory, SomaCommand

__all__ = ["run_oracle", "OracleCommand"]


def run_oracle(args: argparse.Namespace) -> int:
    """Run oracle cell health classification.

    Returns:
        0 if no critical issues, 1 if expired or critically unhealthy cells found.
    """
    from aegis_core.arbitration import generate_checkpoint

    project_root = getattr(args, "workspace", None) or getattr(args, "_project_root", None) or Path.cwd()
    project_root = Path(project_root)

    session_count = getattr(args, "session_count", None)
    use_json = getattr(args, "json", False)

    report = generate_checkpoint(
        workspace=str(project_root),
        session_count=session_count,
    )

    if use_json:
        print(json.dumps(report, indent=2, default=str))
    else:
        _print_report(report)

    # Exit 1 if any critical recommendations
    has_critical = any(
        r.get("severity") == "critical"
        for r in report.get("recommendations", [])
    )
    return 1 if has_critical else 0


def _print_report(report: dict) -> None:
    """Print human-readable oracle report."""
    print()
    print(f"  🔮 Soma Oracle — Cell Health Report")
    print(f"  {'─' * 40}")
    print(f"  Total cells: {report.get('total_cells', 0)}")
    print()

    classifications = report.get("classifications", {})

    icons = {
        "healthy": "✅",
        "active": "⚡",
        "decaying": "🍂",
        "dormant": "💤",
        "unobserved": "🔍",
        "noisy": "📢",
        "expired": "⏰",
    }

    for category in ["healthy", "active", "decaying", "dormant", "unobserved", "noisy", "expired"]:
        cells = classifications.get(category, [])
        if not cells:
            continue
        icon = icons.get(category, "•")
        print(f"  {icon} {category.upper()} ({len(cells)})")
        for cell in cells:
            cell_id = cell.get("cell_id", "unknown")
            details = cell.get("details", "")
            print(f"     {cell_id}: {details}")
        print()

    recommendations = report.get("recommendations", [])
    if recommendations:
        print(f"  📋 Recommendations:")
        for rec in recommendations:
            severity = rec.get("severity", "info")
            message = rec.get("message", "")
            marker = {"critical": "🔴", "warning": "🟡", "info": "ℹ️"}.get(severity, "•")
            print(f"     {marker} {message}")
        print()


class OracleCommand(SomaCommand):
    """Command for cell health classification and recommendations."""

    name = "oracle"
    category = CommandCategory.LIFECYCLE
    help = "Cell health classification and recommendations"

    def configure_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--session-count",
            type=int,
            default=None,
            help="Override session count for expiry calculation",
        )

    def execute(self, args: argparse.Namespace) -> int:
        return run_oracle(args)

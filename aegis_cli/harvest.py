"""soma harvest — retroactively harvest governance telemetry and fitness evidence.

Supports:
- --git: Harvest historical commit diffs from git log to bootstrap initial cell fitness.
- --limit N: Maximum number of commits to inspect (default: 30).
- --dry-run: Simulate harvesting without writing evidence or mutating files.
- --json: Output JSON summary.

Architecture & Safety Guarantees:
- Idempotency: All events are indexed by deterministic idempotency keys ({commit_hash}:trig:{cell_id}),
  preventing duplicate signals across repeated runs.
- Concurrency & Locking: State updates are guarded by evidence_lock() file locking to prevent race conditions.
- Atomic Persistence: Evidence appending and cell frontmatter updates use atomic file replacement,
  preventing state corruption upon pipeline interruption.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from aegis_cli.base import CommandCategory, SomaCommand
from aegis_core.outcomes import harvest_git_history

__all__ = ["run_harvest", "HarvestCommand"]


def run_harvest(args: argparse.Namespace) -> int:
    """Run telemetry harvesting with strict idempotency and lock protection.

    Mitigations for common lifecycle risks:
    - Idempotency: All events use deterministic commit-hash keys ({commit}:trig:{cell})
      to ensure re-harvesting never duplicates records.
    - Concurrency & Cross-Platform Locking: Protected by evidence_lock() providing OS file
      locking with cross-platform fallback and thread reentrancy.
    - Atomic Persistence: Uses atomic rename/replace to prevent state corruption upon interruption.
    """
    project_root = getattr(args, "workspace", None) or getattr(args, "_project_root", None) or Path.cwd()
    project_root = Path(project_root)

    use_git = getattr(args, "git", False)
    limit = getattr(args, "limit", 30) or 30
    dry_run = getattr(args, "dry_run", False)
    use_json = getattr(args, "json", False)

    if not use_git:
        use_git = True

    from aegis_core.telemetry import evidence_lock

    try:
        if not dry_run:
            with evidence_lock(str(project_root)):
                stats = harvest_git_history(
                    workspace=str(project_root),
                    limit=limit,
                    dry_run=dry_run,
                )
        else:
            stats = harvest_git_history(
                workspace=str(project_root),
                limit=limit,
                dry_run=dry_run,
            )
    except Exception as exc:
        print(f"Error: Telemetry harvest failed: {exc}", file=sys.stderr)
        return 1

    if use_json:
        print(json.dumps(stats, indent=2))
        return 0 if not stats.get("error") else 1

    _print_harvest_summary(stats, dry_run=dry_run)
    return 0 if not stats.get("error") else 1


def _print_harvest_summary(stats: dict, dry_run: bool = False) -> None:
    """Print human-readable harvest report."""
    print()
    prefix = "🌾 Soma Harvest (Dry Run)" if dry_run else "🌾 Soma Harvest"
    print(f"  {prefix}")
    print(f"  {'─' * 40}")
    print(f"  Commits inspected: {stats.get('commits_inspected', 0)}")
    print(f"  Cells matched:     {stats.get('cells_matched', 0)}")
    print(f"  Signals minted:    {stats.get('signals_minted', 0)}")
    if stats.get("error"):
        print(f"  Notice:            {stats.get('error')}")
    elif stats.get("signals_minted", 0) > 0 and not dry_run:
        print(f"  ✅ Seeded baseline fitness evidence into .soma/evidence/signals.jsonl")
    print()


class HarvestCommand(SomaCommand):
    """Command to retroactively harvest telemetry and fitness evidence."""

    name = "harvest"
    category = CommandCategory.LIFECYCLE
    help = "Retroactively harvest telemetry and fitness evidence"

    def configure_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--git",
            action="store_true",
            default=True,
            help="Harvest signals from git log history (default: True)",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=30,
            help="Max commits to inspect (default: 30)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Preview harvested signals without writing evidence",
        )

    def execute(self, args: argparse.Namespace) -> int:
        return run_harvest(args)

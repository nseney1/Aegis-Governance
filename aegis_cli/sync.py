"""soma sync — reconcile canonical JSONL evidence with cell frontmatter.

Reads .soma/evidence/signals.jsonl, aggregates trigger/tp/fp signals per
cell, and updates cell frontmatter fitness blocks. Idempotent — can be run
repeatedly.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
import tempfile
from typing import Optional

from aegis_cli import resolve_root
from aegis_cli.base import CommandCategory, AegisCommand
from aegis_core.evidence import aggregate_signals
from aegis_core.sync import aggregate_evidence, sync_frontmatter

__all__ = ["run_sync", "SyncCommand"]


def run_sync(args: argparse.Namespace) -> int:
    """CLI entrypoint for soma sync."""
    root = resolve_root(args)
    evidence_dir = str((root / ".aegis" / "evidence") if (root / ".aegis" / "evidence").is_dir() else (root / ".soma" / "evidence"))
    cells_dir = str((root / ".aegis" / "rules") if (root / ".aegis" / "rules").is_dir() else ((root / ".soma" / "rules") if (root / ".soma" / "rules").is_dir() else (root / ".soma" / "cells")))

    dry_run = getattr(args, "dry_run", False)
    as_json = getattr(args, "json", False)

    aggregation = aggregate_signals(evidence_dir)
    counts = aggregation.counts
    errors: list[dict] = list(aggregation.errors)
    if not counts and not errors:
        if as_json:
            print(json.dumps({
                "status": "ok", "changes": [], "errors": [],
                "dry_run": dry_run,
            }, indent=2))
        else:
            print(f"No evidence found in {evidence_dir}")
        return 0

    if errors:
        if as_json:
            print(json.dumps({
                "status": "error", "changes": [], "errors": errors,
                "dry_run": dry_run,
            }, indent=2))
        else:
            for error in errors:
                subject = error.get("file", "evidence")
                detail = error.get("error", "unknown error")
                if error.get("line") is not None:
                    detail = f"line {error['line']}: {detail}"
                print(f"  ! {subject}: {detail}", file=sys.stderr)
            print(
                f"Sync failed for {len(errors)} evidence rows.",
                file=sys.stderr,
            )
        return 1

    changes = sync_frontmatter(
        cells_dir, counts, dry_run=dry_run, errors=errors
    )

    if as_json:
        print(json.dumps({
            "status": "error" if errors else "ok",
            "changes": changes,
            "errors": errors,
            "dry_run": dry_run,
        }, indent=2))
        return 1 if errors else 0

    for error in errors:
        subject = error.get("cell_id") or error.get("file", "evidence")
        detail = error.get("error") or error.get("message", "unknown error")
        if error.get("line") is not None:
            detail = f"line {error['line']}: {detail}"
        print(f"  ! {subject}: {detail}", file=sys.stderr)

    verb = "Would update" if dry_run else "Updated"
    if not changes and not errors:
        print("All cells already in sync with evidence.")
        return 0

    for change in changes:
        print(
            f"  ✓ {change['cell_id']}: triggers {change['triggers']}, "
            f"tp {change['tp']}, fp {change['fp']} → score={change['score']}"
        )

    if changes:
        print(f"\n{verb} {len(changes)} cells.")
    if errors:
        print(f"Sync failed for {len(errors)} cells.", file=sys.stderr)
        return 1
    return 0


class SyncCommand(AegisCommand):
    """Command to reconcile canonical JSONL evidence with cell frontmatter."""

    name = "sync"
    category = CommandCategory.WORKFLOW
    help = "Reconcile evidence JSONL with cell frontmatter"

    def configure_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would change without writing",
        )

    def execute(self, args: argparse.Namespace) -> int:
        return run_sync(args)

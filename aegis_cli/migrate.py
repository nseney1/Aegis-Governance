"""aegis migrate: convert a v3 workspace or .soma cells to the v4 layout (dry run by default).

The work is aegis_core.migrate; this module parses flags and prints the plan.
Exit codes: 0 done (or nothing to do), 1 something was left unmigrated (an unmapped
type, a destination conflict or an unreadable file), 2 usage error.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Dict

from aegis_cli.base import AegisCommand, CommandCategory

__all__ = ["MigrateCommand", "run_migrate"]


def _print_report(report: Dict[str, Any], applied: bool, backup: Any) -> None:
    root = report["root"]
    if report["status"] == "up_to_date":
        print(f"aegis migrate: {root} is already on the v4 layout; nothing to do.")
    elif applied:
        print(f"aegis migrate: migrated {root} (backup: {backup})")
    else:
        print(f"aegis migrate: {root} (dry run: nothing written; rerun with --apply)")
    ledger = report["ledger"]
    if ledger:
        print(
            f"  ledger: {ledger['rows']} v2 row(s) from {', '.join(ledger['sources'])} "
            f"({ledger['duplicates']} duplicate, {ledger['unusable_rows']} unusable, "
            f"{ledger['skipped_lines']} unreadable line(s))"
        )
    if report["config_sources"]:
        print(f"  config: .aegis/config.json from {', '.join(report['config_sources'])}")
    for move in report["rules"]:
        print(f"  rule: {move['from']} -> {move['to']} (type {move['type']})")
    for strip in report["strip"]:
        print(f"  strip: {', '.join(strip['keys'])} from {strip['path']}")
    for path in report["remove"]:
        print(f"  remove (backed up first): {path}")
    for line in report["dropped"]:
        print(f"  dropped: {line}")
    for entry in report["unmapped"]:
        print(f"  ! unmapped type {entry['type']!r}: {entry['path']} left in place (no canonical type; not guessed)")
    for entry in report["conflicts"]:
        print(f"  ! {entry['to']} already exists: {entry['path']} left in place")
    for path in report["unreadable"]:
        print(f"  ! cannot read {path}: left in place")
    for path in report["left_in_place"]:
        print(f"  note: {path} is not part of the v4 layout; left in place")
    if report["user_config"]:
        print("  For ~/.aegis/config.json (not written: a repository cannot name commands or set slots):")
        print("    " + json.dumps(report["user_config"], indent=2).replace("\n", "\n    "))


def run_migrate(args: argparse.Namespace) -> int:
    """CLI handler for aegis migrate."""
    from aegis_core import migrate

    root = Path(getattr(args, "workspace", None) or getattr(args, "_project_root", None) or Path.cwd())
    if not root.is_dir():
        print(f"Error: workspace path does not exist: {root}", file=sys.stderr)
        return 2
    plan = migrate.plan(root)
    apply_it = bool(getattr(args, "apply", False))
    report = plan.to_dict()  # before applying: the report describes what was planned
    backup = None
    if apply_it:
        backup = migrate.apply(plan).backup
    if apply_it and report["status"] == "pending":
        report["status"] = "applied"
    report["backup"] = str(backup) if backup else None
    if getattr(args, "json", False):
        print(json.dumps(report, indent=2))
    else:
        _print_report(report, apply_it and backup is not None, backup)
    left_behind = report["unmapped"] or report["conflicts"] or report["unreadable"]
    return 1 if apply_it and left_behind else 0


class MigrateCommand(AegisCommand):
    """Convert a v3 workspace or legacy .soma cells to the v4 layout."""

    name = "migrate"
    aliases = ()
    category = CommandCategory.SETUP
    help = "Convert a v3 or .soma workspace to the v4 layout (dry run unless --apply)"
    description = (
        "Plan, then with --apply perform, the move to the v4 layout: the v3 ledger becomes "
        ".aegis/state/ledger.jsonl (v2 rows), aegis.conf/slots.yaml/config.yaml become "
        ".aegis/config.json, .soma cells move to .aegis/rules/<type>/, derived counters leave "
        "rule frontmatter and v3 runtime state is removed. Every changed file is backed up to "
        ".aegis/state/migrate-backup-<time>/ first; running it again changes nothing."
    )

    def configure_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--apply", action="store_true", help="Perform the migration (default: dry run)")
        parser.add_argument("--dry-run", action="store_true", help="Only report what would change (the default)")

    def execute(self, args: argparse.Namespace) -> int:
        if getattr(args, "apply", False) and getattr(args, "dry_run", False):
            print("Error: --apply and --dry-run are mutually exclusive", file=sys.stderr)
            return 2
        return run_migrate(args)

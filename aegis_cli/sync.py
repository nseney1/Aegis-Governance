"""aegis sync — rebuild derived state from the rules and the ledger, and suggest transitions.

`aegis sync` writes .aegis/state/derived.json (fitness, triggers and a suggested
promote/demote/archive for every rule) and changes no rule file. `aegis sync --apply`
also applies the suggestions; it is the only command that moves rules in bulk
(ADR 0005 D1). Exit codes: 0 done, 1 a rule file cannot be loaded or applying was
refused or failed, 2 usage or workspace error. With --json, stdout carries only the
JSON document.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, List

from aegis_cli import sanitize_display
from aegis_cli.base import AegisCommand, CommandCategory
from aegis_core.errors import AegisError

__all__ = ["SyncCommand", "run_sync"]

EXIT_OK = 0
EXIT_PROBLEMS = 1
EXIT_USAGE = 2
_APPLIED_OK = frozenset({"promoted", "demoted", "archived"})


def _rows(derived: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [dict(entry, id=rule_id) for rule_id, entry in sorted(derived["rules"].items())]


def _status(result: Any) -> str:
    if result.refused:
        return "refused"
    if result.derived["errors"]:
        return "errors"
    return "applied" if result.applied else "synced"


def _print_text(args: argparse.Namespace, result: Any, rel_path: str) -> None:
    from aegis_cli.ui.table import Table
    from aegis_cli.ui.theme import OutputContext

    existing = getattr(args, "ui", None)
    ui = existing if isinstance(existing, OutputContext) else OutputContext.from_env_and_args(args)
    rows = _rows(result.derived)
    if rows:
        tbl = Table(ctx=ui)
        for column in ("Rule", "Type", "Fitness", "Triggers", "TP", "FP", "Suggestion"):
            tbl.add_column(column, no_wrap=True)
        for row in rows:
            tbl.add_row(
                sanitize_display(str(row["id"])), ui.color_rule_type(str(row["type"])), f"{row['fitness']:.2f}",
                str(row["triggers"]), f"{row['tp']:g}", f"{row['fp']:g}", row["suggestion"] or "—",
            )
        for line in tbl.render(ui).splitlines():
            print(f"  {line}")
    for error in result.derived["errors"]:
        print(f"  ❌ {sanitize_display(error['path'])}: {sanitize_display(error['error'], 300)}")
    for ignored in result.derived["ignored"]:
        print(f"  ⚠️  {sanitize_display(ignored['path'])}: {ignored['reason']}")
    for action in result.applied:
        detail = f" ({action['from_type']} -> {action['to_type']})" if action.get("to_type") else ""
        print(f"  {action['action']} {sanitize_display(action['rule'])}: {action['status']}{detail}")
    if result.refused:
        print(f"  ❌ {result.refused}")
    pending = sum(1 for row in rows if row["suggestion"])
    print(f"Wrote {rel_path} ({len(rows)} rules, {pending} suggested transitions).")
    if pending and not result.applied and not result.refused:
        print("Apply the suggestions with: aegis sync --apply")


def run_sync(args: argparse.Namespace) -> int:
    from aegis_core.sync import sync
    from aegis_core.workspace.base import Workspace
    from aegis_core.workspace.layout import is_aegis_workspace

    raw_ws = getattr(args, "workspace", None)
    if raw_ws and not os.path.exists(raw_ws):
        print(f"Error: workspace path does not exist: {raw_ws}", file=sys.stderr)
        return EXIT_USAGE
    try:
        root = Workspace.resolve(raw_ws).root.resolve()
    except AegisError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return EXIT_USAGE
    if not is_aegis_workspace(root):
        print(f"Error: not an Aegis workspace (no .aegis/ in {root}); run aegis init", file=sys.stderr)
        return EXIT_USAGE

    try:
        result = sync(root, apply=getattr(args, "apply", False))
    except (AegisError, RuntimeError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return EXIT_PROBLEMS

    rel_path = result.path.relative_to(root).as_posix()
    failed = [a for a in result.applied if a["status"] not in _APPLIED_OK]
    rc = EXIT_PROBLEMS if (result.refused or result.derived["errors"] or failed) else EXIT_OK
    if getattr(args, "json", False):
        print(json.dumps({
            "status": _status(result),
            "path": rel_path,
            "synced_at": result.derived["synced_at"],
            "rules": _rows(result.derived),
            "applied": result.applied,
            "refused": result.refused,
            "errors": result.derived["errors"],
            "ignored": result.derived["ignored"],
        }, indent=2, default=str))
    else:
        _print_text(args, result, rel_path)
    return rc


class SyncCommand(AegisCommand):
    """Rebuild derived rule state and suggest lifecycle transitions."""

    name = "sync"
    category = CommandCategory.LIFECYCLE
    help = "Rebuild rule fitness from the ledger and suggest promotions (--apply to apply them)"

    def configure_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--apply", action="store_true",
            help="Apply the suggested promote/demote/archive transitions (moves rule files)",
        )

    def execute(self, args: argparse.Namespace) -> int:
        return run_sync(args)

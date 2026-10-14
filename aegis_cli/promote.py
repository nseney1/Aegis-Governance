"""soma promote — evaluate and display cell promotion candidates."""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

from aegis_cli.base import CommandCategory, SomaCommand


from aegis_core.lifecycle import (
    PROMOTION_PATH,
    TYPE_TO_DIR,
    find_cell_file,
    promote_cell,
)

__all__ = ["run_promote", "PromoteCommand"]


def _force_promote(project_root: Path, cell_id: str, dry_run: bool, use_json: bool) -> int:
    """Force-promote a specific cell, bypassing evidence thresholds."""
    res = promote_cell(project_root, cell_id, force=True, dry_run=dry_run)
    status = res.get("status")

    if status == "not_found":
        msg = f"Cell '{cell_id}' not found in {project_root / '.soma' / 'cells'}"
        if use_json:
            print(json.dumps({"error": msg}))
        else:
            print(f"  ❌ {msg}")
        return 1

    if status == "already_terminal":
        msg = f"Cell '{cell_id}' is already at terminal promotion level ('{res.get('current_type')}')"
        if use_json:
            print(json.dumps({"info": msg}))
        else:
            print(f"  ℹ️  {msg}")
        return 0

    if status == "target_exists":
        msg = res.get("message", "Target already exists")
        if use_json:
            print(json.dumps({"error": msg}))
        else:
            print(msg)
        return 1

    if status == "dry_run":
        if use_json:
            print(json.dumps({"action": "promote", "cell_id": cell_id,
                             "from": res["from_type"], "to": res["to_type"], "dry_run": True}))
        else:
            print(f"  🧬 Would promote: {cell_id}: {res['from_type']} → {res['to_type']}")
            print(f"     {res['source_path']} → {res['target_path']}")
        return 0

    if status == "promoted":
        if use_json:
            print(json.dumps({"action": "promote", "cell_id": cell_id,
                             "from": res["from_type"], "to": res["to_type"]}))
        else:
            print(f"  ✅ Promoted: {cell_id}: {res['from_type']} → {res['to_type']}")
        return 0

    msg = res.get("message", "Promotion failed")
    if use_json:
        print(json.dumps({"error": msg}))
    else:
        print(f"  ❌ {msg}")
    return 1


def run_promote(args: argparse.Namespace) -> int:
    """Evaluate promotion candidates and display results.
    
    Returns 0 always (dry-run is advisory).
    """
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    from aegis_core.workspace import Workspace

    ws = getattr(args, "ws", None) or Workspace.resolve(
        getattr(args, "workspace", None) or getattr(args, "_project_root", None)
    )
    project_root = ws.root
    use_json = getattr(args, "json", False)
    dry_run = getattr(args, "dry_run", False)
    force = getattr(args, "force", False)
    cell_id = getattr(args, "cell", None)

    if getattr(args, "tier_check", False):
        from aegis_core.lifecycle import evaluate_cell_tiers
        res = evaluate_cell_tiers(project_root, execute=not dry_run)
        if use_json:
            print(json.dumps(res, indent=2))
        else:
            changes = res.get("changes", [])
            print(f"  🧬 Evaluated {res.get('evaluated', 0)} cells across enforcement tiers.")
            if not changes:
                print("  No tier changes required.")
            else:
                for c in changes:
                    print(f"    {c['cell']}: {c['old_tier']} → {c['new_tier']} ({c['reason']})")
        return 0

    if getattr(args, 'cell', None) and not getattr(args, 'force', False):
        print("Warning: --cell requires --force; running normal evaluation", file=sys.stderr)

    if force:
        if not cell_id:
            msg = "--force requires --cell <cell-id>"
            if use_json:
                print(json.dumps({"error": msg}))
            else:
                print(f"  ❌ {msg}")
            return 1
        return _force_promote(project_root, cell_id, dry_run, use_json)

    from aegis_core.lifecycle import evaluate_promotions

    candidates = evaluate_promotions(str(project_root))
    
    if use_json:
        print(json.dumps({"candidates": candidates}, indent=2, default=str))
    else:
        if not candidates:
            print("  No promotion candidates found.")
        else:
            print(f"  🧬 Promotion Candidates ({len(candidates)}):")
            print()
            for c in candidates:
                print(f"    {c['cell_id']}: {c['from_type']} → {c['to_type']}")
                print(f"      triggers={c['triggers']} tp_rate={c['tp_rate']:.0%} age={c['age_days']}d")
            print()
    
    return 0


class PromoteCommand(SomaCommand):
    """Command to evaluate and execute cell promotion candidates."""

    name = "promote"
    category = CommandCategory.LIFECYCLE
    help = "Evaluate cell promotion candidates"

    def configure_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show candidates without performing promotions",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Force promotion of --cell, bypassing evidence thresholds",
        )
        parser.add_argument(
            "--cell",
            type=str,
            default=None,
            help="Target cell ID for --force promotion",
        )
        parser.add_argument(
            "--tier-check",
            action="store_true",
            help="Evaluate enforcement tier transitions and apply decay",
        )

    def execute(self, args: argparse.Namespace) -> int:
        return run_promote(args)


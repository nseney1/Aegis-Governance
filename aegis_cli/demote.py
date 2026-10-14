"""soma demote — evaluate and display cell demotion candidates."""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

from aegis_cli.base import CommandCategory, SomaCommand


from aegis_core.lifecycle import (
    DEMOTION_PATH,
    PROTECTED_RULES,
    TYPE_TO_DIR,
    demote_cell,
    find_cell_file,
)


__all__ = ["run_demote", "DemoteCommand"]


def _force_demote(project_root: Path, cell_id: str, dry_run: bool, use_json: bool) -> int:
    """Force-demote a specific cell, bypassing evidence thresholds."""
    try:
        res = demote_cell(project_root, cell_id, dry_run=dry_run)
    except ValueError as exc:
        msg = f"Cannot demote core rule: {cell_id}. Only promoted cells can be demoted."
        if use_json:
            print(json.dumps({"error": msg}))
        else:
            print(f"  ❌ {msg}")
        return 1
    except Exception as exc:
        msg = f"Demotion error: {exc}"
        if use_json:
            print(json.dumps({"error": msg}))
        else:
            print(f"  ❌ {msg}")
        return 1

    status = res.get("status")
    if status == "not_found":
        msg = f"Cell '{cell_id}' not found in {project_root / '.soma' / 'cells'} or {project_root / 'genome'}"
        if use_json:
            print(json.dumps({"error": msg}))
        else:
            print(f"  ❌ {msg}")
        return 1

    if status == "already_base":
        msg = f"Cell '{cell_id}' is already at '{res.get('current_type')}' (minimum tier, cannot demote)"
        if use_json:
            print(json.dumps({"error": msg}))
        else:
            print(f"  ⚠️  {msg}")
        return 1

    if status == "target_exists":
        msg = res.get("message", "Target already exists")
        if use_json:
            print(json.dumps({"error": msg}))
        else:
            print(msg)
        return 1

    if status == "dry_run":
        if use_json:
            print(json.dumps({"action": "demote", "cell_id": cell_id,
                             "from": res["from_type"], "to": res["to_type"], "dry_run": True}))
        else:
            print(f"  🧬 Would demote: {cell_id}: {res['from_type']} → {res['to_type']}")
            print(f"     {res['source_path']} → {res['target_path']}")
        return 0

    if status == "demoted":
        if use_json:
            print(json.dumps({"action": "demote", "cell_id": cell_id,
                             "from": res["from_type"], "to": res["to_type"]}))
        else:
            print(f"  ✅ Demoted: {cell_id}: {res['from_type']} → {res['to_type']}")
        return 0

    msg = res.get("message", "Demotion failed")
    if use_json:
        print(json.dumps({"error": msg}))
    else:
        print(f"  ❌ {msg}")
    return 1


def run_demote(args: argparse.Namespace) -> int:
    """Evaluate demotion candidates and display results.
    
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
        return _force_demote(project_root, cell_id, dry_run, use_json)

    from aegis_core.lifecycle import evaluate_demotions

    candidates = evaluate_demotions(str(project_root))
    
    if use_json:
        print(json.dumps({"candidates": candidates}, indent=2, default=str))
    else:
        if not candidates:
            print("  No demotion candidates found.")
        else:
            print(f"  ⚠️  Demotion Candidates ({len(candidates)}):")
            print()
            for c in candidates:
                print(f"    {c['cell_id']}: {c['from_type']} → {c['to_type']} ({c['reason']})")
                if c['triggers'] > 0:
                    print(f"      triggers={c['triggers']} fp_rate={c['fp_rate']:.0%}")
                else:
                    print(f"      dormant for {c['age_days']}d")
            print()
    
    return 0


class DemoteCommand(SomaCommand):
    """Command to evaluate and execute cell demotion candidates."""

    name = "demote"
    category = CommandCategory.LIFECYCLE
    help = "Evaluate cell demotion candidates"

    def configure_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show candidates without performing demotions",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Force demotion of --cell, bypassing evidence thresholds",
        )
        parser.add_argument(
            "--cell",
            type=str,
            default=None,
            help="Target cell ID for --force demotion",
        )

    def execute(self, args: argparse.Namespace) -> int:
        return run_demote(args)

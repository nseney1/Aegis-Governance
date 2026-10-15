"""aegis rule — Unified rule lifecycle management.

Subcommands:
  aegis rule list                 List active workspace rules and fitness scores
  aegis rule promote <rule_id>    Promote a rule up lifecycle tiers
  aegis rule demote <rule_id>     Demote a rule down lifecycle tiers
  aegis rule archive [rule_id]    Archive decayed, extinct, or quarantined rules
  aegis rule clean                Prune leaked or redundant rules
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, List, Optional

from aegis_cli.base import CommandCategory, AegisCommand
from aegis_core.taxonomy import RULE_TYPE_DIRS
from aegis_core.workspace import Workspace
from aegis_core.workspace.layout import WorkspaceLayout
from aegis_core.lifecycle import (
    promote_cell, demote_cell, prune_cells, find_cell_file,
    evaluate_promotions, evaluate_demotions, evaluate_cell_tiers,
)
from aegis_core.lifecycle.cleanse import (
    AEGIS_INTERNAL_PURGE_STEMS, UNIVERSAL_TENETS, _clean_claude_sections,
    clean_global_rules, collect_workspace_rules, format_cleanse_report, is_purge_candidate,
)

__all__ = [
    "run_rule", "RuleCommand", "run_promote", "run_demote", "_force_promote",
    "_force_demote", "clean_global_rules", "run_clean_rules", "UNIVERSAL_TENETS",
    "AEGIS_INTERNAL_PURGE_STEMS", "is_purge_candidate", "_clean_claude_sections",
]


def run_rule(args: argparse.Namespace) -> int:
    """Entrypoint for aegis rule subcommands."""
    action = getattr(args, "rule_action", None) or "list"
    handlers = {
        "list": _run_list, "create": _run_create, "promote": _run_promote,
        "demote": _run_demote, "archive": _run_archive, "clean": _run_clean,
    }
    if action not in handlers:
        print(f"Unknown rule subcommand: {action}", file=sys.stderr)
        return 1
    return handlers[action](args)


def _resolve_workspace_root(args: argparse.Namespace) -> Path:
    ws_obj = getattr(args, "ws", None)
    if ws_obj is not None:
        return ws_obj.root
    raw = getattr(args, "workspace", None) or getattr(args, "_project_root", None) or getattr(args, "_root", None)
    return Path(raw).resolve() if raw else Workspace.resolve().root


def _run_list(args: argparse.Namespace) -> int:
    """List active rules and fitness metrics."""
    root = _resolve_workspace_root(args)
    rules_dir = WorkspaceLayout(root).rules_dir
    if not rules_dir.is_dir():
        print(json.dumps([]) if getattr(args, "json", False) else "No rules directory found.")
        return 0

    rules = collect_workspace_rules(
        root, rules_dir, getattr(args, "type", None), getattr(args, "min_fitness", None)
    )
    if getattr(args, "json", False):
        print(json.dumps(rules, indent=2))
        return 0
    if not rules:
        print("No matching rules found.")
        return 0

    from aegis_cli.ui.table import Table
    from aegis_cli.ui.theme import OutputContext

    existing_ui = getattr(args, "ui", None)
    ui = existing_ui if isinstance(existing_ui, OutputContext) else OutputContext.from_env_and_args(args)
    tbl = Table(ctx=ui)
    for col in ("Rule ID", "Type", "Enforcement"):
        tbl.add_column(col, no_wrap=True)
    tbl.add_column("Fitness", justify="right", no_wrap=True)
    for r in rules:
        score_str = ui.color_fitness(float(r["score"])) if isinstance(r.get("score"), (int, float)) else "—"
        tbl.add_row(str(r["id"]), ui.color_rule_type(str(r["type"])), str(r["enforcement"]), score_str)

    print(f"Active Rules ({len(rules)} found):")
    for line in tbl.render(ui).splitlines():
        print(f"  {line}")
    return 0


def _emit_status(use_json: bool, payload: dict[str, Any], text: str, rc: int) -> int:
    print(json.dumps(payload) if use_json else text)
    return rc


def _resolve_rule_id(args: argparse.Namespace) -> str | None:
    return getattr(args, "rule", None) or getattr(args, "rule_id", None) or getattr(args, "cell", None) or getattr(args, "cell_id", None)


def _run_promote(args: argparse.Namespace) -> int:
    """Promote a rule up lifecycle tiers or evaluate promotion candidates."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    root = _resolve_workspace_root(args)
    rule_id = _resolve_rule_id(args)
    dry_run = getattr(args, "dry_run", False)
    use_json = getattr(args, "json", False)

    if getattr(args, "tier_check", False):
        res = evaluate_cell_tiers(root, execute=not dry_run)
        if use_json:
            print(json.dumps(res, indent=2))
        else:
            changes = res.get("changes", [])
            print(f"  Evaluated {res.get('evaluated', 0)} rules across enforcement tiers.")
            if not changes:
                print("  No tier changes required.")
            for c in changes:
                print(f"    {c['cell']}: {c['old_tier']} → {c['new_tier']} ({c['reason']})")
        return 0

    if not rule_id:
        candidates = evaluate_promotions(str(root))
        if use_json:
            print(json.dumps({"candidates": candidates}, indent=2, default=str))
        elif not candidates:
            print("  No promotion candidates found.")
        else:
            print(f"  Promotion Candidates ({len(candidates)}):\n")
            for c in candidates:
                print(f"    {c['cell_id']}: {c['from_type']} → {c['to_type']}\n      triggers={c['triggers']} tp_rate={c['tp_rate']:.0%} age={c['age_days']}d")
            print()
        return 0

    res = promote_cell(root, rule_id, force=True, dry_run=dry_run)
    status = res.get("status")
    if status == "not_found":
        msg = f"Rule '{rule_id}' not found in workspace"
        return _emit_status(use_json, {"error": msg}, f"  ❌ {msg}", 1)
    if status == "already_terminal":
        msg = f"Rule '{rule_id}' is already at terminal tier ('{res.get('current_type')}')"
        return _emit_status(use_json, {"info": msg}, f"  ℹ️  {msg}", 0)
    if status == "target_exists":
        msg = res.get("message", "Target already exists")
        return _emit_status(use_json, {"error": msg}, f"  ❌ {msg}", 1)

    from_t, to_t = res.get("from_type"), res.get("to_type")
    if dry_run:
        return _emit_status(use_json, {"action": "promote", "rule_id": rule_id, "from": from_t, "to": to_t, "dry_run": True}, f"  🔍 Would promote: {rule_id}: {from_t} → {to_t}", 0)
    return _emit_status(use_json, {"action": "promote", "rule_id": rule_id, "from": from_t, "to": to_t, "success": True}, f"  ✅ Promoted: {rule_id}: {from_t} → {to_t}", 0)


def _run_demote(args: argparse.Namespace) -> int:
    """Demote a rule down lifecycle tiers or evaluate demotion candidates."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    root = _resolve_workspace_root(args)
    rule_id = _resolve_rule_id(args)
    dry_run = getattr(args, "dry_run", False)
    use_json = getattr(args, "json", False)

    if not rule_id:
        candidates = evaluate_demotions(str(root))
        if use_json:
            print(json.dumps({"candidates": candidates}, indent=2, default=str))
        elif not candidates:
            print("  No demotion candidates found.")
        else:
            print(f"  ⚠️  Demotion Candidates ({len(candidates)}):\n")
            for c in candidates:
                detail = f"triggers={c['triggers']} fp_rate={c.get('fp_rate', 0):.0%}" if c.get("triggers", 0) > 0 else f"dormant for {c.get('age_days', 0)}d"
                print(f"    {c['cell_id']}: {c['from_type']} → {c['to_type']} ({c['reason']})\n      {detail}")
            print()
        return 0

    try:
        res = demote_cell(root, rule_id, dry_run=dry_run)
    except ValueError:
        msg = f"Cannot demote core rule: {rule_id}."
        return _emit_status(use_json, {"error": msg}, f"  ❌ {msg}", 1)
    except Exception as exc:
        msg = f"Demotion error: {exc}"
        return _emit_status(use_json, {"error": msg}, f"  ❌ {msg}", 1)

    status = res.get("status")
    if status == "not_found":
        msg = f"Rule '{rule_id}' not found in workspace"
        return _emit_status(use_json, {"error": msg}, f"  ❌ {msg}", 1)
    if status == "already_base":
        msg = f"Rule '{rule_id}' is already at base tier ('{res.get('current_type')}')"
        return _emit_status(use_json, {"error": msg}, f"  ⚠️  {msg}", 1)

    from_t, to_t = res.get("from_type"), res.get("to_type")
    if dry_run:
        return _emit_status(use_json, {"action": "demote", "rule_id": rule_id, "from": from_t, "to": to_t, "dry_run": True}, f"  🔍 Would demote: {rule_id}: {from_t} → {to_t}", 0)
    return _emit_status(use_json, {"action": "demote", "rule_id": rule_id, "from": from_t, "to": to_t, "success": True}, f"  ✅ Demoted: {rule_id}: {from_t} → {to_t}", 0)


def _force_promote(project_root: Path, cell_id: str, dry_run: bool = False, use_json: bool = False) -> int:
    return _run_promote(argparse.Namespace(_project_root=project_root, rule_id=cell_id, dry_run=dry_run, json=use_json, force=True))


def _force_demote(project_root: Path, cell_id: str, dry_run: bool = False, use_json: bool = False) -> int:
    return _run_demote(argparse.Namespace(_project_root=project_root, rule_id=cell_id, dry_run=dry_run, json=use_json, force=True))


run_promote = _run_promote
run_demote = _run_demote


def _run_archive(args: argparse.Namespace) -> int:
    """Archive extinct or decayed rules."""
    root = _resolve_workspace_root(args)
    execute = not getattr(args, "dry_run", False) and getattr(args, "apply", True)
    return prune_cells(workspace=root, execute=execute)


def _run_clean(args: argparse.Namespace) -> int:
    """Clean redundant or leaked global rules."""
    dry_run = getattr(args, "dry_run", False)
    apply = getattr(args, "apply", False) or getattr(args, "force", False)
    force = apply and not dry_run
    q_dir = getattr(args, "quarantine_dir", "") or None
    res = clean_global_rules(dry_run=not force, force=force, quarantine_dir=q_dir)
    print(format_cleanse_report(res))
    return 0


run_clean_rules = _run_clean


def _split_csv_arg(raw: Any) -> list[str] | None:
    if isinstance(raw, list):
        return raw
    if isinstance(raw, str) and raw.strip():
        return [item.strip() for item in raw.split(",") if item.strip()]
    return None


def _run_create(args: argparse.Namespace) -> int:
    """Create a new governance rule in the workspace."""
    from aegis_core.lifecycle.creation import create_cell
    root = _resolve_workspace_root(args)
    cell_type = getattr(args, "type", None) or getattr(args, "cell_type", None) or "trap"
    hypothesis = getattr(args, "hypothesis", "") or getattr(args, "description", "")
    if not hypothesis:
        print("Error: --hypothesis is required to create a rule.", file=sys.stderr)
        return 1
    rule_id = getattr(args, "id", None) or getattr(args, "cell_id", None) or None
    try:
        created = create_cell(
            cell_type=cell_type, hypothesis=hypothesis, prediction=getattr(args, "prediction", "") or "",
            falsification=getattr(args, "falsification", "") or "", weight=float(getattr(args, "weight", 1.0) or 1.0),
            tags=_split_csv_arg(getattr(args, "tags", None)), expiry_sessions=getattr(args, "expiry_sessions", 15),
            expiry_days=getattr(args, "expiry_days", 60), minimum_mode=getattr(args, "minimum_mode", "") or "",
            id_override=rule_id, effector=bool(getattr(args, "effector", False)), memory=bool(getattr(args, "memory", False)),
            target_paths=_split_csv_arg(getattr(args, "target_paths", None)), domain=getattr(args, "domain", "correctness") or "correctness",
            workspace=root, enforcement=getattr(args, "enforcement", None),
        )
    except Exception as exc:
        print(json.dumps({"error": str(exc), "status": "error"}) if getattr(args, "json", False) else f"Error: {exc}", file=sys.stdout if getattr(args, "json", False) else sys.stderr)
        return 1
    print(json.dumps({"status": "created", "path": str(created), "id": created.stem}, indent=2) if getattr(args, "json", False) else f"Created rule: {created}")
    return 0


class RuleCommand(AegisCommand):
    """Unified rule lifecycle management."""

    name = "rule"
    aliases = ()
    category = CommandCategory.LIFECYCLE
    help = "Manage rule lifecycle (list, create, promote, demote, archive, clean)"

    def configure_parser(self, parser: argparse.ArgumentParser) -> None:
        common = argparse.ArgumentParser(add_help=False)
        for flag in ("--plain", "--no-emoji", "--json"):
            common.add_argument(flag, action="store_true", default=argparse.SUPPRESS)
        common.add_argument("--format", choices=["text", "json", "mermaid"], default=argparse.SUPPRESS)
        common.add_argument("-v", "--verbose", action="store_true", default=argparse.SUPPRESS)
        common.add_argument("-q", "--quiet", action="store_true", default=argparse.SUPPRESS)
        common.add_argument("--workspace", type=str, default=argparse.SUPPRESS)
        sub = parser.add_subparsers(dest="rule_action", metavar="ACTION")

        p_list = sub.add_parser("list", parents=[common], help="List active rules and fitness metrics")
        p_list.add_argument("--type", choices=list(RULE_TYPE_DIRS.keys()), help="Filter by rule type")
        p_list.add_argument("--min-fitness", type=float, help="Filter by minimum fitness score")

        p_create = sub.add_parser("create", parents=[common], help="Create a new governance rule")
        p_create.add_argument("-t", "--type", dest="type", default="trap", help="Rule type (trap, invariant, boundary, persona, contract)")
        p_create.add_argument("--hypothesis", default="", help="Testable rule hypothesis")
        p_create.add_argument("-p", "--prediction", default="", help="Expected outcome when hypothesis holds")
        p_create.add_argument("-f", "--falsification", default="", help="Criteria that falsify the rule")
        p_create.add_argument("-d", "--domain", default="correctness", help="Governance domain")
        p_create.add_argument("-e", "--enforcement", default=None, help="Enforcement tier (gate, advisory)")
        p_create.add_argument("-n", "--name", "--id", dest="id", default=None, help="Explicit rule ID stem")
        p_create.add_argument("--target-paths", dest="target_paths", default="", help="Comma-separated target path globs")
        p_create.add_argument("--tags", default="", help="Comma-separated tags")
        p_create.add_argument("-w", "--weight", type=float, default=1.0, help="Impact weight")
        p_create.add_argument("--expiry-sessions", dest="expiry_sessions", type=int, default=15, help="Session expiry")
        p_create.add_argument("--expiry-days", dest="expiry_days", type=int, default=60, help="Day expiry")
        p_create.add_argument("--minimum-mode", dest="minimum_mode", default="", help="Minimum review mode")
        p_create.add_argument("--effector", action="store_true", default=False, help="Create as effector cell")
        p_create.add_argument("--memory", action="store_true", default=False, help="Create as memory cell")
        p_create.add_argument("--from-description", dest="description", default="", help="Create from description")

        p_prom = sub.add_parser("promote", parents=[common], help="Promote a rule up lifecycle tiers")
        p_prom.add_argument("rule_id", nargs="?", default=None, help="Rule identifier to promote")
        p_prom.add_argument("--rule", default=None, help="Rule identifier to promote")
        p_prom.add_argument("--reason", help="Audit explanation for promotion")
        p_prom.add_argument("--force", action="store_true", help="Bypass evidence threshold checks")
        p_prom.add_argument("--tier-check", action="store_true", help="Evaluate enforcement tier transitions")
        p_prom.add_argument("--dry-run", action="store_true", help="Preview promotion without moving files")

        p_dem = sub.add_parser("demote", parents=[common], help="Demote a rule down lifecycle tiers")
        p_dem.add_argument("rule_id", nargs="?", default=None, help="Rule identifier to demote")
        p_dem.add_argument("--rule", default=None, help="Rule identifier to demote")
        p_dem.add_argument("--reason", help="Audit explanation for demotion")
        p_dem.add_argument("--force", action="store_true", help="Force demotion")
        p_dem.add_argument("--dry-run", action="store_true", help="Preview demotion without moving files")

        p_arch = sub.add_parser("archive", parents=[common], help="Archive decayed or extinct rules")
        p_arch.add_argument("rule_id", nargs="?", help="Specific rule ID to archive")
        p_arch.add_argument("--dry-run", action="store_true", help="Preview rules to archive")
        p_arch.add_argument("--apply", action="store_true", default=True, help="Apply archive movements")

        p_clean = sub.add_parser("clean", parents=[common], help="Clean redundant or leaked rules")
        p_clean.add_argument("--dry-run", action="store_true", help="Show purge candidates without deleting")
        p_clean.add_argument("--apply", action="store_true", help="Apply cleanup deletions")

    def execute(self, args: argparse.Namespace) -> int:
        return run_rule(args)


if __name__ == "__main__":  # pragma: no cover
    from aegis_cli.cli import main
    sys.exit(main(["rule"] + sys.argv[1:]))



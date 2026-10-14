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
from aegis_core.workspace import Workspace
from aegis_core.lifecycle import (
    promote_cell,
    demote_cell,
    prune_cells,
    find_cell_file,
    evaluate_promotions,
    evaluate_demotions,
    evaluate_cell_tiers,
)

__all__ = [
    "run_rule",
    "RuleCommand",
    "run_promote",
    "run_demote",
    "_force_promote",
    "_force_demote",
    "clean_global_rules",
    "run_clean_rules",
    "UNIVERSAL_TENETS",
]


def run_rule(args: argparse.Namespace) -> int:
    """Entrypoint for aegis rule subcommands."""
    action = getattr(args, "rule_action", None)
    if not action:
        # Default behavior: list rules
        return _run_list(args)

    if action == "list":
        return _run_list(args)
    elif action == "promote":
        return _run_promote(args)
    elif action == "demote":
        return _run_demote(args)
    elif action == "archive":
        return _run_archive(args)
    elif action == "clean":
        return _run_clean(args)

    print(f"Unknown rule subcommand: {action}", file=sys.stderr)
    return 1


def _resolve_workspace_root(args: argparse.Namespace) -> Path:
    ws_obj = getattr(args, "ws", None)
    if ws_obj is not None:
        return ws_obj.root
    raw = getattr(args, "workspace", None) or getattr(args, "_project_root", None) or getattr(args, "_root", None)
    if raw:
        return Path(raw).resolve()
    return Workspace.resolve().root


def _run_list(args: argparse.Namespace) -> int:
    """List active rules and fitness metrics."""
    from aegis_core.yaml import parse_frontmatter
    root = _resolve_workspace_root(args)
    rules_dir = (root / ".aegis" / "rules") if (root / ".aegis" / "rules").is_dir() else (root / ".soma" / "cells")
    if not rules_dir.is_dir():
        if getattr(args, "json", False):
            print(json.dumps([]))
        else:
            print("No rules directory found.")
        return 0

    rule_type_filter = getattr(args, "type", None)
    min_fitness = getattr(args, "min_fitness", None)

    rules = []
    for md_file in sorted(rules_dir.rglob("*.md")):
        if md_file.name == "README.md":
            continue
        try:
            content = md_file.read_text(encoding="utf-8")
            fm = parse_frontmatter(content) or {}
            r_type = fm.get("type", md_file.parent.name.rstrip("s"))
            if rule_type_filter and r_type != rule_type_filter:
                continue

            fitness_block = fm.get("fitness", {})
            score = fitness_block.get("score") if isinstance(fitness_block, dict) else None

            if min_fitness is not None and score is not None and score < min_fitness:
                continue

            rules.append({
                "id": fm.get("id", md_file.stem),
                "type": r_type,
                "domain": fm.get("domain", "general"),
                "enforcement": fm.get("enforcement", "advisory"),
                "score": score,
                "path": str(md_file.relative_to(root)),
            })
        except Exception:
            continue

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
    tbl.add_column("Rule ID", no_wrap=True)
    tbl.add_column("Type", no_wrap=True)
    tbl.add_column("Enforcement", no_wrap=True)
    tbl.add_column("Fitness", justify="right", no_wrap=True)
    for r in rules:
        score_str = ui.color_fitness(float(r["score"])) if isinstance(r.get("score"), (int, float)) else "—"
        type_str = ui.color_rule_type(str(r["type"]))
        tbl.add_row(str(r["id"]), type_str, str(r["enforcement"]), score_str)

    print(f"Active Rules ({len(rules)} found):")
    for line in tbl.render(ui).splitlines():
        print(f"  {line}")
    return 0



def _run_promote(args: argparse.Namespace) -> int:
    """Promote a rule up lifecycle tiers or evaluate promotion candidates."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    root = _resolve_workspace_root(args)
    rule_id = getattr(args, "rule", None) or getattr(args, "rule_id", None) or getattr(args, "cell", None) or getattr(args, "cell_id", None)
    dry_run = getattr(args, "dry_run", False)
    use_json = getattr(args, "json", False)
    force = getattr(args, "force", False)

    if getattr(args, "tier_check", False):
        res = evaluate_cell_tiers(root, execute=not dry_run)
        if use_json:
            print(json.dumps(res, indent=2))
        else:
            changes = res.get("changes", [])
            print(f"  Evaluated {res.get('evaluated', 0)} rules across enforcement tiers.")
            if not changes:
                print("  No tier changes required.")
            else:
                for c in changes:
                    print(f"    {c['cell']}: {c['old_tier']} → {c['new_tier']} ({c['reason']})")
        return 0

    if not rule_id:
        candidates = evaluate_promotions(str(root))
        if use_json:
            print(json.dumps({"candidates": candidates}, indent=2, default=str))
        else:
            if not candidates:
                print("  No promotion candidates found.")
            else:
                print(f"  Promotion Candidates ({len(candidates)}):")
                print()
                for c in candidates:
                    print(f"    {c['cell_id']}: {c['from_type']} → {c['to_type']}")
                    print(f"      triggers={c['triggers']} tp_rate={c['tp_rate']:.0%} age={c['age_days']}d")
                print()
        return 0

    res = promote_cell(root, rule_id, force=True, dry_run=dry_run)
    status = res.get("status")

    if status == "not_found":
        msg = f"Rule '{rule_id}' not found in workspace"
        if use_json:
            print(json.dumps({"error": msg}))
        else:
            print(f"  ❌ {msg}")
        return 1

    if status == "already_terminal":
        msg = f"Rule '{rule_id}' is already at terminal tier ('{res.get('current_type')}')"
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
            print(f"  ❌ {msg}")
        return 1

    from_t = res.get("from_type")
    to_t = res.get("to_type")
    if dry_run:
        if use_json:
            print(json.dumps({"action": "promote", "rule_id": rule_id, "from": from_t, "to": to_t, "dry_run": True}))
        else:
            print(f"  🔍 Would promote: {rule_id}: {from_t} → {to_t}")
        return 0

    if use_json:
        print(json.dumps({"action": "promote", "rule_id": rule_id, "from": from_t, "to": to_t, "success": True}))
    else:
        print(f"  ✅ Promoted: {rule_id}: {from_t} → {to_t}")
    return 0


def _run_demote(args: argparse.Namespace) -> int:
    """Demote a rule down lifecycle tiers or evaluate demotion candidates."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    root = _resolve_workspace_root(args)
    rule_id = getattr(args, "rule", None) or getattr(args, "rule_id", None) or getattr(args, "cell", None) or getattr(args, "cell_id", None)
    dry_run = getattr(args, "dry_run", False)
    use_json = getattr(args, "json", False)

    if not rule_id:
        candidates = evaluate_demotions(str(root))
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
                    if c.get("triggers", 0) > 0:
                        print(f"      triggers={c['triggers']} fp_rate={c.get('fp_rate', 0):.0%}")
                    else:
                        print(f"      dormant for {c.get('age_days', 0)}d")
                print()
        return 0

    try:
        res = demote_cell(root, rule_id, dry_run=dry_run)
    except ValueError as exc:
        msg = f"Cannot demote core rule: {rule_id}."
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
        msg = f"Rule '{rule_id}' not found in workspace"
        if use_json:
            print(json.dumps({"error": msg}))
        else:
            print(f"  ❌ {msg}")
        return 1

    if status == "already_base":
        msg = f"Rule '{rule_id}' is already at base tier ('{res.get('current_type')}')"
        if use_json:
            print(json.dumps({"error": msg}))
        else:
            print(f"  ⚠️  {msg}")
        return 1

    from_t = res.get("from_type")
    to_t = res.get("to_type")
    if dry_run:
        if use_json:
            print(json.dumps({"action": "demote", "rule_id": rule_id, "from": from_t, "to": to_t, "dry_run": True}))
        else:
            print(f"  🔍 Would demote: {rule_id}: {from_t} → {to_t}")
        return 0

    if use_json:
        print(json.dumps({"action": "demote", "rule_id": rule_id, "from": from_t, "to": to_t, "success": True}))
    else:
        print(f"  ✅ Demoted: {rule_id}: {from_t} → {to_t}")
    return 0


def _force_promote(project_root: Path, cell_id: str, dry_run: bool = False, use_json: bool = False) -> int:
    args = argparse.Namespace(_project_root=project_root, rule_id=cell_id, dry_run=dry_run, json=use_json, force=True)
    return _run_promote(args)


def _force_demote(project_root: Path, cell_id: str, dry_run: bool = False, use_json: bool = False) -> int:
    args = argparse.Namespace(_project_root=project_root, rule_id=cell_id, dry_run=dry_run, json=use_json, force=True)
    return _run_demote(args)


run_promote = _run_promote
run_demote = _run_demote


def _run_archive(args: argparse.Namespace) -> int:
    """Archive extinct or decayed rules."""
    root = _resolve_workspace_root(args)
    dry_run = getattr(args, "dry_run", False)
    execute = not dry_run and getattr(args, "apply", True)
    return prune_cells(workspace=root, execute=execute)


UNIVERSAL_TENETS = frozenset({
    "providence",
    "cost-optimization",
    "subagent-delegation",
    "destructive-ops",
    "testing",
    "documentation",
    "architectural-tenets",
    "polyglot-standards",
    "feature-specs",
    "desktop-automation",
    "tdd-protocol",
    "atomic-workstream-protocol",
})

AEGIS_INTERNAL_PURGE_STEMS = frozenset({
    "core-change-protocol",
    "optional-import-guard",
    "ci-green-before-release",
    "gitflow-review-gate",
    "no-pre-existing-excuse",
})


def is_purge_candidate(file_path: Path) -> tuple[bool, str]:
    """Check if a file matches leaked internal rule signatures."""
    stem = file_path.stem

    if stem.startswith("hgt-"):
        return True, "leaked_hgt_rule"

    if stem in AEGIS_INTERNAL_PURGE_STEMS:
        return True, "leaked_internal_rule"

    try:
        from aegis_core.yaml import parse_frontmatter
        content = file_path.read_text(encoding="utf-8-sig", errors="replace")
        meta = parse_frontmatter(content)
        if meta and isinstance(meta, dict):
            if meta.get("aegis_internal") is True or meta.get("soma_internal") is True or meta.get("domain") in ("aegis-internal", "soma-internal"):
                return True, "internal_marker"
            if "hgt" in meta or meta.get("domain") == "hgt":
                return True, "hgt_marker"
    except Exception:
        pass

    return False, ""


def _clean_claude_sections(content: str) -> tuple[str, list[str]]:
    """Clean leaked rules from CLAUDE.md while preserving custom user sections."""
    import re
    lines = content.splitlines()
    cleaned_lines: list[str] = []
    removed_sections: list[str] = []

    in_purge_section = False
    current_heading = ""

    for line in lines:
        match = re.match(r"^(#{1,3})\s+(.*)$", line)
        if match:
            heading = match.group(2).strip()
            slug = re.sub(r"[^a-zA-Z0-9]+", "-", heading.lower()).strip("-")
            should_purge = False
            for stem in AEGIS_INTERNAL_PURGE_STEMS:
                if stem in slug or slug in stem:
                    should_purge = True
                    break
            if "hgt" in slug or slug.startswith("hgt-"):
                should_purge = True

            if should_purge:
                in_purge_section = True
                current_heading = heading
                removed_sections.append(heading)
                continue
            else:
                in_purge_section = False
                current_heading = ""

        if in_purge_section:
            continue

        cleaned_lines.append(line)

    cleaned_content = "\n".join(cleaned_lines)
    if content.endswith("\n") and not cleaned_content.endswith("\n"):
        cleaned_content += "\n"
    return cleaned_content, removed_sections


def clean_global_rules(
    home_dir: Path | str | None = None,
    dry_run: bool = True,
    force: bool = False,
    quarantine_dir: Path | str | None = None,
) -> dict[str, Any]:
    """Inspect and optionally clean leaked rules across global AI platform directories."""
    import shutil
    from datetime import datetime, timezone
    execute = bool(force and not dry_run)
    home = Path(home_dir).resolve() if home_dir else Path(os.environ.get("HOME") or Path.home()).resolve()

    q_base = Path(quarantine_dir).resolve() if quarantine_dir else (home / ".aegis" / "quarantine" if (home / ".aegis").is_dir() else home / ".soma" / "quarantine")
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    q_backup = q_base / f"global_rules_backup_{timestamp}"

    candidate_rules_dirs = [
        home / ".gemini" / "config" / "rules",
        home / ".cursor" / "rules",
        home / ".kiro" / "steering",
    ]

    purged_rules: list[str] = []
    retained_rules: list[str] = []
    claude_cleaned = False

    for rdir in candidate_rules_dirs:
        if not rdir.is_dir():
            continue

        for rule_file in sorted(rdir.glob("*.md")):
            should_purge, reason = is_purge_candidate(rule_file)
            if should_purge:
                purged_rules.append(rule_file.name)
                if execute:
                    q_backup.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(str(rule_file), str(q_backup / rule_file.name))
                    rule_file.unlink()
            else:
                retained_rules.append(rule_file.name)

    claude_md = home / ".claude" / "CLAUDE.md"
    if claude_md.is_file():
        try:
            claude_content = claude_md.read_text(encoding="utf-8", errors="replace")
            clean_content, removed = _clean_claude_sections(claude_content)
            if removed:
                claude_cleaned = True
                purged_rules.extend([f"CLAUDE.md:{sec}" for sec in removed])
                if execute:
                    q_backup.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(str(claude_md), str(q_backup / "CLAUDE.md"))
                    claude_bak = claude_md.parent / f"CLAUDE.md.bak.{timestamp}"
                    shutil.copy2(str(claude_md), str(claude_bak))
                    claude_md.write_text(clean_content, encoding="utf-8")
        except Exception as e:
            print(f"Warning: Failed inspecting CLAUDE.md: {e}", file=sys.stderr)

    return {
        "dry_run": not execute,
        "quarantine_dir": str(q_backup) if execute else str(q_base),
        "purged_rules": purged_rules,
        "retained_rules": retained_rules,
        "claude_cleaned": claude_cleaned,
    }


def _run_clean(args: argparse.Namespace) -> int:
    """Clean redundant or leaked global rules."""
    dry_run = getattr(args, "dry_run", False)
    apply = getattr(args, "apply", False) or getattr(args, "force", False)
    force = apply and not dry_run
    q_dir = getattr(args, "quarantine_dir", "") or None

    res = clean_global_rules(dry_run=not force, force=force, quarantine_dir=q_dir)

    print("🛡️  Aegis Global Rules Cleanse Protocol")
    print(f"  Mode: {'🔍 Dry Run (preview only)' if res['dry_run'] else '⚡ Executed'}")

    if res["purged_rules"]:
        print(f"\n  🧹 Leaked Rules Targeted ({len(res['purged_rules'])}):")
        for r in res["purged_rules"]:
            print(f"    - {r}")
    else:
        print("\n  ✨ No leaked rules found in global platform directories.")

    if res["retained_rules"]:
        print(f"\n  ✅ Retained Rules ({len(res['retained_rules'])}):")
        for r in res["retained_rules"]:
            print(f"    - {r}")

    if not res["dry_run"]:
        print(f"\n  📦 Quarantine backup preserved at: {res['quarantine_dir']}")
    elif res["purged_rules"]:
        print("\n  ℹ️  Run with --apply to quarantine and purge leaked rules.")

    return 0


run_clean_rules = _run_clean


class RuleCommand(AegisCommand):
    """Unified rule lifecycle management."""

    name = "rule"
    aliases = ()
    category = CommandCategory.LIFECYCLE
    help = "Manage rule lifecycle (list, promote, demote, archive, clean)"

    def configure_parser(self, parser: argparse.ArgumentParser) -> None:
        sub = parser.add_subparsers(dest="rule_action", metavar="ACTION")

        # list
        p_list = sub.add_parser("list", help="List active rules and fitness metrics")
        p_list.add_argument("--type", choices=["invariant", "trap", "boundary", "persona", "contract", "wall", "vacuole"], help="Filter by rule type")
        p_list.add_argument("--min-fitness", type=float, help="Filter by minimum fitness score")

        # promote
        p_prom = sub.add_parser("promote", help="Promote a rule up lifecycle tiers")
        p_prom.add_argument("rule_id", nargs="?", default=None, help="Rule identifier to promote")
        p_prom.add_argument("--rule", default=None, help="Rule identifier to promote")
        p_prom.add_argument("--reason", help="Audit explanation for promotion")
        p_prom.add_argument("--force", action="store_true", help="Bypass evidence threshold checks")
        p_prom.add_argument("--tier-check", action="store_true", help="Evaluate enforcement tier transitions")
        p_prom.add_argument("--dry-run", action="store_true", help="Preview promotion without moving files")

        # demote
        p_dem = sub.add_parser("demote", help="Demote a rule down lifecycle tiers")
        p_dem.add_argument("rule_id", nargs="?", default=None, help="Rule identifier to demote")
        p_dem.add_argument("--rule", default=None, help="Rule identifier to demote")
        p_dem.add_argument("--reason", help="Audit explanation for demotion")
        p_dem.add_argument("--force", action="store_true", help="Force demotion")
        p_dem.add_argument("--dry-run", action="store_true", help="Preview demotion without moving files")


        # archive
        p_arch = sub.add_parser("archive", help="Archive decayed or extinct rules")
        p_arch.add_argument("rule_id", nargs="?", help="Specific rule ID to archive")
        p_arch.add_argument("--dry-run", action="store_true", help="Preview rules to archive")
        p_arch.add_argument("--apply", action="store_true", default=True, help="Apply archive movements")

        # clean
        p_clean = sub.add_parser("clean", help="Clean redundant or leaked rules")
        p_clean.add_argument("--dry-run", action="store_true", help="Show purge candidates without deleting")
        p_clean.add_argument("--apply", action="store_true", help="Apply cleanup deletions")

    def execute(self, args: argparse.Namespace) -> int:
        return run_rule(args)


if __name__ == "__main__":  # pragma: no cover
    from aegis_cli.cli import main
    sys.exit(main(["rule"] + sys.argv[1:]))

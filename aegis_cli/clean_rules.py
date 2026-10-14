"""soma clean-global-rules — Cleanse leaked internal rules from global platform dirs.

Preserves universal tenets and custom user rules while quarantining and removing
leaked HGT playbooks and repository-internal Soma rules.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import os
from pathlib import Path
import re
import shutil
import sys
from typing import Any

from aegis_core.somayaml import parse_frontmatter
from aegis_cli.base import CommandCategory, SomaCommand

__all__ = ["run_clean_rules", "CleanRulesCommand"]

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

SOMA_INTERNAL_PURGE_STEMS = frozenset({
    "core-change-protocol",
    "optional-import-guard",
    "ci-green-before-release",
    "gitflow-review-gate",
    "no-pre-existing-excuse",
})


def is_purge_candidate(file_path: Path) -> tuple[bool, str]:
    """Check if a file matches leaked Soma or HGT rule signatures."""
    stem = file_path.stem

    if stem.startswith("hgt-"):
        return True, "leaked_hgt_rule"

    if stem in SOMA_INTERNAL_PURGE_STEMS:
        return True, "leaked_soma_internal_rule"

    try:
        content = file_path.read_text(encoding="utf-8-sig", errors="replace")
        meta = parse_frontmatter(content)
        if meta and isinstance(meta, dict):
            if meta.get("soma_internal") is True or meta.get("domain") == "soma-internal":
                return True, "soma_internal_marker"
            if "hgt" in meta or meta.get("domain") == "hgt":
                return True, "hgt_marker"
    except Exception:
        pass

    return False, ""


def _clean_claude_sections(content: str) -> tuple[str, list[str]]:
    """Clean leaked rules from CLAUDE.md while preserving custom user sections."""
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
            for stem in SOMA_INTERNAL_PURGE_STEMS:
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
            # Skip until next heading
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
    execute = bool(force and not dry_run)
    home = Path(home_dir).resolve() if home_dir else Path(os.environ.get("HOME") or Path.home()).resolve()

    q_base = Path(quarantine_dir).resolve() if quarantine_dir else home / ".soma" / "quarantine"
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

    # 1. Inspect directory-based rule stores
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

    # 2. Inspect Claude CLAUDE.md
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


def run_clean_rules(args: argparse.Namespace) -> int:
    """CLI dispatcher for soma clean-global-rules."""
    force = getattr(args, "force", False)
    dry_run = getattr(args, "dry_run", False) or not force
    q_dir = getattr(args, "quarantine_dir", "") or None

    res = clean_global_rules(dry_run=dry_run, force=force, quarantine_dir=q_dir)

    print("🛡️  Soma Global Rules Cleanse & Quarantine Protocol")
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
        print("\n  ℹ️  Run with --force to quarantine and purge leaked rules.")

    return 0


class CleanRulesCommand(SomaCommand):
    """Command to cleanse leaked internal rules from global platform directories."""

    name = "clean-global-rules"
    category = CommandCategory.PLUMBING
    help = "Cleanse leaked internal rules from global platform directories"

    def configure_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Simulate cleanse without removing files (default)",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Execute removal of leaked rules with quarantine backup",
        )
        parser.add_argument(
            "--quarantine-dir",
            type=str,
            default="",
            help="Custom quarantine directory (default: ~/.soma/quarantine)",
        )

    def execute(self, args: argparse.Namespace) -> int:
        return run_clean_rules(args)

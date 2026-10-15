"""Global rule section cleansing, legacy marker removal, and workspace rule listing helpers."""
from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
import re
import shutil
import sys
from typing import Any

from aegis_core.workspace.layout import WorkspaceLayout
from aegis_core.yaml import parse_frontmatter

__all__ = [
    "UNIVERSAL_TENETS",
    "AEGIS_INTERNAL_PURGE_STEMS",
    "is_purge_candidate",
    "_clean_claude_sections",
    "clean_global_rules",
    "format_cleanse_report",
    "collect_workspace_rules",
]

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
        content = file_path.read_text(encoding="utf-8-sig", errors="replace")
        meta = parse_frontmatter(content)
        if meta and isinstance(meta, dict):
            if (
                meta.get("aegis_internal") is True
                or meta.get("soma_internal") is True
                or meta.get("domain") in ("aegis-internal", "soma-internal")
            ):
                return True, "internal_marker"
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

    for line in lines:
        match = re.match(r"^(#{1,3})\s+(.*)$", line)
        if match:
            heading = match.group(2).strip()
            slug = re.sub(r"[^a-zA-Z0-9]+", "-", heading.lower()).strip("-")
            should_purge = any(stem in slug or slug in stem for stem in AEGIS_INTERNAL_PURGE_STEMS)
            if "hgt" in slug or slug.startswith("hgt-"):
                should_purge = True

            if should_purge:
                in_purge_section = True
                removed_sections.append(heading)
                continue
            in_purge_section = False

        if not in_purge_section:
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

    q_base = Path(quarantine_dir).resolve() if quarantine_dir else WorkspaceLayout(home).quarantine_dir
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
            should_purge, _reason = is_purge_candidate(rule_file)
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


def format_cleanse_report(res: dict[str, Any]) -> str:
    """Format the output report for clean_global_rules."""
    lines = [
        "🛡️  Aegis Global Rules Cleanse Protocol",
        f"  Mode: {'🔍 Dry Run (preview only)' if res['dry_run'] else '⚡ Executed'}",
    ]
    if res["purged_rules"]:
        lines.append(f"\n  🧹 Leaked Rules Targeted ({len(res['purged_rules'])}):")
        for r in res["purged_rules"]:
            lines.append(f"    - {r}")
    else:
        lines.append("\n  ✨ No leaked rules found in global platform directories.")

    if res["retained_rules"]:
        lines.append(f"\n  ✅ Retained Rules ({len(res['retained_rules'])}):")
        for r in res["retained_rules"]:
            lines.append(f"    - {r}")

    if not res["dry_run"]:
        lines.append(f"\n  📦 Quarantine backup preserved at: {res['quarantine_dir']}")
    elif res["purged_rules"]:
        lines.append("\n  ℹ️  Run with --apply to quarantine and purge leaked rules.")

    return "\n".join(lines)


def collect_workspace_rules(
    root: Path,
    rules_dir: Path,
    rule_type_filter: str | None = None,
    min_fitness: float | None = None,
) -> list[dict[str, Any]]:
    """Scan workspace rules directory and return filtered rule metadata dicts."""
    rules: list[dict[str, Any]] = []
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
    return rules

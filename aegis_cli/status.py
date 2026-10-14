"""soma status — Show active rules and stats."""
from __future__ import annotations

import argparse
import re
from datetime import date, datetime
from pathlib import Path

from aegis_cli import resolve_root, sanitize_display
from aegis_cli.base import CommandCategory, AegisCommand
from aegis_core.evidence import aggregate_signals

__all__ = ["run_status", "StatusCommand"]

from aegis_sdk.cells import parse_cell_file


def _repo_root(args: argparse.Namespace) -> Path:
    """Find the Soma install root (where genome/ lives)."""
    return resolve_root(args, default=Path(__file__).resolve().parent.parent)


def _project_root(args: argparse.Namespace) -> Path:
    """Find the project root (where .soma/ lives)."""
    return resolve_root(args)


def _parse_frontmatter(filepath: str) -> dict:
    """Extract YAML frontmatter from a cell file using the canonical parser.

    Falls back to empty dict on any error.
    """
    try:
        fm, _body = parse_cell_file(filepath)
        return fm
    except Exception:
        return {}


def _parse_created_date(created_val) -> date | None:
    """Parse a created date from frontmatter."""
    if created_val is None:
        return None
    if isinstance(created_val, datetime):
        return created_val.date()
    if isinstance(created_val, date):
        return created_val
    if isinstance(created_val, (int, float)):
        try:
            return datetime.fromtimestamp(created_val).date()
        except Exception:
            return None
    if isinstance(created_val, str):
        s = created_val.strip().rstrip("Z")
        try:
            return date.fromisoformat(s[:10])
        except Exception:
            pass
        try:
            return datetime.strptime(s[:10], "%Y-%m-%d").date()
        except Exception:
            pass
    return None


def _format_adaptive_expiry(created_val, expiry_days_val) -> str:
    """Calculate remaining days for an adaptive rule."""
    if expiry_days_val is None or created_val is None:
        return "—"
    try:
        expiry_days = int(expiry_days_val)
    except (ValueError, TypeError):
        return "—"

    created_date = _parse_created_date(created_val)
    if created_date is None:
        return "—"

    days_elapsed = (date.today() - created_date).days
    remaining_days = expiry_days - days_elapsed
    if remaining_days < 0:
        return "expired"
    return f"{remaining_days}d"


def _read_trigger_counts(evidence_dir: Path) -> dict[str, int]:
    """Read the canonical trigger count dimension per cell."""
    try:
        aggregation = aggregate_signals(str(evidence_dir))
    except Exception:
        return {}

    return {
        str(cell_id): int(entry["triggers"])
        for cell_id, entry in aggregation.counts.items()
        if isinstance(entry, dict) and entry.get("has_triggers")
    }


# ── CLAUDE.md merged rules (BUG-033) ────────────────────────────────────────
# Claude Code reads one CLAUDE.md, so rules are merged rather than copied.
# Two writers exist and must stay in sync with this parser:
#   install/install.sh + install.ps1: "# Soma Governance Rules" header, then
#     per rule a "---" line followed by the frontmatter-stripped body, which
#     starts with an H1. Bodies may contain their own "---" rules (followed
#     by H2s), so only "---" + H1 starts a new rule.
#   aegis_cli/init.py _install_claude_md: <!-- SOMA:START/END --> markers,
#     sections "## <stem>" (raw file incl. frontmatter) joined by "---".

SOMA_HEADER = "# Soma Governance Rules"
SOMA_MARKER_START = "<!-- SOMA:START -->"
SOMA_MARKER_END = "<!-- SOMA:END -->"
_SECTION_SLUG = re.compile(r"^## ([A-Za-z0-9][A-Za-z0-9._-]*)$")
_HEADER_LINE = re.compile(r"^# Soma Governance Rules[ \t]*\r?$", re.M)


def _frontmatter_id(text: str) -> str | None:
    """Return ``id`` from a leading YAML frontmatter block, if any."""
    lines = text.lstrip().splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    for line in lines[1:]:
        if line.strip() == "---":
            break
        m = re.match(r"^id:\s*(.+?)\s*$", line)
        if m:
            return m.group(1).strip("'\"") or None
    return None


def _first_h1(text: str) -> str | None:
    """Return the first top-level heading's text, skipping frontmatter."""
    lines = text.lstrip().splitlines()
    start = 0
    if lines and lines[0].strip() == "---":
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                start = i + 1
                break
    for line in lines[start:]:
        s = line.strip()
        if s.startswith("# "):
            return s[2:].strip()
    return None


def _genome_heading_map(root: Path) -> dict[str, str]:
    """Map each packaged rule's H1 to its id, so merged bodies (which lost
    their frontmatter) still match trigger counts."""
    mapping: dict[str, str] = {}
    genome_dir = root / "rules"
    if not genome_dir.is_dir():
        genome_dir = root / "genome"
    for d in (genome_dir, genome_dir / ".oracles"):
        if not d.is_dir():
            continue
        for p in sorted(d.glob("*.md")):
            try:
                text = p.read_text(encoding="utf-8")
            except Exception:
                continue
            heading = _first_h1(text)
            if heading:
                mapping.setdefault(heading, _frontmatter_id(text) or p.stem)
    return mapping


def _parse_marker_block(lines: list[str]) -> list[dict]:
    """Parse the soma init block: '## <stem>' after the header or a '---'."""
    sections: list[dict] = []
    cur: dict | None = None
    after_sep = True
    i = 0
    while i < len(lines):
        s = lines[i].strip()
        if not s:
            if cur is not None:
                cur["lines"].append(lines[i])
            i += 1
            continue
        m = _SECTION_SLUG.match(s) if after_sep else None
        if m:
            j = next((k for k in range(i + 1, len(lines)) if lines[k].strip()), None)
            nxt = lines[j].strip() if j is not None else ""
            # A rule body starts with frontmatter or an H1; a body's own
            # "---" + "## Section" does not.
            if j is None or nxt == "---" or nxt.startswith("# "):
                cur = {"stem": m.group(1), "lines": []}
                sections.append(cur)
                after_sep = False
                i += 1
                if nxt == "---":  # consume frontmatter so its closing --- is not a separator
                    end = next((k for k in range(j + 1, len(lines))
                                if lines[k].strip() == "---"), None)
                    if end is not None:
                        cur["lines"].extend(lines[i:end + 1])
                        i = end + 1
                continue
        after_sep = s in ("---", SOMA_HEADER)
        if cur is not None:
            cur["lines"].append(lines[i])
        i += 1
    out = []
    for sec in sections:
        text = "".join(sec["lines"])
        out.append({
            "name": _frontmatter_id(text) or sec["stem"],
            "keys": {sec["stem"], _first_h1(text)} - {None},
            "text": text,
        })
    return out


def _parse_install_region(lines: list[str], heading_map: dict[str, str]) -> list[dict]:
    """Parse install.sh/ps1 output: a rule starts at an H1 right after '---'."""
    sections: list[dict] = []
    cur: dict | None = None
    after_sep = False
    for line in lines:
        s = line.strip()
        if s:
            if after_sep and s.startswith("# "):
                cur = {"heading": s[2:].strip(), "lines": []}
                sections.append(cur)
            after_sep = s == "---"
        if cur is not None:
            cur["lines"].append(line)
    out = []
    for sec in sections:
        name = heading_map.get(sec["heading"], sec["heading"])
        out.append({
            "name": name,
            "keys": {name, sec["heading"]},
            "text": "".join(sec["lines"]),
        })
    return out


def _merged_claude_rules(claude_md: Path, heading_map: dict[str, str]) -> tuple[bool, list[dict]]:
    """Return (has_soma_content, merged rule sections) for a CLAUDE.md."""
    try:
        # utf-8-sig: install.ps1 (PowerShell 5.1 Set-Content -Encoding UTF8)
        # writes a BOM that would otherwise defeat the line-1 header match.
        text = claude_md.read_text(encoding="utf-8-sig")
    except Exception:
        return False, []
    has_soma = False
    rules: list[dict] = []
    rest = text
    start = text.find(SOMA_MARKER_START)
    end = text.find(SOMA_MARKER_END)
    if 0 <= start < end:
        has_soma = True
        block = text[start + len(SOMA_MARKER_START):end]
        rules.extend(_parse_marker_block(block.splitlines(True)))
        rest = text[:start] + text[end + len(SOMA_MARKER_END):]
    m = _HEADER_LINE.search(rest)
    if m:
        has_soma = True
        rules.extend(_parse_install_region(rest[m.start():].splitlines(True), heading_map))
    return has_soma, rules


def format_status_summary(data: dict, plumbing: bool = False, plain: bool = False) -> str:
    """Format status summary text."""
    active = data.get("active_rules", data.get("active_cells", 0))
    traps = data.get("trap_count", data.get("vacuole_count", 0))
    invariants = data.get("wall_count", data.get("invariant_count", 0))
    archived = data.get("archived_count", data.get("apoptotic_count", 0))
    lines = [
        "📊 Aegis Governance Status",
        f"  Active Rules:    {active} active",
        f"  Invariants:      {invariants} enforced",
        f"  Adaptive Traps:  {traps} active",
        f"  Archived Rules:  {archived} archived",
    ]

    text = "\n".join(lines)
    if plain:
        from aegis_cli import format_plain
        text = format_plain(text)
    return text


def run_status(args: argparse.Namespace) -> int:
    """Show active rules and stats."""
    root = _repo_root(args)
    proj = _project_root(args)

    # 1. Count installed rules: detect platform and scan rules dir
    #    Skip platform auto-detection when _root is explicitly provided (e.g. tests)
    #    to prevent leaking the real filesystem into test results.
    core_files: list[Path] = []
    merged_rules: list[dict] = []
    has_merged_soma = False
    test_mode = getattr(args, '_root', None) is not None
    home = getattr(args, '_home', getattr(args, '_home_override', None)) or Path.home()

    if not test_mode:
        try:
            from aegis_cli.init import detect_platform, get_rules_dir
            platform = detect_platform(proj)
            if platform == "unknown":
                platform = detect_platform(home)
            if platform != "unknown":
                rules_dir = get_rules_dir(platform, home=home, project_root=proj)
                if rules_dir.is_dir():
                    for p in sorted(rules_dir.glob("*.md")):
                        if p.is_file() and p.name.lower() not in ("readme.md", "claude.md"):
                            core_files.append(p)
                claude_md = rules_dir / "CLAUDE.md"
                if platform == "claude" and claude_md.is_file():
                    has_merged_soma, merged_rules = _merged_claude_rules(
                        claude_md, _genome_heading_map(root))
        except (ImportError, ValueError):
            pass

    # Drop merged sections that duplicate a loose file (soma init leaves the
    # loose copies next to its CLAUDE.md block) or an earlier merged section.
    seen: set[str] = set()
    for f in core_files:
        try:
            loose_text = f.read_text(encoding="utf-8-sig")
        except Exception:
            loose_text = ""
        seen.update(k for k in (f.stem, _frontmatter_id(loose_text),
                                _first_h1(loose_text)) if k)
    unique_merged: list[dict] = []
    for r in merged_rules:
        if r["name"] in seen or r["keys"] & seen:
            continue
        seen.add(r["name"])
        seen.update(r["keys"])
        unique_merged.append(r)
    merged_rules = unique_merged

    # Fallback: scan genome/ from the resolved root — never when CLAUDE.md
    # holds Soma content, or a 1-rule install reports the genome count.
    if not core_files and not has_merged_soma:
        genome_dir = (root / "rules") if (root / "rules").is_dir() else (root / "genome")
        if genome_dir.is_dir():
            for p in sorted(genome_dir.glob("*.md")):
                if p.is_file() and p.name.lower() != "readme.md":
                    core_files.append(p)
        oracles_dir = genome_dir / ".oracles"
        if oracles_dir.is_dir():
            for p in sorted(oracles_dir.glob("*.md")):
                if p.is_file() and p.name.lower() != "readme.md":
                    core_files.append(p)

    # 2. Count adaptive rules: .md files in .aegis/rules/ recursively (exclude README.md)
    adaptive_files: list[Path] = []
    cells_dir = proj / ".aegis" / "rules"
    if cells_dir.is_dir():
        for p in sorted(cells_dir.rglob("*.md")):
            if p.is_file() and p.name.lower() != "readme.md":
                adaptive_files.append(p)

    # 3. Read canonical trigger counts from .aegis/evidence/signals.jsonl
    evidence_dir = proj / ".aegis" / "evidence"
    trigger_counts = _read_trigger_counts(evidence_dir)

    # 4. Process all rules and calculate character overhead
    _type_norm = {
        "wall": "invariant",
        "invariants": "invariant",
        "membrane": "boundary",
        "boundaries": "boundary",
        "vacuole": "trap",
        "traps": "trap",
        "patterns": "trap",
        "chloroplast": "persona",
        "personas": "persona",
        "plasmodesmata": "contract",
        "contracts": "contract",
        "genome": "core",
        "core_rule": "core",
        "cells": "trap",
        "rules": "trap",
    }
    _type_order = {
        "core": 0,
        "invariant": 1,
        "boundary": 2,
        "contract": 3,
        "persona": 4,
        "trap": 5,
    }

    total_chars = 0
    all_rules: list[dict] = []

    for f in core_files:
        try:
            content = f.read_text(encoding="utf-8-sig")
        except Exception:
            content = ""
        total_chars += len(content)
        fm = _parse_frontmatter(str(f))
        rule_name = sanitize_display(str(fm.get("id") or f.stem))
        triggers = trigger_counts.get(rule_name, trigger_counts.get(f.stem, 0))
        fitness_block = fm.get("fitness", {})
        score = fitness_block.get("score") if isinstance(fitness_block, dict) else None
        all_rules.append({
            "name": rule_name,
            "type": "core",
            "score": score,
            "triggers": triggers,
            "expiry": "∞ (core)",
            "is_core": True,
        })

    for r in merged_rules:
        total_chars += len(r["text"])
        rule_name = sanitize_display(str(r["name"]))
        all_rules.append({
            "name": rule_name,
            "type": "core",
            "score": None,
            "triggers": trigger_counts.get(rule_name, 0),
            "expiry": "∞ (core)",
            "is_core": True,
        })

    for f in adaptive_files:
        try:
            content = f.read_text(encoding="utf-8-sig")
        except Exception:
            content = ""
        total_chars += len(content)
        fm = _parse_frontmatter(str(f))
        rule_name = sanitize_display(str(fm.get("id") or f.stem))
        raw_type = str(fm.get("type") or f.parent.name).lower()
        norm_type = _type_norm.get(raw_type, raw_type)
        fitness_block = fm.get("fitness", {})
        score = fitness_block.get("score") if isinstance(fitness_block, dict) else None
        triggers = trigger_counts.get(rule_name, trigger_counts.get(f.stem, 0))
        expiry_str = _format_adaptive_expiry(fm.get("created"), fm.get("expiry_days"))
        all_rules.append({
            "name": rule_name,
            "type": norm_type,
            "score": score,
            "triggers": triggers,
            "expiry": expiry_str,
            "is_core": False,
        })

    # Context load: total characters / 4
    estimated_tokens = total_chars // 4

    # Sort rules grouped by modern type, then triggers descending, fitness descending, name
    all_rules.sort(
        key=lambda r: (
            _type_order.get(r["type"], 99),
            -r["triggers"],
            -(float(r["score"]) if isinstance(r.get("score"), (int, float)) else -1.0),
            r["name"],
        )
    )

    if getattr(args, "format", None) == "json" or getattr(args, "json", False):
        import json
        payload = {
            "core_rules": len(core_files) + len(merged_rules),
            "adaptive_rules": len(adaptive_files),
            "estimated_tokens": estimated_tokens,
            "rules": all_rules,
        }
        print(json.dumps(payload, indent=2))
        return 0

    import os
    from aegis_cli.ui.table import Table
    from aegis_cli.ui.theme import OutputContext

    existing_ui = getattr(args, "ui", None)
    ui = existing_ui if isinstance(existing_ui, OutputContext) else OutputContext.from_env_and_args(args)
    max_budget = int(os.environ.get("AEGIS_MAX_JIT_TOKENS", "2000"))

    header_title = "🛡️ Aegis Workspace Status" if ui.emoji_enabled else "Aegis Workspace Status"
    print(f"{ui.style(header_title, 'bold', 'cyan')}\n")
    print(f"  {'Core rules:':<16}{len(core_files) + len(merged_rules)} active")
    print(f"  {'Adaptive rules:':<16}{len(adaptive_files)} (traps/patterns)")
    print(f"  {'Context load:':<16}~{estimated_tokens:,} tokens (pre-JIT max)")
    print(f"  {'Token budget:':<16}{ui.format_budget_bar(estimated_tokens, max_budget)}\n")

    if not all_rules:
        print("  No rules found. Run 'aegis init' to set up governance rules.")
        return 0

    tbl = Table(ctx=ui)
    tbl.add_column("Rule", no_wrap=True)
    tbl.add_column("Triggers", no_wrap=True)
    tbl.add_column("Type", no_wrap=True)
    tbl.add_column("Fitness", no_wrap=True)
    tbl.add_column("Expiry", no_wrap=True)

    last_type: str | None = None
    for r in all_rules:
        r_type = str(r.get("type", "trap"))
        if last_type is not None and r_type != last_type:
            tbl.add_section()
        last_type = r_type

        score_val = r.get("score")
        score_str = ui.color_fitness(float(score_val)) if isinstance(score_val, (int, float)) else "—"
        type_str = ui.color_rule_type(r_type)
        tbl.add_row(
            str(r["name"]),
            str(r["triggers"]),
            type_str,
            score_str,
            str(r["expiry"]),
        )

    for line in tbl.render(ui).splitlines():
        print(f"  {line}")

    return 0


class StatusCommand(AegisCommand):
    """Command to show active rules, rule inventory, and health stats."""

    name = "status"
    aliases = ("rules",)
    category = CommandCategory.WORKFLOW
    help = "Show active rules and stats"

    def configure_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--all",
            action="store_true",
            default=False,
            help="Show all rules without truncation",
        )

    def execute(self, args: argparse.Namespace) -> int:
        return run_status(args)


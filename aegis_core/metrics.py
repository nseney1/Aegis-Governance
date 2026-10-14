"""aegis_core.metrics — Metrics snapshots, token census, cell quorum, coverage, and immune grading.

Consolidates:
- Metrics snapshot persistence and token census aggregation across rules & skills.
- Quorum sensing across multi-cell triggers.
- Codebase governance coverage mapping and directory tier breakdown.
- Single-grade governance report card calculation.
"""
from __future__ import annotations

from datetime import datetime, timezone
import fnmatch
import glob
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import List, Optional, Union

from aegis_core.workspace import Workspace, resolve_workspace
from aegis_core.yaml import dump_frontmatter, parse_frontmatter


def resolve_metrics_dir(workspace: Path | str) -> Path:
    """Resolve where metrics snapshots are stored."""
    team_repo = os.environ.get("TEAM_REPO")
    team_member = os.environ.get("TEAM_MEMBER_ID", "local_user")
    metrics_repo = os.environ.get("METRICS_REPO")

    ws = Path(workspace).resolve()
    conf_path = ws / "aegis.conf"
    if (not team_repo or not metrics_repo) and conf_path.is_file():
        with open(conf_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("TEAM_REPO=") and not line.startswith("#"):
                    team_repo = line.split("=", 1)[1].strip().strip('"').strip("'")
                elif line.startswith("TEAM_MEMBER_ID=") and not line.startswith("#"):
                    team_member = line.split("=", 1)[1].strip().strip('"').strip("'")
                elif line.startswith("METRICS_REPO=") and not line.startswith("#"):
                    metrics_repo = line.split("=", 1)[1].strip().strip('"').strip("'")

    if team_repo:
        path = Path(os.path.expanduser(team_repo)) / "snapshots" / team_member
        path.mkdir(parents=True, exist_ok=True)
        return path

    if metrics_repo:
        path = Path(os.path.expanduser(metrics_repo))
        path.mkdir(parents=True, exist_ok=True)
        return path

    default = ws / "docs" / "snapshots"
    default.mkdir(parents=True, exist_ok=True)
    return default


def compute_token_census(workspace: Workspace | Path | str | None = None, model: str = "gemini-3.8-flash") -> dict:
    """Compute token census across genome rules and organ skills without subprocess."""
    ws = workspace if isinstance(workspace, Workspace) else (
        Workspace.resolve(workspace) if workspace is not None else Workspace.resolve()
    )
    rules_dir = (ws.root / "rules") if (ws.root / "rules").is_dir() else (ws.root / "genome")
    skills_dir = (ws.root / "skills") if (ws.root / "skills").is_dir() else (ws.root / "organs")

    results = []
    total_words = 0
    total_tokens = 0
    fallback_ratio = 1.35

    def _wc(text: str) -> int:
        return len(text.split())

    if ws.is_aegis_repo and rules_dir.is_dir():
        for fpath in sorted(rules_dir.glob("*.md")):
            try:
                content = fpath.read_text(encoding="utf-8")
            except OSError:
                continue
            fm_dict = parse_frontmatter(content) or {}
            fm = dump_frontmatter(fm_dict) if fm_dict else ""
            trig = str(fm_dict.get("trigger", "unknown")).strip()
            w_full = _wc(content)
            w_fm = _wc(fm)

            if trig == "always_on":
                c_type = "always_on_rule"
                t_idle = int(w_full * fallback_ratio)
                t_active = t_idle
                w_idle = w_full
                w_active = w_full
            else:
                c_type = "conditional_rule"
                t_idle = int(w_fm * fallback_ratio)
                t_active = int(w_full * fallback_ratio)
                w_idle = w_fm
                w_active = w_full

            total_words += w_full
            total_tokens += t_active
            results.append({
                "filename": f"{rules_dir.name}/{fpath.name}",
                "type": c_type,
                "idle_words": w_idle,
                "idle_tokens": t_idle,
                "active_words": w_active,
                "active_tokens": t_active,
                "ratio": t_active / w_active if w_active else 0,
            })

    if skills_dir.is_dir():
        for fpath in sorted(skills_dir.glob("*/SKILL.md")):
            skill_name = fpath.parent.name
            try:
                content = fpath.read_text(encoding="utf-8")
            except OSError:
                continue
            fm_dict = parse_frontmatter(content) or {}
            fm = dump_frontmatter(fm_dict) if fm_dict else ""
            w_full = _wc(content)
            w_fm = _wc(fm)
            t_idle = int(w_fm * fallback_ratio)
            t_active = int(w_full * fallback_ratio)
            w_idle = w_fm
            w_active = w_full

            total_words += w_full
            total_tokens += t_active
            results.append({
                "filename": f"organs/{skill_name}/SKILL.md",
                "type": "skill",
                "idle_words": w_idle,
                "idle_tokens": t_idle,
                "active_words": w_active,
                "active_tokens": t_active,
                "ratio": t_active / w_active if w_active else 0,
            })

    calibrated_ratio = total_tokens / total_words if total_words else fallback_ratio
    subtotals = {
        "always_on_rules_idle_tokens": sum(r["idle_tokens"] for r in results if r["type"] == "always_on_rule"),
        "conditional_rules_idle_tokens": sum(r["idle_tokens"] for r in results if r["type"] == "conditional_rule"),
        "conditional_rules_active_tokens": sum(r["active_tokens"] for r in results if r["type"] == "conditional_rule"),
        "skills_idle_tokens": sum(r["idle_tokens"] for r in results if r["type"] == "skill"),
        "skills_active_tokens": sum(r["active_tokens"] for r in results if r["type"] == "skill"),
    }
    grand_total_idle = subtotals["always_on_rules_idle_tokens"] + subtotals["conditional_rules_idle_tokens"] + subtotals["skills_idle_tokens"]

    return {
        "model": model,
        "measured_with_sdk": False,
        "calibrated_ratio": round(calibrated_ratio, 2),
        "files": results,
        "subtotals": subtotals,
        "grand_total_idle": grand_total_idle,
    }


def take_snapshot(
    json_mode: bool = False,
    raw_mode: bool = False,
    compare_file: str | None = None,
    save: bool = False,
    workspace: Path | None = None,
) -> int:
    ws = Path(workspace).resolve() if workspace else Path(resolve_workspace()).resolve()
    metrics_dir = resolve_metrics_dir(ws)

    try:
        census = compute_token_census(ws)
    except Exception:
        census = {
            "files": [],
            "subtotals": {"always_on_rules_idle_tokens": 0, "conditional_rules_idle_tokens": 0, "skills_idle_tokens": 0},
            "grand_total_idle": 0,
            "calibrated_ratio": 0,
        }

    always_on_rules = sum(1 for r in census["files"] if r.get("type") == "always_on_rule")
    conditional_rules = sum(1 for r in census["files"] if r.get("type") == "conditional_rule")
    skills_count = sum(1 for r in census["files"] if r.get("type") == "skill")

    prong_budgets = {}
    staff_review_path = ws / "organs" / "staff-review" / "SKILL.md"
    if staff_review_path.is_file():
        content = staff_review_path.read_text(encoding="utf-8")
        for line in content.splitlines():
            match = re.search(
                r'\|\s*.*?(Spores|Mycelium|Roots|Thorns|Bedrock|Mulch).*?\|\s*\**([0-9,]+\s*tokens).*?\|',
                line,
                re.IGNORECASE,
            )
            if match:
                prong_budgets[match.group(1)] = match.group(2).strip()

    waste_rate_best = "1.1%"
    waste_rate_avg = "18.8%"

    cells_count = 0
    cells_dir = ws / ".aegis" / "rules"
    if cells_dir.is_dir():
        for f in cells_dir.rglob("*.md"):
            cells_count += 1

    metrics = {
        "rules_always_on": always_on_rules,
        "rules_conditional": conditional_rules,
        "skills_count": skills_count,
        "cells_count": cells_count,
        "tokens": census.get("subtotals", {}),
        "grand_total_idle_overhead": census.get("grand_total_idle", 0),
        "calibrated_ratio": census.get("calibrated_ratio", 0),
        "waste_rate_best": waste_rate_best,
        "waste_rate_avg": waste_rate_avg,
        "prong_budgets": prong_budgets,
        "metrics_dir": str(metrics_dir),
    }

    if raw_mode:
        metrics["timestamp"] = datetime.now(timezone.utc).isoformat() + "Z"

    compare_data = None
    if compare_file and os.path.exists(compare_file):
        with open(compare_file, "r", encoding="utf-8") as f:
            compare_data = json.load(f)

    if save:
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        save_path = metrics_dir / f"snapshot-{ts}.json"
        save_metrics = dict(metrics)
        save_metrics["timestamp"] = datetime.now(timezone.utc).isoformat() + "Z"
        save_metrics.pop("metrics_dir", None)
        with open(save_path, "w", encoding="utf-8") as f:
            json.dump(save_metrics, f, indent=2)
        print(f"Saved to: {save_path}", file=sys.stderr)

    if json_mode:
        output = dict(metrics)
        output.pop("metrics_dir", None)
        print(json.dumps(output, indent=2))
    else:
        print("=== SOMA: METRICS SNAPSHOT ===")
        if raw_mode:
            print(f"Timestamp: {metrics.get('timestamp')}")
        print(f"Metrics Dir: {metrics_dir}")
        print("\n[ Counts ]")
        print(f"Rules:  {always_on_rules} always-on, {conditional_rules} conditional")
        print(f"Skills: {skills_count}")
        print(f"Cells:  {metrics.get('cells_count', 0)}")

        print("\n[ Tokens ]")
        toks = metrics.get('tokens', {})
        print(f"Always-On Rules (Idle):    {toks.get('always_on_rules_idle_tokens', 0)}")
        print(f"Conditional Rules Idle:    {toks.get('conditional_rules_idle_tokens', 0)}")
        print(f"Skills Idle:               {toks.get('skills_idle_tokens', 0)}")
        print(f"GRAND TOTAL IDLE OVERHEAD: {metrics['grand_total_idle_overhead']}")
        print(f"Calibrated Ratio:          {metrics['calibrated_ratio']}")

        print("\n[ Waste Rates ]")
        print(f"Best Governed:             {waste_rate_best}")
        print(f"Avg Governed:              {waste_rate_avg}")

        if prong_budgets:
            print("\n[ Prong Budgets ]")
            for p, b in prong_budgets.items():
                print(f"  {p}: {b}")

        if compare_data:
            print("\n[ Deltas vs Previous ]")
            prev_total = compare_data.get("grand_total_idle_overhead", 0)
            diff = metrics["grand_total_idle_overhead"] - prev_total
            print(f"Grand Total Idle Overhead: {diff:+d}")

    return 0


_QUORUM_MODES = {'breeze': 0, 'gale': 1, 'trident': 2, 'maelstrom': 3, 'tempest': 4}


def _resolve_rules_dir(workspace: str | Path) -> str:
    ws = Path(workspace)
    return str(ws / ".aegis" / "rules")


def _list_workspace_files(workspace: str) -> list[str]:
    result = subprocess.run(['git', 'ls-files'], capture_output=True, text=True, cwd=workspace)
    if result.returncode == 0 and result.stdout.strip():
        return [f for f in result.stdout.strip().split('\n') if f]
    ws_path = Path(workspace)
    files: list[str] = []
    if ws_path.is_dir():
        for p in sorted(ws_path.rglob("*")):
            if p.is_file():
                rel = p.relative_to(ws_path).as_posix()
                files.append(rel)
    return files


def evaluate_quorum(cells_dir: Path | str, changed_files: list[str], threshold: int = 3) -> dict:
    """Core quorum evaluation — pure function."""
    if not changed_files:
        return {'quorum': False, 'cells_triggered': 0, 'rules_triggered': 0}

    cells_path = Path(cells_dir)
    if not cells_path.is_dir():
        aegis_cand = cells_path / ".aegis" / "rules"
        if aegis_cand.is_dir():
            cells_path = aegis_cand
        else:
            return {'quorum': False, 'cells_triggered': 0, 'rules_triggered': 0}
    elif (cells_path / ".aegis" / "rules").is_dir():
        cells_path = cells_path / ".aegis" / "rules"

    triggered = []
    for cell_file in cells_path.rglob("*.md"):
        if cell_file.name == 'README.md':
            continue
        try:
            with open(cell_file, 'r', encoding='utf-8') as f:
                content = f.read()
            fm = parse_frontmatter(content) or {}
            target_paths = fm.get('target_paths', [])
            if isinstance(target_paths, str):
                target_paths = [target_paths]
            hypothesis = fm.get('hypothesis', '')

            matched = False
            for tp in target_paths:
                tp_norm = tp.replace("\\", "/")
                for cf in changed_files:
                    cf_norm = cf.replace("\\", "/")
                    if fnmatch.fnmatch(cf_norm, tp_norm):
                        matched = True
                        break
                if matched:
                    break

            if not matched:
                for cf in changed_files:
                    basename = os.path.basename(cf)
                    if basename in hypothesis:
                        matched = True
                        break

            if matched:
                triggered.append({
                    'name': fm.get('id', cell_file.stem),
                    'type': fm.get('type', 'unknown'),
                    'minimum_mode': fm.get('minimum_mode', 'breeze'),
                    'fitness': (fm.get('fitness') or {}).get('score'),
                    'hypothesis': hypothesis[:80]
                })
        except Exception:
            pass

    if len(triggered) >= threshold:
        max_mode = max(triggered, key=lambda t: _QUORUM_MODES.get(t.get('minimum_mode', 'breeze'), 0))['minimum_mode']
        return {
            'quorum': True,
            'cells_triggered': len(triggered),
            'rules_triggered': len(triggered),
            'cell_types': list({t['type'] for t in triggered}),
            'rule_types': list({t['type'] for t in triggered}),
            'escalate_to': max_mode,
            'triggered_cells': triggered,
            'triggered_rules': triggered,
        }
    return {
        'quorum': False,
        'cells_triggered': len(triggered),
        'rules_triggered': len(triggered),
    }


def calculate_coverage(workspace: str, exclude: Optional[Union[List[str], str]] = None) -> dict:
    """Calculate cell coverage mapping and directory tier breakdown."""
    cells_dir = _resolve_rules_dir(workspace)
    all_files = _list_workspace_files(workspace)
    EXCLUDE_PATTERNS = ['.aegis/', '.soma/', 'vendor/', '.git/', 'node_modules/']
    if exclude:
        if isinstance(exclude, str):
            EXCLUDE_PATTERNS.append(exclude)
        else:
            EXCLUDE_PATTERNS.extend(exclude)
    all_files = [f for f in all_files if not any(p in f for p in EXCLUDE_PATTERNS)]

    cell_patterns = []
    if os.path.isdir(cells_dir):
        for cell_file in glob.glob(os.path.join(cells_dir, '**', '*.md'), recursive=True):
            if os.path.basename(cell_file) == 'README.md':
                continue
            try:
                with open(cell_file, 'r', encoding='utf-8') as f:
                    fm = parse_frontmatter(f.read()) or {}
                paths = fm.get('target_paths', [])
                if isinstance(paths, str):
                    paths = [paths]
                name = fm.get('id', os.path.splitext(os.path.basename(cell_file))[0])
                cell_patterns.append({
                    'name': name,
                    'patterns': paths,
                    'type': fm.get('type', ''),
                    'enforcement': fm.get('enforcement', 'advisory')
                })
            except Exception as exc:
                sys.stderr.write(f"Warning: Failed to parse cell {cell_file}: {exc}\n")

    covered_files = set()
    uncovered_files = set()
    coverage_map = {}
    tier_rank = {'advisory': 0, 'mechanical': 1, 'gate': 2}
    dir_tiers = {}

    for f in all_files:
        is_covered = False
        for cell in cell_patterns:
            for pattern in cell['patterns']:
                if fnmatch.fnmatch(f, pattern):
                    is_covered = True
                    break
            if is_covered:
                break

        if is_covered:
            covered_files.add(f)
        else:
            uncovered_files.add(f)

        d = os.path.dirname(f) or '.'
        if d not in coverage_map:
            coverage_map[d] = {'covered': 0, 'total': 0, 'tier': 'none'}
        coverage_map[d]['total'] += 1
        if is_covered:
            coverage_map[d]['covered'] += 1

        for cell in cell_patterns:
            for pattern in cell['patterns']:
                if fnmatch.fnmatch(f, pattern):
                    current = dir_tiers.get(d, 'none')
                    cell_tier = cell.get('enforcement', 'advisory')
                    if tier_rank.get(cell_tier, 0) > tier_rank.get(current, -1):
                        dir_tiers[d] = cell_tier
                    break

        coverage_map[d]['tier'] = dir_tiers.get(d, 'none')

    total = len(all_files)
    covered = len(covered_files)
    pct = (covered / total * 100) if total > 0 else 0

    return {
        'total_files': total,
        'covered': covered,
        'uncovered': total - covered,
        'coverage_pct': round(pct, 1),
        'by_directory': coverage_map,
        'uncovered_files': sorted(uncovered_files),
    }


calculate_cell_coverage = calculate_coverage
calculate_rule_coverage = calculate_coverage


def letter_grade(pct: float) -> str:
    """Map a percentage (0..100) to a letter grade."""
    if pct >= 97: return 'A+'
    if pct >= 93: return 'A'
    if pct >= 90: return 'A-'
    if pct >= 87: return 'B+'
    if pct >= 83: return 'B'
    if pct >= 80: return 'B-'
    if pct >= 77: return 'C+'
    if pct >= 73: return 'C'
    if pct >= 70: return 'C-'
    if pct >= 67: return 'D+'
    if pct >= 60: return 'D'
    return 'F'


def calculate_immune_grade(workspace: str) -> Optional[dict]:
    """Calculate complete governance report card."""
    cells_dir = _resolve_rules_dir(workspace)
    cells = []
    if os.path.isdir(cells_dir):
        for cell_file in glob.glob(os.path.join(cells_dir, '**', '*.md'), recursive=True):
            if os.path.basename(cell_file) == 'README.md':
                continue
            try:
                with open(cell_file, 'r', encoding='utf-8') as f:
                    fm = parse_frontmatter(f.read()) or {}
                if isinstance(fm.get('fitness'), (int, float)):
                    fm['fitness'] = {'score': float(fm['fitness'])}
                fm['_name'] = os.path.splitext(os.path.basename(cell_file))[0]
                cells.append(fm)
            except Exception as exc:
                sys.stderr.write(f"Warning: Failed to parse cell {cell_file}: {exc}\n")

    if not cells:
        return None

    all_files = _list_workspace_files(workspace)
    exclude = ['.aegis/', '.soma/', 'vendor/', '.git/', 'node_modules/']
    all_files = [f for f in all_files if not any(p in f for p in exclude)]

    all_patterns = []
    for c in cells:
        all_patterns.extend(c.get('target_paths', []))

    covered = sum(1 for f in all_files if any(fnmatch.fnmatch(f, p) for p in all_patterns))
    coverage_pct = (covered / len(all_files) * 100) if all_files else 0

    scores = [(c.get('fitness') or {}).get('score') for c in cells if (c.get('fitness') or {}).get('score') is not None]
    avg_fitness = (sum(scores) / len(scores)) if scores else 0
    fitness_pct = avg_fitness * 100

    type_counts = {}
    for c in cells:
        ct = c.get('type', 'unknown')
        type_counts[ct] = type_counts.get(ct, 0) + 1
    total = sum(type_counts.values())
    if len(type_counts) > 1:
        entropy = -sum((n/total) * math.log(n/total) for n in type_counts.values() if n > 0)
        max_entropy = math.log(len(type_counts))
        diversity = (entropy / max_entropy) * 100
    else:
        diversity = 0

    stale = sum(1 for c in cells if (c.get('fitness') or {}).get('triggers', 0) == 0)
    staleness_pct = 100 - (stale / len(cells) * 100) if cells else 100

    walls = [c for c in cells if c.get('type') in ('wall', 'invariant')]
    healthy_walls = sum(1 for w in walls if ((w.get('fitness') or {}).get('score') is not None and (w.get('fitness') or {}).get('score', 0) > 0.3))
    wall_pct = (healthy_walls / len(walls) * 100) if walls else 100

    overall_pct = (coverage_pct * 0.3 + fitness_pct * 0.25 + diversity * 0.15 + staleness_pct * 0.15 + wall_pct * 0.15)

    tier_counts = {}
    for c in cells:
        tier = c.get('enforcement', 'advisory')
        tier_counts[tier] = tier_counts.get(tier, 0) + 1

    uncovered_dirs = {}
    for f in all_files:
        if not any(fnmatch.fnmatch(f, p) for p in all_patterns):
            d = os.path.dirname(f) or '.'
            uncovered_dirs[d] = uncovered_dirs.get(d, 0) + 1
    top_gap = max(uncovered_dirs.items(), key=lambda x: x[1]) if uncovered_dirs else ('none', 0)

    return {
        'coverage': {'pct': round(coverage_pct, 1), 'grade': letter_grade(coverage_pct)},
        'avg_fitness': {'pct': round(fitness_pct, 1), 'grade': letter_grade(fitness_pct), 'score': avg_fitness},
        'diversity': {'pct': round(diversity, 1), 'grade': letter_grade(diversity)},
        'staleness': {'pct': round(staleness_pct, 1), 'grade': letter_grade(staleness_pct)},
        'wall_integrity': {'pct': round(wall_pct, 1), 'grade': letter_grade(wall_pct)},
        'invariant_integrity': {'pct': round(wall_pct, 1), 'grade': letter_grade(wall_pct)},
        'tiers': tier_counts,
        'overall': {'pct': round(overall_pct, 1), 'grade': letter_grade(overall_pct)},
        'top_improvement': f'Add cells for {top_gap[0]}/ ({top_gap[1]} uncovered files)',
        'top_gap_count': top_gap[1],
        'details': {
            'total_cells': len(cells),
            'total_rules': len(cells),
            'walls': len(walls),
            'invariants': len(walls),
            'healthy_walls': healthy_walls,
            'healthy_invariants': healthy_walls,
            'stale_cells': stale,
            'stale_rules': stale,
        },
        'components': {
            'coverage': round(coverage_pct, 1),
            'avg_fitness': round(fitness_pct, 1),
            'diversity': round(diversity, 1),
            'staleness': round(staleness_pct, 1),
            'wall_strength': round(wall_pct, 1),
            'invariant_strength': round(wall_pct, 1),
            'wall_integrity': round(wall_pct, 1),
        },
    }


calculate_governance_grade = calculate_immune_grade


__all__ = [
    "resolve_metrics_dir",
    "compute_token_census",
    "take_snapshot",
    "evaluate_quorum",
    "calculate_coverage",
    "calculate_cell_coverage",
    "calculate_rule_coverage",
    "letter_grade",
    "calculate_immune_grade",
    "calculate_governance_grade",
]

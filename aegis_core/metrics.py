"""Rule coverage of the workspace's files and the governance report card (SDK grade/coverage_report)."""
from __future__ import annotations

import fnmatch
import glob
import math
import os
from pathlib import Path
import sys
from typing import List, Optional, Union

from aegis_core import gitsafe
from aegis_core.workspace.layout import AEGIS_DIRNAME, LEGACY_SOMA_DIRNAME, WorkspaceLayout
from aegis_core.yaml_engine.frontmatter import parse_frontmatter


def _resolve_rules_dir(workspace: str | Path) -> str:
    return str(WorkspaceLayout(Path(workspace).resolve()).rules_dir)


def _list_workspace_files(workspace: str) -> list[str]:
    tracked = gitsafe.list_files(workspace, untracked=False)
    if tracked:
        return tracked
    ws_path = Path(workspace)
    files: list[str] = []
    if ws_path.is_dir():
        for p in sorted(ws_path.rglob("*")):
            if p.is_file():
                rel = p.relative_to(ws_path).as_posix()
                files.append(rel)
    return files


def calculate_coverage(workspace: str, exclude: Optional[Union[List[str], str]] = None) -> dict:
    """Calculate cell coverage mapping and directory tier breakdown."""
    cells_dir = _resolve_rules_dir(workspace)
    all_files = _list_workspace_files(workspace)
    EXCLUDE_PATTERNS = [f'{AEGIS_DIRNAME}/', f'{LEGACY_SOMA_DIRNAME}/', 'vendor/', '.git/', 'node_modules/']
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


def calculate_governance_grade(workspace: str) -> Optional[dict]:
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
    exclude = [f'{AEGIS_DIRNAME}/', f'{LEGACY_SOMA_DIRNAME}/', 'vendor/', '.git/', 'node_modules/']
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
        'top_improvement': f'Add rules for {top_gap[0]}/ ({top_gap[1]} uncovered files)',
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


__all__ = [
    "calculate_coverage",
    "letter_grade",
    "calculate_governance_grade",
]


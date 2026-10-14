#!/usr/bin/env python3
"""JIT Cell Expression Engine — Soma v0.30

Implements just-in-time governance delivery based on context engineering research:
- Gloaguen et al. (2026): Static context files don't improve task success
- ACE (2025): Evolving, curated context improves agent performance by 10%+

Instead of dumping all rules into the system prompt, this engine:
1. Reads the current git diff to identify changed files
2. Matches cells by target_paths (fnmatch)
3. Ranks by Bayesian fitness score (highest first)
4. Returns only the top N cells (default: 3) with full guidance text
5. Includes relevant non-standard genome rules

Dependency policy: pyyaml is OPTIONAL here. aegis_mcp/ must import and run on a
bare interpreter (see .soma/cells/walls/wall-mcp-zero-deps.md), so frontmatter
falls back to a stdlib parser covering the YAML subset the cells actually use.
"""
from __future__ import annotations

import os
import sys
from typing import Any
import glob
import re
import subprocess
import fnmatch

yaml = None  # Backward-compatible sentinel: zero-dependency runtime

from aegis_mcp.cell_cache import CellCache

# Module-level singleton — persists across MCP tool invocations
_cell_cache = CellCache()

# Ensure parent dir is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def warn(message: str) -> None:
    """Emit a diagnostic on STDERR.

    stdout is the JSON-RPC transport — never write diagnostics there.
    """
    try:
        print(f"[soma-mcp] {message}", file=sys.stderr, flush=True)
    except Exception:
        pass


from aegis_core.somayaml import (
    FrontmatterError,
    parse_yaml_subset,
    parse_frontmatter,
    _get_body,
)
from aegis_core.scoring import compute_cell_fitness, compute_salience
from aegis_core.ast_match import match_ast_triggers, prefilter_ast_tokens

def estimate_tokens(text: object | None) -> int:
    """Estimate token count using fast stdlib heuristic (~1.35 tokens per word).

    Handles strings, non-string objects, and None safely without raising AttributeError.
    """
    if text is None:
        return 0
    if not isinstance(text, str):
        try:
            text = str(text)
        except Exception:
            return 0
    words = len(text.split())
    return int(words * 1.35)


def resolve_token_budget(workspace: str | None, max_tokens: int | None = None) -> int:
    """Resolve JIT context token budget with precedence: arg > env > config > default(2000)."""
    # 1. Explicit max_tokens argument
    if max_tokens is not None:
        try:
            return int(max_tokens)
        except (ValueError, TypeError):
            pass

    # 2. Environment variable SOMA_MAX_JIT_TOKENS
    env_val = os.environ.get("SOMA_MAX_JIT_TOKENS")
    if env_val:
        try:
            return int(env_val.strip())
        except (ValueError, TypeError):
            pass

    # 3. Workspace soma.conf configuration
    if workspace:
        conf_path = os.path.join(workspace, "soma.conf")
        if os.path.isfile(conf_path):
            try:
                with open(conf_path, encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line.startswith("#"):
                            continue
                        lowered = line.lower()
                        if lowered.startswith("max_jit_tokens=") or lowered.startswith("max_jit_tokens:"):
                            sep = "=" if "=" in line else ":"
                            val = line.split(sep, 1)[1].strip().strip('"').strip("'")
                            return int(val)
            except Exception:
                pass

    # 4. Default fallback: 2000 tokens
    return 2000


def get_git_diff_files(workspace: str) -> list[str]:
    """Get files changed in the current working tree + staged."""
    files = set()
    for cmd in [['git', 'diff', '--name-only'],
                ['git', 'diff', '--name-only', '--cached']]:
        try:
            output = subprocess.check_output(
                cmd, cwd=workspace, text=True, stderr=subprocess.DEVNULL,
                timeout=10,
            ).strip()
            if output:
                files.update(f for f in output.splitlines() if f)
        except Exception:
            pass
    return list(files)


def load_all_cells(workspace: str) -> list[dict[str, object]]:
    """Load all cells from .aegis/rules/ or .soma/cells/ using stdlib parser."""
    cells = []
    cells_dir = os.path.join(workspace, '.aegis', 'rules')
    if not os.path.isdir(cells_dir):
        cells_dir = os.path.join(workspace, '.soma', 'cells')
    if not os.path.isdir(cells_dir):
        return cells

    for cell_file in glob.glob(os.path.join(cells_dir, '**', '*.md'), recursive=True):
        if os.path.basename(cell_file) == 'README.md':
            continue
        rel = os.path.relpath(cell_file, workspace)
        try:
            with open(cell_file, encoding="utf-8-sig") as f:
                content = f.read()
            fm = parse_frontmatter(content)
            if fm is None:
                warn(f'skipped cell {rel}: malformed YAML frontmatter')
                continue
            if not fm:
                warn(f'skipped cell {rel}: no frontmatter metadata')
                continue
            # Skip expired cells (pruned by cell_expiry --prune)
            if fm.get('expired_at'):
                continue
            fm['_name'] = os.path.splitext(os.path.basename(cell_file))[0]
            fm['_path'] = rel
            fm['_body'] = _get_body(content)
            fm['_full'] = content
            cells.append(fm)
        except Exception as e:
            warn(f'skipped cell {rel}: {e.__class__.__name__}: {e}')
    return cells


def match_cells_for_diff(
    cells: list[dict[str, Any]],
    changed_files: list[str],
    diff_text: str = "",
    repo_root: str = "",
) -> list[dict[str, Any]]:
    """Match cells against changed files using AST syntactic triggers and target_paths globs.

    Returns a list of match records, each containing the matched cell, match_type,
    and matched_files.
    """
    matched = []
    for cell in cells:
        ast_trigs = cell.get("ast_triggers")
        target_paths = cell.get("target_paths", [])
        if isinstance(target_paths, str):
            target_paths = [target_paths]

        is_match = False
        match_type = "glob_match"
        matched_files = []

        # 1. Syntactic AST triggers (highest precision)
        if ast_trigs and isinstance(ast_trigs, dict):
            for f in changed_files:
                f_path = os.path.join(repo_root, f) if repo_root else f
                ast_matched, details = match_ast_triggers(
                    ast_trigs,
                    file_path=f_path,
                    diff_text=diff_text,
                )
                if ast_matched:
                    is_match = True
                    match_type = "ast_match"
                    matched_files.append(f)

        # 2. Path matching (if not already matched by AST or if cell has target_paths)
        if not is_match and target_paths:
            for changed in changed_files:
                base = os.path.basename(changed)
                for pattern in target_paths:
                    if changed == pattern:
                        is_match = True
                        match_type = "exact_path"
                        matched_files.append(changed)
                        break
                    elif fnmatch.fnmatch(changed, pattern) or fnmatch.fnmatch(base, pattern):
                        is_match = True
                        if match_type != "exact_path":
                            match_type = "glob_match"
                        matched_files.append(changed)
                        break

        if is_match:
            cell_copy = cell.copy()
            unique_files = list(set(matched_files))
            cell_copy["_matched_files"] = unique_files
            cell_copy["match_type"] = match_type
            match_entry = {
                "cell": cell_copy,
                "match_type": match_type,
                "matched_files": unique_files,
                **cell_copy,
            }
            matched.append(match_entry)

    return matched


def match_cells_to_files(cells: list[dict[str, object]], changed_files: list[str]) -> list[dict[str, object]]:
    """Match cells to changed files by target_paths (fnmatch) and AST triggers."""
    matches = match_cells_for_diff(cells, changed_files)
    return [m["cell"] for m in matches]


def get_fitness_score(cell: dict[str, object]) -> float:
    """Extract fitness score from cell using canonical aegis_core.scoring."""
    return compute_cell_fitness(cell)


def rank_cells(matched_cells: list[dict[str, object]]) -> list[dict[str, object]]:
    """Rank matched cells by Salience score (highest first), with diversity bonus."""
    for cell in matched_cells:
        cell['_fitness_score'] = get_fitness_score(cell)
        cell['_salience'] = compute_salience(cell, match_type=cell.get('match_type', 'glob_match'))

    # Sort by salience (descending), then fitness, then match count
    return sorted(
        matched_cells,
        key=lambda c: (c['_salience'], c['_fitness_score'], len(c.get('_matched_files', []))),
        reverse=True
    )


def ensure_type_diversity(ranked_cells: list[dict[str, object]], budget: int) -> list[dict[str, object]]:
    """Ensure we don't load N cells of the same type. Prefer diversity."""
    selected = []
    seen_types = set()

    # First pass: one of each type
    for cell in ranked_cells:
        ctype = cell.get('type', 'unknown')
        if ctype not in seen_types and len(selected) < budget:
            selected.append(cell)
            seen_types.add(ctype)

    # Second pass: fill remaining budget
    for cell in ranked_cells:
        if cell not in selected and len(selected) < budget:
            selected.append(cell)

    return selected


def format_cell_guidance(cell: dict[str, object]) -> dict[str, object]:
    """Format a cell into actionable, concise guidance text."""
    ctype = cell.get('type', 'unknown')
    hypothesis = cell.get('hypothesis', '')
    prediction = cell.get('prediction', '')
    body = cell.get('_body', '')
    name = cell.get('_name', '')
    matched = cell.get('_matched_files', [])
    fitness = cell.get('_fitness_score', 0)

    type_emoji = {
        'wall': '🧱',
        'vacuole': '🧫',
        'membrane': '🔬',
        'chloroplast': '🌿',
        'plasmodesmata': '🔗'
    }.get(ctype, '📋')

    type_label = {
        'wall': 'INVARIANT (must not violate)',
        'vacuole': 'ANTI-PATTERN TRAP (watch out)',
        'membrane': 'ESCALATION GATE (needs review)',
        'chloroplast': 'BEST PRACTICE (follow this pattern)',
        'plasmodesmata': 'CONTRACT (cross-service agreement)'
    }.get(ctype, ctype.upper())

    guidance = f"{type_emoji} [{type_label}] {name}\n"
    guidance += f"   Hypothesis: {hypothesis}\n"
    if prediction:
        guidance += f"   If violated: {prediction}\n"
    if matched:
        guidance += f"   Triggered by: {', '.join(matched[:5])}\n"
    if body:
        # Truncate body to keep context tight
        body_lines = body.strip().split('\n')[:8]
        guidance += f"   Detail: {' '.join(line.strip() for line in body_lines)[:300]}\n"
    guidance += f"   Fitness: {fitness:.2f}\n"

    return {
        'name': name,
        '_path': cell.get('_path', ''),
        'type': ctype,
        'enforcement': type_label,
        'hypothesis': hypothesis,
        'prediction': prediction,
        'matched_files': matched,
        'fitness': fitness,
        'guidance': guidance,
        'body': body[:500] if body else ''
    }


def compress_to_atomic_directive(cell: dict[str, Any]) -> str:
    """Compress a security gate cell into an Atomic Invariant Directive.

    Strips historical prose, examples, and detailed explanations while preserving
    the core invariant statement, enforcement consequence, and trigger patterns.
    Typically consumes ~35-55 tokens.
    """
    cid = cell.get("id") or cell.get("_name") or cell.get("name") or "gate-contract"
    hypothesis = cell.get("hypothesis") or cell.get("name") or "Security contract"
    prediction = cell.get("prediction") or "Contract violation causes security failure"

    patterns = []
    ast_trigs = cell.get("ast_triggers") or {}
    if isinstance(ast_trigs, dict):
        for k, v in ast_trigs.items():
            if v:
                patterns.append(f"AST {k}: {v}")
    target_paths = cell.get("target_paths") or []
    if target_paths:
        if isinstance(target_paths, str):
            patterns.append(f"Paths: {target_paths}")
        else:
            patterns.append(f"Paths: {', '.join(str(p) for p in target_paths[:3])}")
    pattern_str = " | ".join(patterns) if patterns else "All matching files"

    return (
        f"### 🛡️ [GATE: ATOMIC] {cid}\n"
        f"- **Invariant**: {hypothesis}\n"
        f"- **Consequence**: {prediction}\n"
        f"- **Pattern**: {pattern_str}\n"
    )


def pack_two_tier_context(
    gates: list[dict[str, Any]],
    advisory: list[dict[str, Any]],
    total_budget: int = 2000,
    tier1_ratio: float = 0.60,
) -> dict[str, Any]:
    """Partitioned 2-Tier Token Budget packing with Incompressible Gate Guarantee.

    Allocation:
    - Tier 1: Security Gates (guaranteed 60% = 1200 tokens default)
    - Tier 2: Advisory Rules (dynamic headroom, up to remaining budget)

    Degradation ladder:
    1. If gates fit in Tier 1 budget: gates full-fidelity, unused headroom flows to Tier 2.
    2. If gates exceed Tier 1 budget (<= 1800 tokens): Tier 2 dropped to 0, gates pack full-fidelity up to budget.
    3. Extreme Gate Pressure: Gates are NEVER dropped. Overflow gates compress into Atomic Invariant Directives.
    4. Advisory cells sorted by descending Salience.
    """
    tier1_budget = int(total_budget * tier1_ratio)

    def _get_salience(c: dict[str, Any]) -> float:
        if "_salience" in c:
            try:
                return float(c["_salience"])
            except (ValueError, TypeError):
                pass
        match_type = c.get("match_type", "glob_match")
        return compute_salience(c, match_type=match_type)

    sorted_gates = sorted(gates, key=_get_salience, reverse=True)
    sorted_advisory = sorted(advisory, key=_get_salience, reverse=True)

    def _full_content(c: dict[str, Any]) -> str:
        if "_full" in c and c["_full"]:
            return str(c["_full"])
        body = c.get("body") or c.get("_body") or ""
        fg = format_cell_guidance(c)
        if body and len(body) > 300:
            return f"{fg['guidance']}\n   Full Detail: {body}"
        return fg["guidance"]

    gate_sizes = []
    for g in sorted_gates:
        full_text = _full_content(g)
        full_tok = estimate_tokens(full_text)
        atomic_text = compress_to_atomic_directive(g)
        atomic_tok = estimate_tokens(atomic_text)
        gate_sizes.append({
            "cell": g,
            "full_text": full_text,
            "full_tokens": full_tok,
            "atomic_text": atomic_text,
            "atomic_tokens": atomic_tok,
        })

    total_full_gate_tokens = sum(item["full_tokens"] for item in gate_sizes)

    expressed_gates: list[dict[str, Any]] = []
    used_gate_tokens = 0

    if total_full_gate_tokens <= total_budget:
        for item in gate_sizes:
            cell_data = item["cell"].copy()
            cell_data["compressed"] = False
            cell_data["content"] = item["full_text"]
            cell_data["tokens"] = item["full_tokens"]
            expressed_gates.append(cell_data)
            used_gate_tokens += item["full_tokens"]
    else:
        # Extreme gate pressure: pack full fidelity as many as fit within tier1_budget,
        # and compress the rest into Atomic Invariant Directives
        for i, item in enumerate(gate_sizes):
            remaining_atomic_tokens = sum(g["atomic_tokens"] for g in gate_sizes[i+1:])
            if (used_gate_tokens + item["full_tokens"] + remaining_atomic_tokens <= total_budget
                    and used_gate_tokens + item["full_tokens"] <= tier1_budget):
                cell_data = item["cell"].copy()
                cell_data["compressed"] = False
                cell_data["content"] = item["full_text"]
                cell_data["tokens"] = item["full_tokens"]
                expressed_gates.append(cell_data)
                used_gate_tokens += item["full_tokens"]
            else:
                cell_data = item["cell"].copy()
                cell_data["compressed"] = True
                cell_data["content"] = item["atomic_text"]
                cell_data["tokens"] = item["atomic_tokens"]
                expressed_gates.append(cell_data)
                used_gate_tokens += item["atomic_tokens"]

    # Calculate available budget for Tier 2 Advisory Rules
    if total_full_gate_tokens > tier1_budget:
        advisory_budget = 0
    else:
        advisory_budget = max(0, total_budget - used_gate_tokens)

    expressed_advisory: list[dict[str, Any]] = []
    used_advisory_tokens = 0

    for a in sorted_advisory:
        a_text = _full_content(a)
        a_tok = estimate_tokens(a_text)
        if used_advisory_tokens + a_tok <= advisory_budget:
            cell_data = a.copy()
            cell_data["compressed"] = False
            cell_data["content"] = a_text
            cell_data["tokens"] = a_tok
            expressed_advisory.append(cell_data)
            used_advisory_tokens += a_tok

    total_tokens = used_gate_tokens + used_advisory_tokens
    clamped = (len(expressed_advisory) < len(advisory)) or any(g.get("compressed") for g in expressed_gates)

    return {
        "expressed_gates": expressed_gates,
        "expressed_advisory": expressed_advisory,
        "total_tokens": total_tokens,
        "gate_tokens": used_gate_tokens,
        "advisory_tokens": used_advisory_tokens,
        "clamped": clamped,
    }


def extract_target_constraints(cells: list[dict[str, object]], changed_files: list[str]) -> list[dict[str, object]]:
    """Extract structured constraints for target files to pre-seed invariants before editing (Issue #77)."""
    constraints = []
    for cell in cells:
        name = cell.get('_name') or cell.get('name', 'unnamed')
        ctype = cell.get('type', 'advisory')
        enforcement = cell.get('enforcement', ctype)
        hypothesis = cell.get('hypothesis', '')
        prediction = cell.get('prediction', '')
        matched = cell.get('_matched_files', [])
        constraints.append({
            'name': name,
            'type': ctype,
            'tier': enforcement,
            'hypothesis': hypothesis,
            'prediction': prediction,
            'matched_files': matched or list(changed_files),
        })
    return constraints


def load_genome_rules(workspace: str, changed_files: list[str]) -> list[dict[str, str]]:
    """Load genome rules marked as non_standard that match changed files."""
    try:
        from aegis_core.workspace import Workspace
        ws = Workspace.resolve(workspace)
        if not ws.is_soma_repo:
            return []
    except Exception:
        return []

    genome_dir = os.path.join(workspace, 'rules')
    if not os.path.isdir(genome_dir):
        genome_dir = os.path.join(workspace, 'genome')
    if not os.path.isdir(genome_dir):
        return []

    relevant = []
    for rule_file in sorted(glob.glob(os.path.join(genome_dir, '*.md'))):
        rel = os.path.relpath(rule_file, workspace)
        try:
            with open(rule_file, encoding="utf-8-sig") as f:
                content = f.read()
            fm = parse_frontmatter(content)
            if fm is None:
                warn(f'skipped genome rule {rel}: malformed YAML frontmatter')
                continue
            # Only include non-standard rules
            non_standard = fm.get('non_standard', 'false')
            if str(non_standard).lower() not in ('true', 'yes', '1'):
                continue
            # Include if it has target_paths matching, or if it has no target_paths (global)
            target_paths = fm.get('target_paths', [])
            if isinstance(target_paths, str):
                target_paths = [target_paths]
            if not target_paths:
                # Global non-standard rule — always include
                body = _get_body(content)
                relevant.append({
                    'name': os.path.splitext(os.path.basename(rule_file))[0],
                    'body': body[:500] if body else '',
                    'category': fm.get('category', 'general')
                })
            else:
                # Check if any changed files match
                for changed in changed_files:
                    for pattern in target_paths:
                        if fnmatch.fnmatch(changed, pattern):
                            body = _get_body(content)
                            relevant.append({
                                'name': os.path.splitext(os.path.basename(rule_file))[0],
                                'body': body[:500] if body else '',
                                'category': fm.get('category', 'general')
                            })
                            break
                    else:
                        continue
                    break
        except Exception as e:
            warn(f'skipped genome rule {rel}: {e.__class__.__name__}: {e}')
    return relevant


def express(
    workspace: str,
    changed_files: list[str] | None = None,
    budget: int | None = None,
    max_tokens: int | None = None,
) -> dict[str, object]:
    """Main JIT expression function.

    Returns the minimum effective governance context for the current change,
    clamped to rule count (budget) and token budget (max_tokens).
    """
    token_budget = resolve_token_budget(workspace, max_tokens)

    if budget is None:
        budget = int(os.environ.get('SOMA_CONTEXT_BUDGET', '3'))

    if not changed_files:
        changed_files = get_git_diff_files(workspace)

    if not changed_files:
        return {
            'relevant_cells': [],
            'genome_guidance': [],
            'target_constraints': [],
            'context': 'No changed files detected. Governance guidance will be provided when files are modified.',
            'stats': {
                'total_cells': 0,
                'matched': 0,
                'expressed': 0,
                'budget': budget,
                'changed_files': 0,
                'estimated_tokens': 0,
                'max_tokens_budget': token_budget,
                'clamped': False,
            }
        }

    # Load and match cells
    all_cells = _cell_cache.get_cells(workspace)
    matched = match_cells_to_files(all_cells, changed_files)

    # Score ALL matched cells first (fixes C3: mandatory cells displaying Fitness: 0.00)
    for cell in matched:
        cell['_fitness_score'] = get_fitness_score(cell)

    # Apply hot zone boost from bug registry (v0.85 antifragile loop)
    try:
        from aegis_sdk.hot_zones import compute_cell_boost, load_report_from_workspace
        hz_report = load_report_from_workspace(workspace)
        if hz_report and (hz_report.active_file_zones or hz_report.active_pattern_zones):
            for cell in matched:
                fitness = cell.get('fitness', {})
                tp = int(fitness.get('true_positives', 0)) if isinstance(fitness, dict) else 0
                fp = int(fitness.get('false_positives', 0)) if isinstance(fitness, dict) else 0
                outcome_count = tp + fp
                boost = compute_cell_boost(cell, hz_report, outcome_count)
                if boost > 0:
                    cell['_fitness_score'] *= (1 + boost)
                    cell['_hot_zone_boost'] = boost
    except ImportError:
        pass  # Graceful degradation

    # Stage 0: Mandatory invariants — walls and gate-tier cells always load
    mandatory = []
    candidates = []
    for cell in matched:
        cell_type = cell.get('type', 'vacuole')
        enforcement = cell.get('enforcement', 'advisory')
        if cell_type == 'wall' or enforcement == 'gate':
            mandatory.append(cell)
        else:
            candidates.append(cell)

    # Stage 1-2: Rank and diversify remaining candidates within leftover budget
    remaining_budget = max(0, budget - len(mandatory))
    ranked = rank_cells(candidates)
    selected_candidates = ensure_type_diversity(ranked, remaining_budget)

    # Stage 3: Pre-seed constraints and token budget clamping (Issue #75 & Issue #77)
    target_constraints = extract_target_constraints(matched, changed_files)
    early_warning_parts = []
    wall_constraints = [c for c in target_constraints if c.get('tier') == 'wall' or c.get('type') == 'wall']

    if wall_constraints:
        early_warning_parts.append("## Pre-Edit Invariants & Constraints\n")
        early_warning_parts.append("CRITICAL: You must adhere to the following invariants when modifying target files:\n")
        for wc in wall_constraints:
            early_warning_parts.append(f"- 🧱 [INVARIANT] {wc['name']}: {wc['hypothesis']}\n")

    early_warning_text = "".join(early_warning_parts)
    accumulated_tokens = estimate_tokens(early_warning_text)
    expressed_cells = []
    clamped = False

    # Mandatory cells are prioritized
    for cell in mandatory:
        fg = format_cell_guidance(cell)
        cell_tokens = estimate_tokens(fg['guidance'])
        if accumulated_tokens + cell_tokens <= token_budget:
            expressed_cells.append(fg)
            accumulated_tokens += cell_tokens
        else:
            expressed_cells.append(fg)
            accumulated_tokens += cell_tokens
            clamped = True

    # Candidate cells fill remaining budget
    for cell in selected_candidates:
        fg = format_cell_guidance(cell)
        cell_tokens = estimate_tokens(fg['guidance'])
        if accumulated_tokens + cell_tokens <= token_budget:
            expressed_cells.append(fg)
            accumulated_tokens += cell_tokens
        else:
            clamped = True

    # Load matching non-standard genome rules
    genome_rules = load_genome_rules(workspace, changed_files)
    expressed_genome = []
    for rule in genome_rules:
        rule_text = f"### {rule['name']}\n{rule['body']}\n"
        rule_tokens = estimate_tokens(rule_text)
        if accumulated_tokens + rule_tokens <= token_budget:
            expressed_genome.append(rule)
            accumulated_tokens += rule_tokens
        else:
            clamped = True

    # Build the combined guidance text
    guidance_parts = []
    if early_warning_parts:
        guidance_parts.extend(early_warning_parts)

    if expressed_cells:
        guidance_parts.append("## Active Governance Cells\n")
        for cg in expressed_cells:
            guidance_parts.append(cg['guidance'])

    if expressed_genome:
        guidance_parts.append("\n## Project-Specific Rules\n")
        for rule in expressed_genome:
            guidance_parts.append(f"### {rule['name']}\n{rule['body']}\n")

    combined = '\n'.join(guidance_parts) if guidance_parts else 'No governance cells match your current changes.'
    total_tokens = estimate_tokens(combined)

    return {
        'relevant_cells': expressed_cells,
        'genome_guidance': expressed_genome,
        'target_constraints': target_constraints,
        'context': combined,
        'stats': {
            'total_cells': len(all_cells),
            'matched': len(matched),
            'expressed': len(expressed_cells),
            'budget': budget,
            'changed_files': len(changed_files),
            'estimated_tokens': total_tokens,
            'max_tokens_budget': token_budget,
            'clamped': clamped,
        }
    }

#!/usr/bin/env python3
"""JIT rule expression engine.

Instead of loading every rule into the system prompt, aegis_scan returns only the
rules for the files about to change:

1. Read the changed files (the caller's list, or the git diff).
2. Match rules by target_paths (fnmatch on the path and the basename).
3. Gates and invariants always load; other rules are ranked by salience and
   fitness, kept type-diverse, and capped by a rule count.
4. The whole response is clamped to the token budget (AEGIS_MAX_JIT_TOKENS):
   a rule that does not fit is omitted and counted, never silently dropped.

aegis_mcp imports only the standard library and aegis_core.
"""
from __future__ import annotations

import fnmatch
import glob
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from aegis_core.scoring import compute_cell_fitness, compute_salience
from aegis_core.taxonomy import (
    JIT_DEFAULT_MAX_TOKENS,
    JIT_DEFAULT_RULE_COUNT_BUDGET,
    SUBPROCESS_DEFAULT_TIMEOUT_SECONDS,
    WORDS_TO_TOKENS_FACTOR,
)
from aegis_core.workspace.layout import WorkspaceLayout
from aegis_core.yaml_engine.frontmatter import _get_body, parse_frontmatter
from aegis_mcp.rule_cache import CellCache

# Module-level singleton — persists across MCP tool invocations
_cell_cache = CellCache()

# The server sends a scan as json.dumps(result), which is ASCII, so a response the
# budget admits is at most 4 bytes per budgeted token.
ASCII_CHARS_PER_TOKEN = 4

NO_CHANGES_TEXT = "No changed files detected. Governance guidance will be provided when files are modified."
NO_MATCH_TEXT = "No governance rules match your current changes."


def warn(message: str) -> None:
    """Emit a diagnostic on STDERR.

    stdout is the JSON-RPC transport — never write diagnostics there.
    """
    try:
        print(f"[aegis-mcp] {message}", file=sys.stderr, flush=True)
    except Exception:
        pass


def estimate_tokens(text: object | None) -> int:
    """Estimate a token count: the larger of ~1.35 per word and one per 4 ASCII characters
    plus one per non-ASCII character.

    A word count alone sees text without spaces (CJK, base64, a minified line) as a
    single word, so the character floor is what lets the budget bound the bytes sent.
    Handles strings, non-string objects, and None safely without raising AttributeError.
    """
    if text is None:
        return 0
    if not isinstance(text, str):
        try:
            text = str(text)
        except Exception:
            return 0
    ascii_chars = len(text.encode("ascii", "ignore"))
    by_chars = -(-ascii_chars // ASCII_CHARS_PER_TOKEN) + (len(text) - ascii_chars)
    by_words = int(len(text.split()) * WORDS_TO_TOKENS_FACTOR)
    return max(by_words, by_chars)


def resolve_token_budget(workspace: str | None, max_tokens: int | None = None) -> int:
    """Resolve JIT context token budget with precedence: arg > env > config > default(2000)."""
    if max_tokens is not None:
        try:
            return int(max_tokens)
        except (ValueError, TypeError):
            pass

    env_val = os.environ.get("AEGIS_MAX_JIT_TOKENS")
    if env_val:
        try:
            return int(env_val.strip())
        except (ValueError, TypeError):
            pass

    if workspace:
        conf_path = os.path.join(workspace, "aegis.conf")
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

    return JIT_DEFAULT_MAX_TOKENS


def get_git_diff_files(workspace: str) -> list[str]:
    """Get files changed in the current working tree + staged."""
    files = set()
    for cmd in [['git', 'diff', '--name-only'],
                ['git', 'diff', '--name-only', '--cached']]:
        try:
            output = subprocess.check_output(
                cmd, cwd=workspace, text=True, stderr=subprocess.DEVNULL,
                timeout=SUBPROCESS_DEFAULT_TIMEOUT_SECONDS,
            ).strip()
            if output:
                files.update(f for f in output.splitlines() if f)
        except Exception:
            pass
    return list(files)


def load_all_cells(workspace: str) -> list[dict[str, object]]:
    """Load all rules from .aegis/rules/ using stdlib parser."""
    cells = []
    cells_dir = str(WorkspaceLayout(Path(workspace)).rules_dir)
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


def _path_match_type(target_paths: list[str], changed: str) -> str | None:
    base = os.path.basename(changed)
    for pattern in target_paths:
        if changed == pattern:
            return "exact_path"
        if (
            fnmatch.fnmatch(changed, pattern)
            or fnmatch.fnmatch(base, pattern)
            or (pattern.startswith("**/") and (fnmatch.fnmatch(changed, pattern[3:]) or fnmatch.fnmatch(base, pattern[3:])))
        ):
            return "glob_match"
    return None


def match_cells_to_files(
    cells: list[dict[str, object]],
    changed_files: list[str],
) -> list[dict[str, object]]:
    """Match rules to changed files by target_paths.

    Each match is a copy of the rule carrying ``_matched_files`` and ``match_type``
    (``exact_path`` when a changed file equals a pattern, else ``glob_match``).
    """
    matched = []
    for cell in cells:
        target_paths = cell.get("target_paths") or cell.get("paths") or cell.get("globs") or []
        if isinstance(target_paths, str):
            target_paths = [target_paths]
        if not target_paths:
            continue

        match_type = None
        matched_files = []
        for changed in changed_files:
            kind = _path_match_type(target_paths, changed)
            if kind is None:
                continue
            matched_files.append(changed)
            if kind == "exact_path" or match_type is None:
                match_type = kind

        if matched_files:
            cell_copy = cell.copy()
            cell_copy["_matched_files"] = list(dict.fromkeys(matched_files))
            cell_copy["match_type"] = match_type
            matched.append(cell_copy)
    return matched


def get_fitness_score(cell: dict[str, object]) -> float:
    """Extract fitness score from cell using canonical aegis_core.scoring."""
    return compute_cell_fitness(cell)


def rank_cells(matched_cells: list[dict[str, object]]) -> list[dict[str, object]]:
    """Rank matched cells by Salience score (highest first), with diversity bonus."""
    for cell in matched_cells:
        cell['_fitness_score'] = get_fitness_score(cell)
        cell['_salience'] = compute_salience(cell, match_type=cell.get('match_type', 'glob_match'))

    return sorted(
        matched_cells,
        key=lambda c: (c['_salience'], c['_fitness_score'], len(c.get('_matched_files', []))),
        reverse=True
    )


def ensure_type_diversity(ranked_cells: list[dict[str, object]], budget: int) -> list[dict[str, object]]:
    """Ensure we don't load N cells of the same type. Prefer diversity."""
    selected = []
    seen_types = set()

    for cell in ranked_cells:
        ctype = cell.get('type', 'unknown')
        if ctype not in seen_types and len(selected) < budget:
            selected.append(cell)
            seen_types.add(ctype)

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
        'invariant': '🧱',
        'trap': '🧫',
        'membrane': '🔬',
        'boundary': '🔬',
        'persona': '🌿',
        'contract': '🔗',
    }.get(ctype, '📋')

    type_label = {
        'wall': 'INVARIANT (must not violate)',
        'invariant': 'INVARIANT (must not violate)',
        'trap': 'ANTI-PATTERN TRAP (watch out)',
        'membrane': 'ESCALATION GATE (needs review)',
        'boundary': 'ESCALATION GATE (needs review)',
        'persona': 'BEST PRACTICE (follow this pattern)',
        'contract': 'CONTRACT (cross-service agreement)',
    }.get(ctype, ctype.upper())

    guidance = f"{type_emoji} [{type_label}] {name}\n"
    guidance += f"   Hypothesis: {hypothesis}\n"
    if prediction:
        guidance += f"   If violated: {prediction}\n"
    if matched:
        guidance += f"   Triggered by: {', '.join(matched[:5])}\n"
    if body:
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
        from aegis_core.workspace.base import Workspace
        ws = Workspace.resolve(workspace)
        if not ws.is_aegis_repo:
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
            non_standard = fm.get('non_standard', 'false')
            if str(non_standard).lower() not in ('true', 'yes', '1'):
                continue
            target_paths = fm.get('target_paths', [])
            if isinstance(target_paths, str):
                target_paths = [target_paths]
            if not target_paths or any(
                fnmatch.fnmatch(changed, pattern) for changed in changed_files for pattern in target_paths
            ):
                body = _get_body(content)
                relevant.append({
                    'name': os.path.splitext(os.path.basename(rule_file))[0],
                    'body': body[:500] if body else '',
                    'category': fm.get('category', 'general')
                })
        except Exception as e:
            warn(f'skipped genome rule {rel}: {e.__class__.__name__}: {e}')
    return relevant


def _is_mandatory(cell: dict[str, Any]) -> bool:
    """Gates and invariants load before any ranked rule and ignore the rule count."""
    return cell.get('type') in ('wall', 'invariant', 'gate') or cell.get('enforcement') == 'gate'


def _is_invariant(constraint: dict[str, Any]) -> bool:
    return constraint.get('tier') in ('wall', 'invariant') or constraint.get('type') in ('wall', 'invariant')


def _load_rules(workspace: str) -> list[dict[str, Any]]:
    """Rules from .aegis/rules/, or from a top-level rules/ dir when there is no .aegis/rules/."""
    all_cells = list(_cell_cache.get_cells(workspace))
    top_rules_dir = os.path.join(str(workspace), "rules")
    if not os.path.isdir(top_rules_dir) or os.path.isdir(os.path.join(str(workspace), ".aegis", "rules")):
        return all_cells
    seen_names = {c.get("_name") for c in all_cells}
    for rule_file in sorted(glob.glob(os.path.join(top_rules_dir, "**", "*.md"), recursive=True)):
        if os.path.basename(rule_file) == "README.md":
            continue
        name = os.path.splitext(os.path.basename(rule_file))[0]
        if name in seen_names:
            continue
        try:
            with open(rule_file, encoding="utf-8-sig") as f:
                content = f.read()
        except OSError:
            continue
        fm = parse_frontmatter(content)
        if not fm or fm.get("expired_at"):
            continue
        fm["_name"] = name
        fm["_path"] = os.path.relpath(rule_file, str(workspace))
        fm["_body"] = _get_body(content)
        fm["_full"] = content
        all_cells.append(fm)
        seen_names.add(name)
    return all_cells


def _omitted_note(omitted: int) -> str:
    noun = "rule" if omitted == 1 else "rules"
    return f"⚠️ {omitted} more {noun} omitted (raise AEGIS_MAX_JIT_TOKENS)"


def _invariant_line(constraint: dict[str, Any]) -> str:
    return f"- 🧱 [INVARIANT] {constraint['name']}: {constraint['hypothesis']}\n"


def _genome_section(rule: dict[str, Any]) -> str:
    return f"### {rule['name']}\n{rule['body']}\n"


def _render_guidance(staged: list[dict[str, Any]], genome: list[dict[str, Any]], omitted: int) -> str:
    parts = []
    invariants = [s for s in staged if _is_invariant(s['constraint'])]
    if invariants:
        parts.append("## Pre-Edit Invariants & Constraints\n")
        parts.append("CRITICAL: You must adhere to the following invariants when modifying target files:\n")
        parts.extend(_invariant_line(s['constraint']) for s in invariants)
    if staged:
        parts.append("## Active Governance Rules\n")
        parts.extend(s['text'] for s in staged)
    if genome:
        parts.append("\n## Project-Specific Rules\n")
        parts.extend(_genome_section(rule) for rule in genome)
    if omitted:
        parts.append(f"\n{_omitted_note(omitted)}\n")
    return '\n'.join(parts) if parts else NO_MATCH_TEXT


def _payload(staged, genome, omitted, guidance, stats) -> dict[str, Any]:
    return {
        'relevant_rules': [s['item'] for s in staged],
        'guidance': guidance,
        'genome_guidance': genome,
        'invariant_warnings': [s['constraint'] for s in staged if _is_invariant(s['constraint'])],
        'rules_staged': len(staged),
        'stats': dict(stats, clamped=omitted > 0, omitted=omitted),
    }


def _payload_tokens(payload: object) -> int:
    """Tokens of a value as the server serializes it (json.dumps, ASCII-escaped)."""
    return estimate_tokens(json.dumps(payload))


def express(
    workspace: str,
    changed_files: list[str] | None = None,
    budget: int | None = None,
    max_tokens: int | None = None,
) -> dict[str, object]:
    """Main JIT expression function.

    Returns the rules for the current change. ``budget`` caps how many optional
    (non-gate, non-invariant) rules load; ``max_tokens`` bounds the whole response,
    gates included, and every rule that does not fit is counted in stats.omitted.
    """
    token_budget = resolve_token_budget(workspace, max_tokens)
    if budget is None:
        budget = JIT_DEFAULT_RULE_COUNT_BUDGET

    if not changed_files:
        changed_files = get_git_diff_files(workspace)

    stats = {
        'total_rules': 0,
        'matched': 0,
        'budget': budget,
        'changed_files': len(changed_files),
        'estimated_tokens': 0,
        'max_tokens_budget': token_budget,
    }
    if not changed_files:
        payload = _payload([], [], 0, NO_CHANGES_TEXT, stats)
        payload['stats']['estimated_tokens'] = _payload_tokens(payload)
        return payload

    all_cells = _load_rules(workspace)
    matched = match_cells_to_files(all_cells, changed_files)
    stats['total_rules'] = len(all_cells)
    stats['matched'] = len(matched)

    mandatory = rank_cells([c for c in matched if _is_mandatory(c)])
    candidates = rank_cells([c for c in matched if not _is_mandatory(c)])
    selected = ensure_type_diversity(candidates, max(0, budget - len(mandatory)))

    # The rendered text carries the detail; the structured item is the index of it.
    entries = []
    for cell in mandatory + selected:
        item = format_cell_guidance(cell)
        text = item.pop('guidance')
        item.pop('body')
        constraint = extract_target_constraints([cell], changed_files)[0]
        entries.append({'item': item, 'text': text, 'constraint': constraint})
    genome_rules = load_genome_rules(workspace, changed_files)

    # Fill in priority order and stop at the first rule that does not fit, so a
    # lower-priority rule never displaces a gate. Then confirm against the serialized
    # response: the per-entry estimate is additive only up to rounding.
    used = _payload_tokens(_payload([], [], 0, _render_guidance([], [], 1), stats))
    staged, genome, omitted = [], [], 0
    for entry in entries:
        cost = _payload_tokens(entry['item']) + _payload_tokens(entry['text'])
        if _is_invariant(entry['constraint']):
            cost += _payload_tokens(entry['constraint']) + _payload_tokens(_invariant_line(entry['constraint']))
        if omitted or used + cost > token_budget:
            omitted += 1
            continue
        staged.append(entry)
        used += cost
    for rule in genome_rules:
        cost = _payload_tokens(rule) + _payload_tokens(_genome_section(rule))
        if omitted or used + cost > token_budget:
            omitted += 1
            continue
        genome.append(rule)
        used += cost

    while True:
        payload = _payload(staged, genome, omitted, _render_guidance(staged, genome, omitted), stats)
        # Measure with the widest count that can pass, so writing the real one cannot overflow.
        payload['stats']['estimated_tokens'] = token_budget
        tokens = _payload_tokens(payload)
        if tokens <= token_budget or not (staged or genome):
            break
        (genome or staged).pop()
        omitted += 1
    payload['stats']['estimated_tokens'] = tokens
    return payload

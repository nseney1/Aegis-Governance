"""aegis_core.insights — Human insight capture, correlation, and candidate synthesis.

Consolidates:
- Human insight capture & coverage correlation (formerly enzymes/insight_capture.py)
- Insight clustering and cell candidate synthesis (formerly enzymes/insight_correlator.py)
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
import sys
from typing import Any, Dict, List, Optional

from aegis_core.workspace import resolve_workspace
from aegis_core.workspace.layout import WorkspaceLayout
from aegis_core.taxonomy import INSIGHT_LAPLACE_PRIOR, ReviewMode, normalize_review_mode
from aegis_core.defects import find_covering_cells, load_cells
from aegis_core.yaml import parse_frontmatter, parse_yaml_subset, dump_frontmatter
from aegis_core.evidence import aggregate_signals


def _load_signal_weight(workspace: str) -> float:
    """Load insight_signal_weight from .aegis/config.yaml, defaulting to 0.5."""
    default = 0.5
    config_path = os.path.join(workspace, ".aegis", "config.yaml")
    if not os.path.exists(config_path):
        return default
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            content = f.read()
        if content.startswith('\ufeff'):
            content = content[1:]
        cfg = parse_frontmatter(content) if content.startswith("---") else parse_yaml_subset(content)
        if isinstance(cfg, dict):
            return float(cfg.get("insight_signal_weight", default))
    except Exception:
        pass
    return default


def _parse_timestamp(ts_str: str) -> datetime:
    """Parse an ISO-8601 timestamp string to a timezone-aware datetime."""
    if ts_str.endswith("Z"):
        ts_str = ts_str[:-1] + "+00:00"
    return datetime.fromisoformat(ts_str)


def capture_insight(
    workspace: str,
    insight: str,
    context_files: list,
    source_conversation: Optional[str] = None,
    category: Optional[str] = None,
    scaffold_wall: bool = False,
    wall_id: Optional[str] = None,
    scaffold_invariant: bool = False,
    invariant_id: Optional[str] = None,
) -> dict:
    """Capture a human insight and persist it to JSONL, optionally scaffolding a Wall or Invariant cell."""
    if not isinstance(context_files, list):
        raise ValueError("context_files must be a list, not " + type(context_files).__name__)
    if not context_files:
        raise ValueError("context_files must not be empty")
    if not insight or not insight.strip():
        raise ValueError("insight must not be empty")

    ws_path = getattr(workspace, "root", workspace)
    layout = WorkspaceLayout(ws_path)
    cells_dir = str(layout.rules_dir)
    if os.path.isdir(cells_dir):
        cells = load_cells(cells_dir)
    else:
        cells = []

    covering = find_covering_cells(cells, context_files)
    covering_cell_names = [c["cell"]["_name"] for c in covering]
    was_covered = len(covering_cell_names) > 0

    signal_weight = _load_signal_weight(ws_path)

    record = {
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "insight": insight,
        "context_files": context_files,
        "source_conversation": source_conversation,
        "category": category,
        "covering_cells": covering_cell_names,
        "was_covered": was_covered,
        "signal_weight": signal_weight,
    }

    if scaffold_wall or wall_id:
        wall_dir = str(layout.rules_dir / "walls")
        os.makedirs(wall_dir, exist_ok=True)
        if wall_id:
            clean_stem = wall_id.strip().lower()
            stem = clean_stem if clean_stem.startswith("wall-") else f"wall-{clean_stem}"
        else:
            h = hashlib.sha256(insight.strip().encode("utf-8")).hexdigest()[:8]
            stem = f"wall-insight-{h}"

        wall_path = os.path.join(wall_dir, f"{stem}.md")
        meta = {
            "id": stem,
            "type": "wall",
            "enforcement": "gate",
            "domain": category or "security",
            "description": insight.strip(),
            "context_files": list(context_files),
        }
        body = f"# {stem}\n\n## Summary\n{insight.strip()}\n\n## Invariants\n- All changes touching context files must satisfy deterministic verification.\n"
        content = dump_frontmatter(meta, body)
        with open(wall_path, "w", encoding="utf-8") as wf:
            wf.write(content)
        record["wall_file"] = wall_path
        record["wall_id"] = stem

    if scaffold_invariant or invariant_id:
        inv_dir = str(layout.rules_dir / "invariants")
        os.makedirs(inv_dir, exist_ok=True)
        if invariant_id:
            clean_stem = invariant_id.strip().lower()
            stem = clean_stem if clean_stem.startswith("invariant-") else f"invariant-{clean_stem}"
        else:
            h = hashlib.sha256(insight.strip().encode("utf-8")).hexdigest()[:8]
            stem = f"invariant-insight-{h}"

        inv_path = os.path.join(inv_dir, f"{stem}.md")
        meta = {
            "id": stem,
            "type": "invariant",
            "enforcement": "gate",
            "domain": category or "security",
            "description": insight.strip(),
            "context_files": list(context_files),
        }
        body = f"# {stem}\n\n## Summary\n{insight.strip()}\n\n## Invariants\n- All changes touching context files must satisfy deterministic verification.\n"
        content = dump_frontmatter(meta, body)
        with open(inv_path, "w", encoding="utf-8") as wf:
            wf.write(content)
        record["invariant_file"] = inv_path
        record["invariant_id"] = stem

    jsonl_path = str(layout.human_insights_file)
    os.makedirs(os.path.dirname(jsonl_path), exist_ok=True)
    with open(jsonl_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")

    return record


def cluster_insights(
    workspace: str,
    min_cluster_size: int = 3,
    window_days: int = 30,
) -> list[dict]:
    """Read human insights and cluster by category within rolling window."""
    jsonl_path = str(WorkspaceLayout(getattr(workspace, "root", workspace)).human_insights_file)
    if not os.path.isfile(jsonl_path):
        return []

    records: list[dict] = []
    with open(jsonl_path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    if not records:
        return []

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=window_days)

    recent: list[dict] = []
    for rec in records:
        ts_str = rec.get("timestamp")
        if not ts_str:
            continue
        try:
            ts = _parse_timestamp(ts_str)
        except (ValueError, TypeError):
            continue
        if ts >= cutoff:
            recent.append(rec)

    if not recent:
        return []

    groups: dict[str, list[dict]] = {}
    for rec in recent:
        cat = rec.get("category") or "uncategorized"
        groups.setdefault(cat, []).append(rec)

    clusters: list[dict] = []
    for category, group in sorted(groups.items()):
        if len(group) < min_cluster_size:
            continue

        common_files: list[str] = []
        seen_files: set[str] = set()
        for rec in group:
            for f in rec.get("context_files", []):
                if f not in seen_files:
                    seen_files.add(f)
                    common_files.append(f)

        insight_count = len(group)
        confidence = round(insight_count / (insight_count + INSIGHT_LAPLACE_PRIOR), 4)

        slug = category.replace(" ", "-").lower()
        file_hash = hashlib.sha256(
            "-".join(sorted(seen_files)).encode()
        ).hexdigest()[:8]
        pattern_id = f"{slug}-{file_hash}"

        clusters.append({
            "pattern_id": pattern_id,
            "insight_count": insight_count,
            "common_files": common_files,
            "common_category": category,
            "confidence": confidence,
        })

    return clusters


def generate_cell_candidates(
    clusters: list[dict],
    workspace: str,
) -> list[dict]:
    """Produce governance-cell candidate dicts from insight clusters."""
    if not clusters:
        return []

    candidates: list[dict] = []
    for cluster in clusters:
        category = cluster.get("common_category", "unknown")
        files = cluster.get("common_files", [])
        files_str = ", ".join(files) if files else "project-wide"

        hypothesis = f"Human attention pattern detected: {category} in {files_str}"

        candidates.append({
            "hypothesis": hypothesis,
            "target_paths": list(files),
            "origin": "human_insight",
            "type": "trap",
            "enforcement": "advisory",
        })

    return candidates
 
 
def create_cell_from_insight_cluster(cluster: dict, workspace: str) -> str:
    """Create a governance cell from an insight cluster."""
    import re
 
    category = cluster.get("common_category") or "unknown"
    files = cluster.get("common_files", [])
    confidence = cluster.get("confidence", 0.5)
    files_str = ", ".join(files) if files else "project-wide"
 
    hypothesis = f"Human attention pattern detected: {category} in {files_str}"
 
    slug = re.sub(r"[^a-z0-9]+", "-", category.lower())[:50].strip("-") or "unknown"
    cell_id = f"trap-{slug}"
 
    frontmatter = {
        "id": cell_id,
        "type": "trap",
        "domain": "correctness",
        "hypothesis": hypothesis,
        "prediction": f"Recurring {category} issues will continue if unaddressed",
        "falsification": f"No {category} insights observed for 60 days",
        "target_paths": list(files),
        "minimum_mode": str(ReviewMode.PATROL),
        "origin": "human_insight",
        "tags": ["auto-generated", "insight-cluster", category],
    }
 
    fm_text = dump_frontmatter(frontmatter)
 
    body = (
        f"This trap was auto-generated from a cluster of human insights "
        f"about **{category}** (confidence {confidence:.2f}).\n"
    )
    cell_content = f"---\n{fm_text}---\n\n{body}"
 
    filename = f"trap-{slug}.md"
    target_dir = os.path.join(workspace, ".aegis", "rules", "traps")
    os.makedirs(target_dir, exist_ok=True)
 
    filepath = os.path.join(target_dir, filename)
    if os.path.isfile(filepath):
        evidence_dir = os.path.join(workspace, ".aegis", "evidence")
        signal_counts = aggregate_signals(evidence_dir).counts
        c_id = frontmatter.get("id", "")
        if signal_counts.get(c_id, {}).get("has_triggers", False):
            return filepath
 
    try:
        os.unlink(filepath)
    except OSError:
        pass
    fd = os.open(filepath, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    with open(fd, "w", encoding="utf-8") as f:
        f.write(cell_content)
 
    return filepath
 
 
__all__ = [
    "capture_insight",
    "cluster_insights",
    "generate_cell_candidates",
    "create_cell_from_insight_cluster",
]

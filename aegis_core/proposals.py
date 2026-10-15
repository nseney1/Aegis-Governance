"""Oracle checkpoint: a mid-session health report of the rules and their ledger evidence.

The TTC verifier, the TTC oracle and propose_change were removed in v4 (ADR 0005 §5).
"""
from __future__ import annotations

import collections
from datetime import datetime, timezone
import glob
import json
import os
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional, Tuple

from aegis_core.evidence import aggregate_signals
from aegis_core.workspace import Workspace


def _parse_cell(filepath: str) -> Tuple[Dict[str, Any], str]:
    """Parse cell frontmatter and body."""
    from aegis_core.lifecycle import parse_cell as _core_parse
    fm, body = _core_parse(filepath)
    return (fm or {}, body)


def _load_fitness_evidence(workspace: Workspace | Path | str) -> Dict[str, Any]:
    """Load canonical signal evidence aggregated per cell id."""
    ws = workspace if isinstance(workspace, Workspace) else (
        Workspace(root=Path(workspace).resolve()) if workspace else Workspace.resolve()
    )
    return aggregate_signals(str(ws.evidence_dir)).counts


def _load_cells(workspace: Workspace | Path | str) -> List[Dict[str, Any]]:
    """Load all rule metadata from .aegis/rules/."""
    ws = workspace if isinstance(workspace, Workspace) else (
        Workspace(root=Path(workspace).resolve()) if workspace else Workspace.resolve()
    )
    cells_dir = ws.rules_dir
    cells = []
    if not cells_dir.is_dir():
        return cells

    for md_file in sorted(glob.glob(os.path.join(str(cells_dir), "**", "*.md"), recursive=True)):
        if os.path.basename(md_file) == "README.md":
            continue
        try:
            metadata, _body = _parse_cell(md_file)
            metadata["_filepath"] = md_file
            if not metadata.get("id"):
                metadata["id"] = metadata.get("name") or Path(md_file).stem
            cells.append(metadata)
        except Exception:
            continue
    return cells


def _parse_iso_date(ts_str: Any) -> Optional[datetime]:
    if not ts_str or not isinstance(ts_str, str):
        return None
    cleaned = ts_str.strip()
    if cleaned.endswith("Z"):
        cleaned = cleaned[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(cleaned)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _classify_cell(cell: Dict[str, Any], evidence: Dict[str, Any], expired_ids: set) -> Tuple[str, str]:
    """Classify a single cell's health status."""
    cell_id = cell.get("id", "")

    # Check expiry first
    if cell_id in expired_ids:
        return "expired", "Past expiry limit"

    # Check evidence
    ev = evidence.get(cell_id)
    if not ev or ev.get("triggers", 0) == 0:
        return "unobserved", "No trigger data recorded"

    triggers = ev["triggers"]
    tp = float(ev.get("tp", 0))
    fp = float(ev.get("fp", 0))
    has_outcomes = ev.get("has_outcomes", False)

    # Dynamic read-time decay: check days since last trigger
    last_trigger_str = ev.get("last_trigger")
    if not last_trigger_str and isinstance(cell.get("fitness"), dict):
        last_trigger_str = cell["fitness"].get("last_trigger_date")

    last_trigger_dt = _parse_iso_date(last_trigger_str)
    days_inactive = 0
    if last_trigger_dt:
        now_utc = datetime.now(timezone.utc)
        days_inactive = max(0, (now_utc - last_trigger_dt).days)

    expiry_days = cell.get("expiry_days")
    if expiry_days:
        try:
            expiry_days = int(expiry_days)
        except (ValueError, TypeError):
            expiry_days = None

    if expiry_days and expiry_days > 60:
        dormant_limit = expiry_days
        decay_limit = expiry_days
    else:
        decay_limit = 30
        dormant_limit = 60

    if days_inactive > dormant_limit:
        return "dormant", f"Inactive for {days_inactive} days (dormant)"
    elif days_inactive > decay_limit:
        return "decaying", f"{int(tp)}/{triggers} true positives ({days_inactive}d inactive, score decaying)"

    if has_outcomes:
        if triggers >= 3 and fp > tp:
            precision = tp / triggers if triggers > 0 else 0
            return "noisy", f"{int(fp)}/{triggers} false positives (precision: {precision:.0%})"
        return "healthy", f"{int(tp)}/{triggers} true positives"

    if triggers >= 5:
        return "active", f"{triggers} triggers (no outcome data yet)"
    return "healthy", f"{triggers} trigger(s) recorded"


def generate_checkpoint(workspace: Optional[Workspace | Path | str] = None, session_count: Optional[int] = None) -> Dict[str, Any]:
    """Generate a mid-session health checkpoint report."""
    ws = workspace if isinstance(workspace, Workspace) else (
        Workspace(root=Path(workspace).resolve()) if workspace else Workspace.resolve()
    )
    cells = _load_cells(ws)
    evidence = _load_fitness_evidence(ws)

    from aegis_core.defects import audit_expiry

    expiry_results = audit_expiry(ws, session_count=session_count)
    expired_ids = {
        r["cell_id"] for r in expiry_results
        if r.get("status") in ("EXPIRED", "EXPIRY_WARNING")
    }

    classifications = collections.defaultdict(list)
    for cell in cells:
        cell_id = cell.get("id", "")
        category, details = _classify_cell(cell, evidence, expired_ids)
        classifications[category].append({
            "cell_id": cell_id,
            "type": cell.get("type", "unknown"),
            "details": details,
        })

    recommendations = []
    expired_count = len(classifications.get("expired", []))
    if expired_count > 0:
        recommendations.append({
            "severity": "critical",
            "action": "prune_expired",
            "message": f"{expired_count} cell(s) past expiry limit. Run: python3 enzymes/cell_expiry.py . --prune",
        })

    noisy_count = len(classifications.get("noisy", []))
    if noisy_count > 0:
        noisy_ids = [c["cell_id"] for c in classifications["noisy"]]
        recommendations.append({
            "severity": "warning",
            "action": "review_noisy",
            "message": f"{noisy_count} noisy cell(s): {', '.join(noisy_ids)}. Consider tightening hypotheses or target_paths.",
        })

    unobserved_count = len(classifications.get("unobserved", []))
    if unobserved_count > 0 and len(cells) > 0:
        pct = unobserved_count / len(cells) * 100
        if pct > 50:
            recommendations.append({
                "severity": "info",
                "action": "collect_evidence",
                "message": f"{unobserved_count}/{len(cells)} cells ({pct:.0f}%) have no fitness evidence. Run post-session hook to collect data.",
            })

    healthy_count = len(classifications.get("healthy", [])) + len(classifications.get("active", []))
    warning_count = len(classifications.get("noisy", [])) + len(classifications.get("decaying", []))
    expired_count = len(classifications.get("expired", []))
    dormant_count = len(classifications.get("unobserved", [])) + len(classifications.get("dormant", []))

    return {
        "workspace": str(ws.root),
        "total_cells": len(cells),
        "healthy_count": healthy_count,
        "warning_count": warning_count,
        "expired_count": expired_count,
        "dormant_count": dormant_count,
        "classifications": dict(classifications),
        "recommendations": recommendations,
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }



def cli_checkpoint(argv: Optional[List[str]] = None) -> int:
    """CLI entrypoint for oracle_checkpoint."""
    import argparse

    parser = argparse.ArgumentParser(description="Oracle Checkpoint — Mid-Session Fitness Feedback")
    parser.add_argument("workspace", nargs="?", default=None, help="Workspace path")
    parser.add_argument("--json", action="store_true", help="Output JSON report")
    parser.add_argument("--session-count", type=int, default=None, help="Current session sequence")

    parsed = parser.parse_args(argv if argv is not None else sys.argv[1:])
    report = generate_checkpoint(workspace=parsed.workspace, session_count=parsed.session_count)

    if parsed.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        ts = report.get("timestamp", datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
        ws_str = report.get("workspace", parsed.workspace or "")
        tot = report.get("total_cells", 0)
        h = report.get("healthy_count", 0)
        w = report.get("warning_count", 0)
        e = report.get("expired_count", 0)
        d = report.get("dormant_count", 0)
        print(f"Soma Oracle Checkpoint ({ts})")
        print(f"Workspace: {ws_str}")
        print(f"Cells: {tot} (Healthy: {h}, Warning: {w}, Expired: {e}, Dormant: {d})")
    has_critical = any(
        r.get("severity") == "critical"
        for r in report.get("recommendations", [])
    )
    return 1 if has_critical else 0


__all__ = [
    "generate_checkpoint",
    "_load_fitness_evidence",
    "_load_cells",
    "_classify_cell",
    "cli_checkpoint",
]

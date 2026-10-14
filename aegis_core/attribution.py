"""Closed-Loop Attribution Correlation Mapping (Phase 22 / v0.119.0).

Connects verification results from DeterministicVerifier (Layer 1) and
AdversarialVerifier / Arbiter (Layer 2) directly to governance cells and
.soma/evidence/signals.jsonl:
- Confirmed defects (Layer 1 tool failure or confirmed divergence) attribute True Positives (TP).
- Spurious or dismissed predictions attribute False Positives (FP).
- Updates cell frontmatter (triggers, true_positives, false_positives, last_trigger_date).
- Appends structured signal records to .soma/evidence/signals.jsonl.

Strictly zero-dependency: uses only Python standard library.
"""
from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from aegis_core.yaml import dump_frontmatter, parse_frontmatter, _get_body
from aegis_core.telemetry import append_signals
from aegis_core.workspace import Workspace, as_workspace
from aegis_core.verification import (
    ArbitrationResult,
    Divergence,
    RiskCategory,
    ToolEvidence,
)


TOOL_TO_CATEGORY: Dict[str, RiskCategory] = {
    "persistence_checker": RiskCategory.PERSISTENCE_GAP,
    "branch_coverage": RiskCategory.DEAD_CODE,
    "mutation_tester": RiskCategory.TAUTOLOGICAL_TEST,
    "call_graph": RiskCategory.MISSING_WIRE,
    "import_guard": RiskCategory.BOUNDARY_VIOLATION,
}


def infer_cell_risk_categories(cell: Dict[str, Any]) -> Set[RiskCategory]:
    """Extract or infer RiskCategory enums for a cell.

    Precedence:
    1. Explicit 'risk_categories' frontmatter list
    2. 'tags' frontmatter entries matching RiskCategory taxonomy
    3. Heuristic matching on cell 'id' / filename
    """
    categories: Set[RiskCategory] = set()

    # 1. Explicit risk_categories
    explicit = cell.get("risk_categories") or []
    if isinstance(explicit, str):
        explicit = [explicit]
    for item in explicit:
        norm = str(item).strip().lower().replace("-", "_")
        for cat in RiskCategory:
            if cat.value == norm or cat.name.lower() == norm:
                categories.add(cat)

    # 2. Tags inference
    tags = cell.get("tags") or []
    if isinstance(tags, str):
        tags = [tags]
    for tag in tags:
        norm = str(tag).strip().lower().replace("-", "_")
        for cat in RiskCategory:
            if cat.value == norm or cat.value in norm:
                categories.add(cat)

    # 3. ID / Name heuristics
    cid = str(cell.get("id") or cell.get("_name") or cell.get("name") or "").lower().replace("-", "_")
    if "import" in cid or "boundary" in cid or "isolation" in cid:
        categories.add(RiskCategory.BOUNDARY_VIOLATION)
    if "persistence" in cid or "serialize" in cid or "cache" in cid:
        categories.add(RiskCategory.PERSISTENCE_GAP)
    if "wire" in cid or "reachab" in cid or "orphan" in cid or "call_graph" in cid:
        categories.add(RiskCategory.MISSING_WIRE)
    if "dead" in cid or "branch" in cid or "coverage" in cid:
        categories.add(RiskCategory.DEAD_CODE)
    if "tautolog" in cid or "mutation" in cid:
        categories.add(RiskCategory.TAUTOLOGICAL_TEST)
    if "traversal" in cid or "path" in cid:
        categories.add(RiskCategory.PATH_TRAVERSAL)
    if "injection" in cid or "eval" in cid or "exec" in cid:
        categories.add(RiskCategory.CODE_INJECTION)
    if "shell" in cid:
        categories.add(RiskCategory.SHELL_INJECTION)
    if "platform" in cid or "windows" in cid or "portab" in cid:
        categories.add(RiskCategory.PLATFORM_INCOMPATIBLE)

    return categories


def _load_workspace_cells(cells_dir: Path) -> List[Dict[str, Any]]:
    """Scan cells_dir and load all cell frontmatter and file paths."""
    cells: List[Dict[str, Any]] = []
    if not cells_dir.is_dir():
        return cells

    for fpath in cells_dir.rglob("*.md"):
        if fpath.name == "README.md":
            continue
        try:
            content = fpath.read_text(encoding="utf-8")
            fm = parse_frontmatter(content) or {}
            fm["_path"] = str(fpath)
            fm["_name"] = fpath.stem
            if "id" not in fm:
                fm["id"] = fpath.stem
            cells.append(fm)
        except Exception:
            continue

    return cells


def _update_cell_fitness_on_disk(
    fpath_str: str,
    attribution: str,
    now_iso: str,
) -> bool:
    """Atomically update cell frontmatter on disk with the attribution event."""
    fpath = Path(fpath_str)
    if not fpath.is_file():
        return False

    try:
        content = fpath.read_text(encoding="utf-8")
        fm = parse_frontmatter(content) or {}
        body = _get_body(content)

        fitness = fm.get("fitness")
        if not isinstance(fitness, dict):
            fitness = {"score": None, "impact_weight": 1.0}

        fitness["triggers"] = int(fitness.get("triggers", 0)) + 1
        fitness.setdefault("true_positives", 0)
        fitness.setdefault("false_positives", 0)

        if attribution == "TP":
            fitness["true_positives"] = int(fitness.get("true_positives", 0)) + 1
        elif attribution == "FP":
            fitness["false_positives"] = int(fitness.get("false_positives", 0)) + 1

        fitness["last_trigger_date"] = now_iso
        fitness["last_verified_date"] = now_iso
        fm["fitness"] = fitness

        new_fm = dump_frontmatter(fm)
        new_content = f"---\n{new_fm.strip()}\n---\n\n{body}\n" if body else f"---\n{new_fm.strip()}\n---\n"

        tmp_path = fpath.with_name(f"{fpath.name}.tmp.{os.getpid()}")
        tmp_path.write_text(new_content, encoding="utf-8")
        tmp_path.replace(fpath)
        return True
    except Exception:
        return False


def attribute_verification_outcome(
    workspace: str | Path | Workspace,
    layer1_evidence: List[ToolEvidence],
    arbitration_result: Optional[ArbitrationResult] = None,
    target_files: Optional[List[str]] = None,
    now: Optional[datetime] = None,
) -> List[Dict[str, Any]]:
    """Attribute Layer 1 and Layer 2 verification outcomes to matching workspace cells.

    Updates cell frontmatter (incrementing true_positives / false_positives and triggers)
    and appends structured signals to .aegis/evidence/signals.jsonl.

    Returns:
        List of generated signal events.
    """
    ws = as_workspace(workspace)
    cells_dir = ws.rules_dir
    cells = _load_workspace_cells(cells_dir)
    if not cells:
        return []

    if now is None:
        now = datetime.now(timezone.utc)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    now_iso = now.strftime("%Y-%m-%dT%H:%M:%SZ")

    signals: List[Dict[str, Any]] = []
    attributed_cell_ids: Set[str] = set()

    # 1. Attribute Layer 1 failures -> True Positives (TP)
    for ev in layer1_evidence:
        if ev.verdict is False:
            cat = TOOL_TO_CATEGORY.get(ev.tool)
            if cat is None:
                continue

            for cell in cells:
                cid = cell["id"]
                cell_cats = infer_cell_risk_categories(cell)
                if cat in cell_cats:
                    sig = {
                        "cell_name": cid,
                        "cell_id": cid,
                        "signal_type": "tp",
                        "source": "session",
                        "principal": "verification_pipeline",
                        "event": "verification_attribution",
                        "attribution": "TP",
                        "risk_category": cat.value,
                        "verdict": "FAIL",
                        "target": ev.target,
                        "evidence_tool": ev.tool,
                        "timestamp": now_iso,
                        "metadata": {
                            "attribution": "TP",
                            "evidence_tool": ev.tool,
                            "target": ev.target,
                        },
                    }
                    signals.append(sig)
                    attributed_cell_ids.add(cid)
                    _update_cell_fitness_on_disk(cell["_path"], "TP", now_iso)

    # 2. Attribute Layer 2 divergences (dismissed/spurious predictions) -> False Positives (FP)
    if arbitration_result is not None:
        for div in arbitration_result.divergences:
            is_dismissed = (
                div.divergence_type in ("dismissed_prediction", "unsupported_prediction")
                or (div.divergence_type == "unmatched_prediction" and (not div.tool_evidence or div.tool_evidence.verdict))
            )
            if is_dismissed:
                cat = div.category
                for cell in cells:
                    cid = cell["id"]
                    if cid in attributed_cell_ids:
                        continue
                    cell_cats = infer_cell_risk_categories(cell)
                    if cat in cell_cats:
                        sig = {
                            "cell_name": cid,
                            "cell_id": cid,
                            "signal_type": "fp",
                            "source": "session",
                            "principal": "verification_pipeline",
                            "event": "verification_attribution",
                            "attribution": "FP",
                            "risk_category": cat.value,
                            "verdict": "PASS",
                            "resolution": div.resolution,
                            "timestamp": now_iso,
                            "metadata": {
                                "attribution": "FP",
                                "resolution": div.resolution,
                            },
                        }
                        signals.append(sig)
                        attributed_cell_ids.add(cid)
                        _update_cell_fitness_on_disk(cell["_path"], "FP", now_iso)

    # 3. Append to .soma/evidence/signals.jsonl
    if signals:
        append_signals(ws, signals)

    return signals


__all__ = [
    "TOOL_TO_CATEGORY",
    "attribute_verification_outcome",
    "infer_cell_risk_categories",
]

"""Promotion, demotion, tier evaluation, adaptation, and metamorphosis."""
from __future__ import annotations

from datetime import datetime, timezone
import glob
import os
from pathlib import Path
from typing import Any, Dict, Optional

from aegis_core.yaml import dump_frontmatter, parse_frontmatter
from aegis_core.locking import workspace_lock
from aegis_core.storage import atomic_write_and_unlink as _atomic_write_and_unlink, atomic_write_text
from aegis_core.workspace import Workspace
from aegis_core.workspace.layout import LockResource
from .constants import (
    DORMANT_DAYS_THRESHOLD,
    MAX_FP_RATE_FOR_DEMOTION,
    MIN_AGE_DAYS_FOR_PROMOTION,
    MIN_TP_RATE_FOR_PROMOTION,
    MIN_TRIGGERS_FOR_PROMOTION,
    MODERN_DEMOTION_PATH,
    MODERN_GLOBAL_PROMOTION_PATH,
    MODERN_LOCAL_PROMOTION_PATH,
    PROTECTED_RULES,
    TYPE_TO_DIR,
    get_demotion_path,
    get_promotion_path,
)
from .decay import (
    apply_decay,
    normalize_fitness,
)
from .parsers import (
    _cell_age_days,
    _load_cells,
    _load_evidence,
    _transform_frontmatter_type,
    find_cell_file,
    sanitize_cell_id,
)
from .quorum import is_promotable

__all__ = [
    "demote_cell",
    "evaluate_cell_tiers",
    "evaluate_demotions",
    "evaluate_promotions",
    "promote_cell",
]


def _effective_promotion_path(ws: Workspace) -> dict[str, str]:
    modern = MODERN_GLOBAL_PROMOTION_PATH if getattr(ws, "is_aegis_repo", False) else MODERN_LOCAL_PROMOTION_PATH
    return {**modern, **get_promotion_path(ws)}


def _effective_demotion_path(ws: Workspace) -> dict[str, str]:
    return {**MODERN_DEMOTION_PATH, **get_demotion_path(ws)}


def evaluate_promotions(workspace: Workspace | Path | str) -> list[dict]:
    """Evaluate cells for promotion based on canonical signal evidence.

    Returns:
        List of promotion candidate dicts:
        [{cell_id, from_type, to_type, triggers, tp_rate, age_days}]
    """
    ws = workspace if isinstance(workspace, Workspace) else (
        Workspace(root=Path(workspace).resolve()) if workspace else Workspace.resolve()
    )
    promotion_path = _effective_promotion_path(ws)
    evidence = _load_evidence(ws)
    cells = _load_cells(ws)
    candidates = []

    for cell in cells:
        cell_id = cell["id"]
        cell_type = cell["type"]

        if cell_type not in promotion_path:
            continue

        ev = evidence.get(cell_id, {
            "triggers": 0, "tp": 0, "fp": 0,
            "last_trigger_ts": None, "has_triggers": True,
        })
        triggers = ev["triggers"]
        tp = ev["tp"]
        age_days = _cell_age_days(cell)

        if triggers < MIN_TRIGGERS_FOR_PROMOTION:
            continue
        tp_rate = tp / triggers if triggers > 0 else 0.0
        if tp_rate < MIN_TP_RATE_FOR_PROMOTION:
            continue
        if age_days < MIN_AGE_DAYS_FOR_PROMOTION:
            continue

        candidates.append({
            "cell_id": cell_id,
            "rule_id": cell_id,
            "from_type": cell_type,
            "to_type": promotion_path[cell_type],
            "triggers": triggers,
            "tp_rate": round(tp_rate, 4),
            "age_days": age_days,
        })

    return candidates


def evaluate_demotions(workspace: Workspace | Path | str) -> list[dict]:
    """Evaluate cells for demotion based on canonical signal evidence.

    Returns:
        List of demotion candidate dicts:
        [{cell_id, from_type, to_type, reason, fp_rate, triggers}]
    """
    ws = workspace if isinstance(workspace, Workspace) else (
        Workspace(root=Path(workspace).resolve()) if workspace else Workspace.resolve()
    )
    demotion_path = _effective_demotion_path(ws)
    evidence = _load_evidence(ws)
    cells = _load_cells(ws)
    candidates = []

    for cell in cells:
        cell_id = cell["id"]
        cell_type = cell["type"]

        if cell_type not in demotion_path:
            continue

        clean_id = cell_id[:-3] if cell_id.endswith(".md") else cell_id
        if clean_id.startswith("rule-"):
            clean_id = clean_id[5:]
        if clean_id in PROTECTED_RULES or cell_id in PROTECTED_RULES:
            continue

        ev = evidence.get(cell_id, {
            "triggers": 0, "tp": 0, "fp": 0,
            "last_trigger_ts": None, "has_triggers": True,
        })
        triggers = ev["triggers"]
        tp = ev["tp"]
        fp = ev["fp"]
        age_days = _cell_age_days(cell)

        reason = None

        if triggers >= 5:
            fp_rate = fp / triggers
            if fp_rate > MAX_FP_RATE_FOR_DEMOTION:
                reason = "high_fp_rate"
        else:
            fp_rate = 0.0

        last_trigger_ts = ev.get("last_trigger_ts")
        if last_trigger_ts is not None:
            last_trigger_age = (datetime.now(timezone.utc).replace(tzinfo=None) - last_trigger_ts).days
        else:
            last_trigger_age = (
                age_days
                if triggers == 0 and ev.get("has_triggers", True)
                else 0
            )

        if reason is None and last_trigger_age >= DORMANT_DAYS_THRESHOLD:
            reason = "dormant"

        if reason is None:
            continue

        candidates.append({
            "cell_id": cell_id,
            "rule_id": cell_id,
            "from_type": cell_type,
            "to_type": demotion_path[cell_type],
            "reason": reason,
            "fp_rate": round(fp_rate, 4) if triggers > 0 else 0.0,
            "triggers": triggers,
            "age_days": age_days,
        })

    return candidates


def _recheck_move_locked(cell_id: str, cell_path: Path, target_path: Path) -> Optional[Dict[str, Any]]:
    """Repeat the unlocked pre-move checks once the rules lock is held.

    A create into the target tier, or another promote/demote of the same rule,
    can land between the first checks and the lock: moving anyway would
    overwrite the rival rule or read a source that is already gone.
    """
    if not cell_path.is_file():
        return {
            "status": "not_found",
            "message": f"Cell '{cell_id}' was moved or removed before the rules lock was acquired",
        }
    if target_path != cell_path and target_path.exists():
        return {
            "status": "target_exists",
            "message": f"Target already exists: {target_path}",
        }
    return None


def promote_cell(
    workspace: Workspace | Path | str,
    cell_id: str,
    force: bool = False,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Execute structural promotion for a rule (trap -> invariant -> genome)."""
    ws = workspace if isinstance(workspace, Workspace) else (
        Workspace(root=Path(workspace).resolve()) if workspace else Workspace.resolve()
    )
    cell_path, current_type = find_cell_file(ws, cell_id)
    if cell_path is None or current_type is None:
        return {
            "status": "not_found",
            "message": f"Cell '{cell_id}' not found in workspace",
        }

    promotion_path = _effective_promotion_path(ws)
    next_type = promotion_path.get(current_type)
    if next_type is None:
        return {
            "status": "already_terminal",
            "current_type": current_type,
            "message": f"Cell '{cell_id}' is already at terminal level ('{current_type}')",
        }

    if not force:
        try:
            metadata = parse_frontmatter(cell_path.read_text(encoding="utf-8")) or {}
        except Exception as exc:
            return {"status": "error", "message": f"Failed to parse cell frontmatter: {exc}"}

        fitness = metadata.get("fitness") or {}
        tp = int(fitness.get("true_positives", 0))
        triggers = int(fitness.get("triggers", 0))
        if not is_promotable(tp, triggers):
            return {
                "status": "ineligible",
                "current_type": current_type,
                "triggers": triggers,
                "tp": tp,
                "message": f"Cell '{cell_id}' does not meet promotion threshold (>0.85 with >=20 triggers)",
            }

    clean_id = sanitize_cell_id(cell_id) or cell_path.stem
    rule_base = clean_id[:-3] if clean_id.endswith(".md") else clean_id
    if rule_base.startswith("rule-"):
        rule_base = rule_base[5:]
    if clean_id in PROTECTED_RULES or rule_base in PROTECTED_RULES:
        return {
            "status": "protected_rule_immutable",
            "message": f"Cannot promote cell into protected core rule namespace: '{cell_id}'",
        }

    if next_type == "genome":
        if not ws.is_aegis_repo:
            return {
                "status": "error",
                "message": "Cannot promote to genome in non-soma repository",
            }
        target_dir = (ws.root / "rules") if (ws.root / "rules").is_dir() else (ws.root / "genome")
    else:
        target_dir = ws.rules_dir / TYPE_TO_DIR[next_type]

    target_path = target_dir / f"{clean_id}.md"
    if target_path.exists():
        return {
            "status": "target_exists",
            "message": f"Target already exists: {target_path}",
        }

    if dry_run:
        return {
            "status": "dry_run",
            "from_type": current_type,
            "to_type": next_type,
            "source_path": str(cell_path),
            "target_path": str(target_path),
        }

    target_dir.mkdir(parents=True, exist_ok=True)
    with workspace_lock(ws.root, LockResource.RULES):
        conflict = _recheck_move_locked(cell_id, cell_path, target_path)
        if conflict is not None:
            return conflict
        content = cell_path.read_text(encoding="utf-8")
        new_content = _transform_frontmatter_type(content, next_type)
        _atomic_write_and_unlink(cell_path, target_path, new_content)

    return {
        "status": "promoted",
        "from_type": current_type,
        "to_type": next_type,
        "source_path": str(cell_path),
        "target_path": str(target_path),
    }


def demote_cell(
    workspace: Workspace | Path | str,
    cell_id: str,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Execute structural demotion for a rule (invariant -> trap)."""
    clean_id = sanitize_cell_id(cell_id)
    if not clean_id:
        return {"status": "invalid_id", "message": f"Invalid cell ID: '{cell_id}'"}

    rule_base = clean_id
    if rule_base.startswith("rule-"):
        rule_base = rule_base[5:]

    if clean_id in PROTECTED_RULES or rule_base in PROTECTED_RULES:
        raise ValueError(f"Cannot demote protected core rule: '{cell_id}'")

    ws = workspace if isinstance(workspace, Workspace) else (
        Workspace(root=Path(workspace).resolve()) if workspace else Workspace.resolve()
    )
    cell_path, current_type = find_cell_file(ws, clean_id)
    if cell_path is None or current_type is None:
        return {
            "status": "not_found",
            "message": f"Cell '{clean_id}' not found in workspace",
        }

    demotion_path = _effective_demotion_path(ws)
    next_type = demotion_path.get(current_type)
    if next_type is None:
        return {
            "status": "already_base",
            "current_type": current_type,
            "message": f"Cell '{clean_id}' is at base level ('{current_type}') and cannot be demoted further",
        }

    target_dir = ws.rules_dir / TYPE_TO_DIR[next_type]
    target_path = target_dir / f"{clean_id}.md"
    if target_path.exists():
        return {
            "status": "target_exists",
            "message": f"Target already exists: {target_path}",
        }

    if dry_run:
        return {
            "status": "dry_run",
            "from_type": current_type,
            "to_type": next_type,
            "source_path": str(cell_path),
            "target_path": str(target_path),
        }

    target_dir.mkdir(parents=True, exist_ok=True)
    with workspace_lock(ws.root, LockResource.RULES):
        conflict = _recheck_move_locked(clean_id, cell_path, target_path)
        if conflict is not None:
            return conflict
        content = cell_path.read_text(encoding="utf-8")
        new_content = _transform_frontmatter_type(content, next_type)
        _atomic_write_and_unlink(cell_path, target_path, new_content)

    return {
        "status": "demoted",
        "from_type": current_type,
        "to_type": next_type,
        "source_path": str(cell_path),
        "target_path": str(target_path),
    }


def _read_rule_text(file_path: str) -> Optional[str]:
    try:
        with open(file_path, "r", encoding="utf-8-sig") as f:
            return f.read()
    except Exception:
        return None


def _plan_tier_update(content: str) -> Optional[tuple[dict, str, str, str, str]]:
    """Decay a rule's fitness and pick its enforcement tier.

    Returns ``(metadata, body, old_tier, new_tier, reason)`` with ``metadata``
    already carrying the decay and the new tier, or None if unparseable.
    """
    from aegis_core.yaml import parse_rule_frontmatter
    try:
        metadata, body = parse_rule_frontmatter(content)
    except Exception:
        return None

    enforcement = metadata.get("enforcement", "advisory")
    metadata["fitness"] = normalize_fitness(metadata)
    apply_decay(metadata)
    fitness = metadata["fitness"]

    triggers = fitness.get("triggers", 0)
    fp = fitness.get("false_positives", 0)

    fp_rate = fp / triggers if triggers > 0 else 0.0
    trigger_rate = triggers / 30.0

    new_tier = enforcement
    reason = ""

    if enforcement == "advisory":
        if triggers >= 20 and fp_rate < 0.15:
            new_tier = "mechanical"
            reason = "triggers >= 20, FP rate < 0.15"
    elif enforcement == "mechanical":
        if triggers >= 50 and fp_rate < 0.05:
            new_tier = "gate"
            reason = "triggers >= 50, FP rate < 0.05"
        elif fp_rate > 0.50 or trigger_rate < (1 / 30.0):
            new_tier = "advisory"
            reason = "FP rate > 0.50 or low trigger rate"
    elif enforcement == "gate":
        if fp_rate > 0.30:
            new_tier = "mechanical"
            reason = "FP rate > 0.30"

    if new_tier != enforcement:
        metadata["enforcement"] = new_tier
    return metadata, body, enforcement, new_tier, reason


def evaluate_cell_tiers(workspace: Workspace | Path | str | None = None, execute: bool = False) -> Dict[str, Any]:
    """Evaluate and update cell enforcement tiers (advisory/mechanical/gate) with exponential decay."""
    ws = workspace if isinstance(workspace, Workspace) else (
        Workspace(root=Path(workspace).resolve()) if workspace else Workspace.resolve()
    )
    cells_dir = ws.rules_dir
    cell_files = glob.glob(os.path.join(str(cells_dir), "**", "*.md"), recursive=True)
    changes: list[dict[str, Any]] = []
    evaluated = 0

    for file_path in cell_files:
        if os.path.basename(file_path) == "README.md":
            continue
        content = _read_rule_text(file_path)
        if content is None:
            continue
        cell_name = os.path.basename(file_path)
        plan = _plan_tier_update(content)
        if plan is None:
            continue

        if execute and dump_frontmatter(plan[0], body=plan[1]) != content:
            # Read unlocked, rewrite under the lock, one rule at a time: a pass
            # over hundreds of rules must not starve concurrent writers into
            # LockTimeoutError. Re-plan from the bytes on disk under the lock so
            # a concurrent edit is not clobbered and a rule promoted or demoted
            # meanwhile is not resurrected at its old path.
            with workspace_lock(ws.root, LockResource.RULES):
                current = _read_rule_text(file_path)
                if current is None:
                    continue
                if current != content:
                    plan = _plan_tier_update(current)
                    if plan is None:
                        continue
                metadata, body = plan[0], plan[1]
                new_content = dump_frontmatter(metadata, body=body)
                if new_content != current:
                    atomic_write_text(file_path, new_content)

        evaluated += 1
        _metadata, _body, old_tier, new_tier, reason = plan
        if new_tier != old_tier:
            changes.append({
                "cell": cell_name,
                "old_tier": old_tier,
                "new_tier": new_tier,
                "reason": reason,
            })

    return {"evaluated": evaluated, "changes": changes}



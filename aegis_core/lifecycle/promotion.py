"""Promotion, demotion, tier evaluation, adaptation, and metamorphosis."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import glob
import json
import os
from pathlib import Path
import sys
from typing import Any, Dict, Optional

from aegis_core.yaml import dump_frontmatter, parse_frontmatter
from aegis_core.locking import workspace_lock
from aegis_core.workspace import Workspace, resolve_workspace
from .constants import (
    DEMOTION_PATH,
    DORMANT_DAYS_THRESHOLD,
    MAX_FP_RATE_FOR_DEMOTION,
    METAMORPHOSIS_PATHS,
    MIN_AGE_DAYS_FOR_PROMOTION,
    MIN_TP_RATE_FOR_PROMOTION,
    MIN_TRIGGERS_FOR_PROMOTION,
    MODERN_DEMOTION_PATH,
    MODERN_GLOBAL_PROMOTION_PATH,
    MODERN_LOCAL_PROMOTION_PATH,
    PROMOTION_PATH,
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
    _atomic_write_and_unlink,
    _cell_age_days,
    _load_cells,
    _load_evidence,
    _transform_frontmatter_type,
    find_cell_file,
    sanitize_cell_id,
)
from .quorum import is_promotable

__all__ = [
    "adapt_cell",
    "cli_cell_promote",
    "demote_cell",
    "evaluate_cell_tiers",
    "evaluate_demotions",
    "evaluate_promotions",
    "metamorphose_cell",
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
    with workspace_lock(ws.root, "cells"):
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
    with workspace_lock(ws.root, "cells"):
        content = cell_path.read_text(encoding="utf-8")
        new_content = _transform_frontmatter_type(content, next_type)
        _atomic_write_and_unlink(cell_path, target_path, new_content)

        if current_type in ("wall", "invariant") and next_type == "trap":
            for pfx in ("check-", "gate-"):
                for sfx in (".sh", ".py"):
                    art = ws.aegis_dir / "enforcement" / f"{pfx}{clean_id}{sfx}"
                    if art.exists():
                        try:
                            art.unlink()
                        except Exception:
                            pass

    return {
        "status": "demoted",
        "from_type": current_type,
        "to_type": next_type,
        "source_path": str(cell_path),
        "target_path": str(target_path),
    }


def evaluate_cell_tiers(workspace: Workspace | Path | str | None = None, execute: bool = False) -> Dict[str, Any]:
    """Evaluate and update cell enforcement tiers (advisory/mechanical/gate) with exponential decay."""
    ws = workspace if isinstance(workspace, Workspace) else (
        Workspace(root=Path(workspace).resolve()) if workspace else Workspace.resolve()
    )
    cells_dir = ws.rules_dir
    cell_files = glob.glob(os.path.join(str(cells_dir), "**", "*.md"), recursive=True)
    escaped_defects_log = str(ws.metrics_dir / "escaped_defects.jsonl")

    escaped_counts: Dict[str, int] = {}
    if os.path.exists(escaped_defects_log):
        with open(escaped_defects_log, encoding="utf-8") as edf:
            for line in edf:
                try:
                    entry = json.loads(line.strip())
                    cname = entry.get("cell")
                    if cname:
                        escaped_counts[cname] = escaped_counts.get(cname, 0) + 1
                except Exception:
                    continue

    changes: list[dict[str, Any]] = []
    evaluated = 0

    for file_path in cell_files:
        if os.path.basename(file_path) == "README.md":
            continue
        try:
            with open(file_path, "r", encoding="utf-8-sig") as f:
                content = f.read()
        except Exception:
            continue
        from aegis_core.yaml import _get_body, parse_rule_frontmatter
        try:
            metadata, body = parse_rule_frontmatter(content)
        except Exception:
            continue

        cell_name = os.path.basename(file_path)
        cell_base = os.path.splitext(cell_name)[0]

        enforcement = metadata.get("enforcement", "advisory")
        fitness = normalize_fitness(metadata)

        metadata["fitness"] = fitness
        apply_decay(metadata)
        fitness = metadata["fitness"]

        triggers = fitness.get("triggers", 0)
        tp = fitness.get("true_positives", 0)
        fp = fitness.get("false_positives", 0)

        escaped = escaped_counts.get(cell_base, 0)
        total_cases = escaped + tp
        defect_prevention_rate = tp / total_cases if total_cases > 0 else 1.0

        fp_rate = fp / triggers if triggers > 0 else 0.0
        trigger_rate = triggers / 30.0

        new_tier = enforcement
        reason = ""

        if enforcement == "advisory":
            if defect_prevention_rate > 0.85 and triggers >= 20 and fp_rate < 0.15:
                new_tier = "mechanical"
                reason = "defect_prevention_rate > 0.85, triggers >= 20, FP rate < 0.15"
        elif enforcement == "mechanical":
            if defect_prevention_rate > 0.95 and triggers >= 50 and fp_rate < 0.05:
                new_tier = "gate"
                reason = "defect_prevention_rate > 0.95, triggers >= 50, FP rate < 0.05"
            elif fp_rate > 0.50 or trigger_rate < (1 / 30.0):
                new_tier = "advisory"
                reason = "FP rate > 0.50 or low trigger rate"
        elif enforcement == "gate":
            if fp_rate > 0.30 or escaped > 0:
                new_tier = "mechanical"
                reason = "FP rate > 0.30 or escaped defects spike"

        evaluated += 1

        if new_tier != enforcement:
            changes.append({
                "cell": cell_name,
                "old_tier": enforcement,
                "new_tier": new_tier,
                "reason": reason,
            })
            metadata["enforcement"] = new_tier

        if execute:
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(dump_frontmatter(metadata, body=body))

            if new_tier in ("mechanical", "gate") and new_tier != enforcement:
                try:
                    from aegis_core.enforcement import (
                        generate_gate_assertion,
                        generate_precommit_check,
                        update_cell_enforcement_artifact,
                    )
                    artifacts_dir = str(ws.aegis_dir / "enforcement")
                    os.makedirs(artifacts_dir, exist_ok=True)
                    if new_tier == "mechanical":
                        artifact_content = generate_precommit_check(metadata, str(ws.root))
                        artifact_name = f"check-{cell_base}.sh"
                    else:
                        artifact_content = generate_gate_assertion(metadata, str(ws.root))
                        artifact_name = f"gate-{cell_base}.py"
                    artifact_path = os.path.join(artifacts_dir, artifact_name)
                    with open(artifact_path, "w", encoding="utf-8") as af:
                        af.write(artifact_content)
                    os.chmod(artifact_path, 0o755)
                    metadata["_path"] = file_path
                    update_cell_enforcement_artifact(metadata, artifact_path, str(ws.root))
                except Exception:
                    pass

    return {"evaluated": evaluated, "changes": changes}


def cli_cell_promote(argv: list[str] | None = None, workspace: Optional[str] = None) -> int:
    """CLI wrapper for cell promotion and tier evaluation."""
    parser = argparse.ArgumentParser(description="Promote cells to global rules.")
    parser.add_argument("--local", action="store_true", help="Single-repo mode")
    parser.add_argument("--execute", action="store_true", help="Create rule file / apply tier updates")
    parser.add_argument("--tier-check", action="store_true", help="Check cells for enforcement tier promotion/demotion")
    parser.add_argument("--enforce", action="store_true", help="Alias for --tier-check")
    parser.add_argument("--dry-run", action="store_true", help="Dry run")
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])

    ws = str(workspace or resolve_workspace())
    execute = bool(args.execute and not args.dry_run)
    res = evaluate_cell_tiers(ws, execute=execute)
    for change in res.get("changes", []):
        print(f"Tier update {change['cell']}: {change['old_tier']} -> {change['new_tier']} ({change['reason']})")
    return 0


def metamorphose_cell(workspace: Workspace | Path | str, cell_id: str | Path) -> dict:
    """Transforms cell between types based on maturity criteria."""
    ws = workspace if isinstance(workspace, Workspace) else (
        Workspace(root=Path(workspace).resolve()) if workspace else Workspace.resolve()
    )
    cells_dir = ws.rules_dir
    clean_id = cell_id.stem if isinstance(cell_id, Path) else str(cell_id)
    if clean_id.endswith(".md"):
        clean_id = clean_id[:-3]
    matches = list(cells_dir.rglob(f"*{clean_id}*.md"))
    if not matches:
        return {"status": "not_found", "message": f"Cell '{cell_id}' not found"}

    cell_path = matches[0]
    content = cell_path.read_text(encoding="utf-8")
    meta = parse_frontmatter(content) or {}
    current_type = meta.get("type")
    if not current_type or current_type not in METAMORPHOSIS_PATHS:
        return {"status": "no_paths", "type": current_type}

    fitness = meta.get("fitness") or {}
    triggers = fitness.get("triggers", 0)
    tp = fitness.get("true_positives", 0)
    score = fitness.get("score") or (tp / triggers if triggers > 0 else 0)

    best_path = None
    for p in METAMORPHOSIS_PATHS[current_type]:
        if score >= p["min_fitness"] and triggers >= p["min_sessions"]:
            best_path = p
            break

    if not best_path:
        return {"status": "not_mature", "score": score, "triggers": triggers}

    new_type = best_path["target"]
    meta["type"] = new_type
    meta["metamorphosed_from"] = current_type
    meta["metamorphosis_date"] = datetime.now(timezone.utc).isoformat() + "Z"

    if new_type == "rule":
        if ws.is_aegis_repo:
            target_dir = (ws.root / "rules") if (ws.root / "rules").is_dir() else (ws.root / "genome")
            target_path = target_dir / f"rule-{cell_path.name}"
        else:
            target_dir = cells_dir / "gates"
            target_path = target_dir / cell_path.name
            new_type = "gate"
            meta["type"] = "gate"
    else:
        target_dir = cells_dir / f"{new_type}s"
        target_path = target_dir / cell_path.name

    target_dir.mkdir(parents=True, exist_ok=True)
    from aegis_core.yaml import _get_body
    nfm = dump_frontmatter(meta)
    body = _get_body(content).lstrip()
    target_path.write_text(f"---\n{nfm.strip()}\n---\n\n{body}\n" if body else f"---\n{nfm.strip()}\n---\n", encoding="utf-8")
    cell_path.unlink()

    return {
        "status": "metamorphosed",
        "cell": cell_path.name,
        "from_type": current_type,
        "to_type": new_type,
        "fitness_score": score,
        "triggers": triggers,
    }


def adapt_cell(workspace: Workspace | Path | str, generate: bool = False) -> list[dict]:
    """Scan and adapt cells with middling fitness scores."""
    ws = workspace if isinstance(workspace, Workspace) else (
        Workspace(root=Path(workspace).resolve()) if workspace else Workspace.resolve()
    )
    cells_dir = ws.rules_dir
    results = []

    for fpath in cells_dir.rglob("*.md"):
        if fpath.name == "README.md":
            continue
        try:
            content = fpath.read_text(encoding="utf-8")
            meta = parse_frontmatter(content) or {}
        except Exception:
            continue

        fitness = meta.get("fitness") or {}
        triggers = fitness.get("triggers", 0)
        tp = fitness.get("true_positives", 0)
        fp = fitness.get("false_positives", 0)
        impact = meta.get("impact_weight", 1.0)
        if triggers == 0:
            continue
        score = (tp / triggers) * impact

        if 0.3 <= score <= 0.7:
            suggestion = "narrowing the hypothesis scope" if fp > tp * 1.5 else (
                "broadening the trigger conditions" if triggers < 5 else "splitting into two more specific cells"
            )
            item = {
                "cell": fpath.name,
                "score": score,
                "tp": tp,
                "fp": fp,
                "suggestion": suggestion,
            }
            results.append(item)

            if generate:
                from aegis_core.yaml import _get_body
                v2_name = f"{fpath.stem}_v2.md"
                v2_path = fpath.parent / v2_name
                meta_v2 = dict(meta)
                meta_v2["hypothesis"] = meta_v2.get("hypothesis", "") + " (Refined)"
                meta_v2["fitness"] = {"triggers": 0, "true_positives": 0, "false_positives": 0, "score": None}
                meta_v2["lineage"] = [fpath.name]
                meta_v2["created"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                nfm = dump_frontmatter(meta_v2)
                body = _get_body(content).lstrip()
                v2_path.write_text(f"---\n{nfm.strip()}\n---\n\n{body}\n" if body else f"---\n{nfm.strip()}\n---\n", encoding="utf-8")
                item["generated"] = str(v2_path)

    return results

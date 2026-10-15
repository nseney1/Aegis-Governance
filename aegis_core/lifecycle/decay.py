"""Fitness scoring, Bayesian calculation, and exponential decay."""
from __future__ import annotations

from datetime import datetime, timezone
import glob
import os
from pathlib import Path
import time
from typing import Any, Optional

from aegis_core.yaml import parse_frontmatter
from aegis_core.scoring import bayesian_posterior, bayesian_score, calculate_snr
from aegis_core.taxonomy import RULE_EXPIRY_DAYS
from aegis_core.workspace import Workspace
from .constants import (
    CELL_TELOMERE_DAYS,
    DECAY_FACTOR,
)
from .quorum import calculate_fitness_status

__all__ = [
    "CELL_TELOMERE_DAYS",
    "RULE_EXPIRY_DAYS",
    "apply_decay",
    "bayesian_fitness",
    "compute_cells_fitness",
    "decayed_fitness",
    "normalize_fitness",
    "antifragile_bonus",
]


def apply_decay(meta: dict) -> dict:
    """Decay historical fitness data so recent signals weigh more.

    Prevents Beta-locking: a cell with 1000 historical TPs can still
    be demoted if it starts producing false positives consistently.
    Effective memory window: ~20 sessions (0.95^20 ≈ 0.36).

    Idempotency: skips decay if last_decay_epoch is within 1 hour.
    Mutates meta in place and returns it.
    """
    fitness = (meta or {}).get("fitness", {})
    if not isinstance(fitness, dict):
        return meta

    now = int(time.time())
    last_decay = fitness.get("last_decay_epoch", 0)
    if now - last_decay < 3600:
        return meta

    triggers = fitness.get("triggers", 0)
    tp = fitness.get("true_positives", 0)
    fp = fitness.get("false_positives", 0)

    if triggers <= 0:
        fitness["last_decay_epoch"] = now
        meta["fitness"] = fitness
        return meta

    fitness["triggers"] = max(1, int(triggers * DECAY_FACTOR))
    fitness["true_positives"] = max(0, int(tp * DECAY_FACTOR))
    fitness["false_positives"] = max(0, int(fp * DECAY_FACTOR))

    new_tp = fitness["true_positives"]
    new_triggers = fitness["triggers"]
    fitness["score"] = round(bayesian_score(new_tp, new_triggers), 4)

    fitness["last_decay_epoch"] = now
    meta["fitness"] = fitness
    return meta


def normalize_fitness(metadata: dict) -> dict:
    """Normalize fitness dictionary in cell metadata."""
    fitness = metadata.get("fitness", {})
    if isinstance(fitness, (int, float)):
        return {"score": float(fitness), "impact_weight": 1.0}
    if isinstance(fitness, str):
        try:
            return {"score": float(fitness), "impact_weight": 1.0}
        except ValueError:
            return {"score": None, "impact_weight": 1.0}
    if not isinstance(fitness, dict):
        return {"score": None, "impact_weight": 1.0}
    return fitness


def bayesian_fitness(tp: int, fp: int, confidence: float = 0.90) -> dict:
    """Wilson-bounded posterior with Jeffrey's prior."""
    return bayesian_posterior(tp=tp, fp=fp, confidence=confidence)


def antifragile_bonus(metadata: dict) -> float:
    """Cells gain +5% fitness per survived high-intensity review."""
    stress_events = metadata.get("fitness", {}).get("stress_survived", 0)
    return 1.0 + (0.05 * min(stress_events, 10))


def decayed_fitness(raw_score: Optional[float], last_trigger_date: Any, telomere_days: float = 30) -> Optional[float]:
    if last_trigger_date is None or raw_score is None:
        return raw_score
    try:
        t_days = float(telomere_days)
    except (TypeError, ValueError):
        t_days = 30.0
    if t_days <= 0:
        return raw_score
    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    trigger_utc = last_trigger_date.replace(tzinfo=None) if getattr(last_trigger_date, "tzinfo", None) else last_trigger_date
    days_since = max(0, (now_utc - trigger_utc).days)
    decay_factor = 0.5 ** (days_since / t_days)
    return round(raw_score * decay_factor, 4)


def compute_cells_fitness(
    workspace: Optional[Workspace | str | Path] = None,
    bayesian: bool = False,
    prune: bool = False,
    promote: bool = False,
) -> list[dict]:
    """Compute fitness of immune cells in workspace."""
    ws = workspace if isinstance(workspace, Workspace) else (
        Workspace(root=Path(workspace).resolve()) if workspace else Workspace.resolve()
    )

    total_sessions = 30
    conf_path = ws.root / "aegis.conf"
    if conf_path.is_file():
        try:
            with open(conf_path, encoding="utf-8") as f:
                for line in f:
                    if line.startswith("TOTAL_SESSIONS="):
                        total_sessions = int(line.strip().split("=", 1)[1])
        except Exception:
            pass

    cells_dir = ws.rules_dir
    cell_files = glob.glob(os.path.join(str(cells_dir), "**", "*.md"), recursive=True)
    results = []

    for file_path in cell_files:
        if os.path.basename(file_path) == "README.md":
            continue
        try:
            with open(file_path, "r", encoding="utf-8") as fh:
                metadata = parse_frontmatter(fh.read()) or {}
        except Exception:
            continue

        cell_name = os.path.basename(file_path)
        cell_type = metadata.get("type", "unknown")
        fitness = metadata.get("fitness", {})
        if isinstance(fitness, (int, float)):
            fitness = {"score": float(fitness)}
            metadata["fitness"] = fitness

        triggers = fitness.get("triggers", 0)
        tp = fitness.get("true_positives", 0)
        fp = fitness.get("false_positives", 0)
        impact_weight = metadata.get("impact_weight", 1.0)

        if triggers == 0:
            score = bayesian_score(0, 0, impact_weight)
            snr_db = 0.0
            is_unobserved = True
        else:
            score = bayesian_score(tp, triggers, impact_weight)
            is_unobserved = False
            trigger_rate = triggers / max(total_sessions, 1)
            specificity_penalty = 1.0 - min(trigger_rate, 1.0)
            if trigger_rate > 0.8:
                score = score * specificity_penalty
            score = score * antifragile_bonus(metadata)

            snr_db = calculate_snr(tp, fp)

        last_trigger_date_str = fitness.get("last_trigger_date")
        last_trigger_date = None
        if last_trigger_date_str:
            try:
                last_trigger_date = datetime.fromisoformat(last_trigger_date_str.replace("Z", "+00:00")).replace(tzinfo=None)
            except Exception:
                pass

        hl_val = (
            os.environ.get(f"RULE_EXPIRY_{cell_type.upper()}")
            or os.environ.get(f"CELL_TELOMERE_{cell_type.upper()}")
            or os.environ.get("RULE_EXPIRY_DAYS")
            or os.environ.get("CELL_TELOMERE_DAYS", "30")
        )
        if hl_val == "null":
            dec_score = score
        else:
            telomere_days = int(hl_val)
            dec_score = decayed_fitness(score, last_trigger_date, telomere_days)

        expiry_days = metadata.get("expiry_days")
        created_str = metadata.get("created")
        status = calculate_fitness_status(cell_type, tp, fp, triggers, dec_score, is_unobserved, created_str, expiry_days)

        enforcement = metadata.get("enforcement", "advisory")
        tier_weights = {"advisory": 1.0, "mechanical": 1.2, "gate": 1.5}
        tier_weight = tier_weights.get(enforcement, 1.0)
        enhanced_score = round(score * tier_weight, 4) if score is not None else None

        res = {
            "cell": cell_name,
            "type": cell_type,
            "hypothesis": metadata.get("hypothesis", ""),
            "triggers": triggers,
            "tp": tp,
            "fp": fp,
            "score": score,
            "decayed_score": dec_score,
            "status": status,
            "snr_db": snr_db,
            "enforcement": enforcement,
            "enhanced_fitness": enhanced_score,
        }
        if bayesian:
            res["bayesian"] = bayesian_fitness(tp, fp)
        results.append(res)

    if prune:
        results = [r for r in results if r["status"] in ("EXTINCT", "DORMANT")]
    elif promote:
        results = [r for r in results if r["score"] is not None and r["score"] > 0.7 and r.get("triggers", 0) > 0]

    return results

"""Unified scoring module for soma-governance (Layer 0 Core).

Single source of truth for all fitness scoring math, Wilson intervals,
Laplace smoothing, and Bayesian posteriors.
Strictly zero-dependency: uses only Python standard library.
"""
from __future__ import annotations

import math
from typing import Any, Dict, Optional, Tuple, Union


def _wilson_interval(tp: int | float, total: int | float, z: float = 1.645) -> Tuple[float, float]:
    """Wilson score interval — correct for small n, no scipy needed.

    Args:
        tp: Number of successes (true positives).
        total: Total number of observations (tp + fp).
        z: Z-score for confidence level (1.645=90%, 1.96=95%, 2.576=99%).

    Returns:
        Tuple of (lower_bound, upper_bound).
    """
    total_num = max(0.0, _to_num(total))
    if total_num == 0.0:
        return 0.0, 1.0
    tp_num = max(0.0, min(_to_num(tp), total_num))
    p = tp_num / total_num
    denom = 1 + z ** 2 / total_num
    center = (p + z ** 2 / (2 * total_num)) / denom
    inside = (p * (1 - p) + z ** 2 / (4 * total_num)) / total_num
    spread = z * math.sqrt(max(0.0, inside)) / denom
    return max(0.0, center - spread), min(1.0, center + spread)


def _to_num(val: Any, default: float = 0.0) -> float:
    """Robustly convert arbitrary input to a finite non-negative float."""
    if val is None or isinstance(val, bool):
        return default
    if isinstance(val, (int, float)):
        return max(0.0, float(val)) if math.isfinite(val) else default
    if isinstance(val, str):
        val = val.strip()
        if '/' in val:
            try:
                from fractions import Fraction
                f = float(Fraction(val))
                return max(0.0, f) if math.isfinite(f) else default
            except Exception:
                return default
        try:
            f = float(val)
            return max(0.0, f) if math.isfinite(f) else default
        except Exception:
            return default
    return default


def bayesian_posterior(
    tp: int | float,
    fp: int | float,
    confidence: float = 0.90,
) -> Dict[str, Union[float, str, int]]:
    """Wilson-bounded fitness scoring with Jeffrey's prior.

    Uses the Wilson score interval for lower/upper bounds (correct for small n)
    and Jeffrey's Beta(0.5, 0.5) prior for the posterior mean.

    Args:
        tp: True positives.
        fp: False positives.
        confidence: Confidence level (0.90, 0.95, or 0.99).

    Returns:
        Dict with keys: mean, lower, lower_90, upper, upper_90, certainty, n.
    """
    tp_num = _to_num(tp)
    fp_num = _to_num(fp)
    a = tp_num + 0.5
    b = fp_num + 0.5
    mean = a / (a + b)
    z = {0.90: 1.645, 0.95: 1.96, 0.99: 2.576}.get(confidence, 1.645)
    total = tp_num + fp_num
    lower, upper = _wilson_interval(tp_num, total, z)
    lower = round(lower, 4)
    upper = round(upper, 4)
    return {
        'mean': round(mean, 4),
        'lower': lower,
        'lower_90': lower,    # Backward compat alias
        'upper': upper,
        'upper_90': upper,    # Backward compat alias
        'certainty': 'low' if total < 5 else 'medium' if total < 20 else 'high',
        'n': int(total) if float(total).is_integer() else round(total, 2),
    }


def wilson_lower_bound(
    tp: int | float,
    triggers: int | float,
    z: float = 1.645,
) -> float:
    """Wilson score lower bound for success rate with confidence z.

    Args:
        tp: Number of successes (true positives).
        triggers: Total number of observations.
        z: Z-score for confidence level (default 1.645 for 90%).

    Returns:
        Lower bound strictly in [0.0, 1.0].
    """
    lower, _ = _wilson_interval(tp, triggers, z=z)
    return max(0.0, min(1.0, lower))


def laplace_score(
    tp: int | float,
    triggers: int | float,
    impact_weight: float = 1.0,
) -> float:
    """Laplace-smoothed point estimate: (tp+1)/(triggers+2) × impact.

    Args:
        tp: True positives.
        triggers: Total trigger count.
        impact_weight: Multiplicative weight for impact scoring.

    Returns:
        Smoothed score in [0, 1] × impact_weight.
    """
    weight = float(_to_num(impact_weight, default=1.0))
    tp_num = _to_num(tp)
    triggers_num = max(_to_num(triggers), tp_num)
    score = ((tp_num + 1.0) / (triggers_num + 2.0)) * weight
    return max(0.0, min(1.0 * weight, score)) if weight > 0 else 0.0


def bayesian_score(
    tp: int | float,
    triggers: int | float,
    impact_weight: float = 1.0,
) -> float:
    """Canonical Laplace-smoothed point estimate: (tp+1)/(triggers+2) × impact.

    Identical to laplace_score; provided as the canonical scalar scoring interface.
    For full credible intervals and certainty bounds, use bayesian_posterior().
    """
    return laplace_score(tp, triggers, impact_weight)


def compute_cell_fitness(cell: Dict[str, Any]) -> float:
    """Extract and compute fitness score from a cell dict.

    Canonical replacement for duplicate scoring across JIT engine and enzymes.
    """
    fitness = cell.get('fitness', '')
    impact_weight = cell.get('impact_weight', 1.0)
    try:
        impact_weight = float(impact_weight)
    except (ValueError, TypeError):
        impact_weight = 1.0

    if isinstance(fitness, dict):
        score = fitness.get('score')
        tp = fitness.get('true_positives', 0)
        triggers = fitness.get('triggers', 0)
        try:
            tp_f, trig_f = float(tp), float(triggers)
            if trig_f > 0:
                return laplace_score(tp_f, trig_f, impact_weight)
        except (ValueError, TypeError):
            pass
        if score is not None:
            try:
                return float(score) * impact_weight
            except (ValueError, TypeError):
                pass

    triggers = cell.get('triggers', '0')
    tp = cell.get('true_positives', '0')
    try:
        tp_f = float(tp)
        trig_f = float(triggers)
        if trig_f > 0:
            return laplace_score(tp_f, trig_f, impact_weight)
    except (ValueError, TypeError):
        pass

    try:
        return float(fitness) * impact_weight
    except (ValueError, TypeError):
        return 0.5 * impact_weight


def calculate_snr(tp: int | float, fp: int | float) -> float | None:
    """Calculate Signal-to-Noise Ratio in decibels (dB).

    Returns:
        - 10 * log10(tp / fp) rounded to 1 decimal if tp > 0 and fp > 0
        - None if tp > 0 and fp == 0 (infinite SNR, RFC 8259 compliant)
        - -99.0 if tp == 0 and fp > 0 (zero signal / pure noise, RFC 8259 compliant)
        - 0.0 if tp == 0 and fp == 0
    """
    tp_val = float(tp) if tp is not None else 0.0
    fp_val = float(fp) if fp is not None else 0.0
    if tp_val > 0 and fp_val > 0:
        return round(10.0 * math.log10(tp_val / fp_val), 1)
    elif tp_val > 0:
        return None
    elif fp_val > 0:
        return -99.0
    return 0.0


calculate_composite_fitness = compute_cell_fitness

# ── Salience Scoring Engine (Phase 22 / v0.119.0) ──────────────────────────

SALIENT_EXPLORATION_PRIOR = 0.20  # S_base
SALIENT_DECAY_FLOOR = 0.20        # R_min
SALIENT_GATE_WEIGHT = 5.0         # W_gate
SALIENT_WALL_WEIGHT = 2.0         # W_wall
SALIENT_VACUOLE_WEIGHT = 1.0      # W_vacuole
SALIENT_GATE_UNTESTED = 1.0       # S_gate_untested

SPECIFICITY_MULTIPLIERS = {
    "ast_match": 1.5,
    "exact_path": 1.2,
    "glob_match": 1.0,
    "base": 0.8,
}


def compute_salience(
    cell: Dict[str, Any],
    match_type: str = "glob_match",
    now: Optional[Any] = None,
    decay_lambda: float = 0.05,
    r_min: float = SALIENT_DECAY_FLOOR,
    s_base: float = SALIENT_EXPLORATION_PRIOR,
) -> float:
    """Compute cold-start safe Salience score for a cell.

    Formula:
        Salience(C) = W_tier(C) * (S_base + (1 - S_base) * WLB_95(tp, triggers)) * R(t) * sigma(C, diff)

    Guarantees:
    - Untested security gates receive priority weight W_gate=5.0 and S_gate_untested=1.0.
    - S_base=0.20 exploration prior guarantees newly created cells are never starved (Salience > 0).
    - Clamped temporal decay floor R(t) >= R_min=0.20 prevents stable invariants from dying.
    - Monotonic clock-skew guard prevents future dates from producing R(t) > 1.0.
    """
    from datetime import datetime, timezone

    if now is None:
        now = datetime.now(timezone.utc)
    elif hasattr(now, "tzinfo") and now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    # 1. Tier Weight W_tier(C)
    meta = cell.get("frontmatter", cell) if isinstance(cell, dict) else {}
    cell_type = str(meta.get("type", cell.get("type", "vacuole"))).lower()
    enforcement = str(meta.get("enforcement", cell.get("enforcement", ""))).lower()

    is_gate = cell_type == "gate" or enforcement == "gate"
    if is_gate:
        w_tier = SALIENT_GATE_WEIGHT
    elif cell_type == "wall" or enforcement == "wall":
        w_tier = SALIENT_WALL_WEIGHT
    elif cell_type == "vacuole":
        w_tier = SALIENT_VACUOLE_WEIGHT
    else:
        w_tier = 1.0

    # 2. Fitness & Prior
    fitness = meta.get("fitness") or cell.get("fitness") or {}
    if not isinstance(fitness, dict):
        fitness = {}

    tp = _to_num(fitness.get("true_positives", cell.get("true_positives", 0)))
    triggers = _to_num(fitness.get("triggers", cell.get("triggers", 0)))

    if is_gate and triggers == 0:
        empirical_prior = SALIENT_GATE_UNTESTED
    else:
        wlb_95 = wilson_lower_bound(tp, triggers, z=1.96) if triggers > 0 else 0.0
        empirical_prior = s_base + (1.0 - s_base) * wlb_95

    # 3. Clamped Temporal Decay Floor R(t)
    last_trigger_str = (
        fitness.get("last_trigger_date")
        or cell.get("last_trigger_date")
        or fitness.get("last_verified_date")
        or cell.get("last_verified_date")
    )
    if last_trigger_str:
        try:
            cleaned_str = str(last_trigger_str).replace("Z", "+00:00")
            last_dt = datetime.fromisoformat(cleaned_str)
            if last_dt.tzinfo is None:
                last_dt = last_dt.replace(tzinfo=timezone.utc)
            delta_days = max(0.0, (now - last_dt).total_seconds() / 86400.0)
            decay_factor = math.exp(-decay_lambda * delta_days)
            r_t = r_min + (1.0 - r_min) * decay_factor
        except Exception:
            r_t = 1.0
    else:
        r_t = 1.0

    # 4. Specificity Multiplier sigma
    sigma = SPECIFICITY_MULTIPLIERS.get(match_type, 1.0)

    score = w_tier * empirical_prior * r_t * sigma
    return round(score, 6)


__all__ = [
    "_wilson_interval",
    "_to_num",
    "bayesian_posterior",
    "wilson_lower_bound",
    "laplace_score",
    "bayesian_score",
    "compute_cell_fitness",
    "calculate_composite_fitness",
    "calculate_snr",
    "SALIENT_EXPLORATION_PRIOR",
    "SALIENT_DECAY_FLOOR",
    "SALIENT_GATE_WEIGHT",
    "SALIENT_WALL_WEIGHT",
    "SALIENT_VACUOLE_WEIGHT",
    "SALIENT_GATE_UNTESTED",
    "SPECIFICITY_MULTIPLIERS",
    "compute_salience",
]

"""Quorum sensing and lifecycle state predicates."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from aegis_core.scoring import laplace_score
from .constants import (
    EXTINCTION_THRESHOLD,
    MIN_PROMOTION_TRIGGERS,
    PROMOTION_THRESHOLD,
    STATUS_ADAPT,
    STATUS_APOPTOSIS,
    STATUS_APOPTOSIS_WARNING,
    STATUS_DORMANT,
    STATUS_EXTINCT,
    STATUS_NEW,
    STATUS_RETIRED,
    STATUS_SURVIVE,
)


def calculate_fitness_status(
    cell_type: str,
    tp: int,
    fp: int,
    triggers: int,
    dec_score: Optional[float] = None,
    is_unobserved: bool = False,
    created_str: Optional[str] = None,
    expiry_days: Optional[int] = None,
) -> str:
    """Evaluate canonical cell lifecycle status from observations, score, and age."""
    if fp > 0 and (tp == 0 or fp > 2 * tp):
        return STATUS_APOPTOSIS_WARNING if cell_type == "wall" else STATUS_RETIRED

    if not is_unobserved and dec_score is not None:
        if dec_score > 0.7:
            return STATUS_SURVIVE
        elif dec_score > EXTINCTION_THRESHOLD:
            return STATUS_ADAPT
        else:
            return STATUS_EXTINCT

    if expiry_days and created_str:
        try:
            fmt = "%Y-%m-%dT%H:%M:%SZ" if "T" in created_str else "%Y-%m-%d"
            created_date = datetime.strptime(created_str, fmt)
            current_date = datetime.now(timezone.utc).replace(tzinfo=None)
            days_since_created = (current_date - created_date).days
            if days_since_created > expiry_days:
                return STATUS_DORMANT
            return STATUS_NEW
        except Exception:
            return STATUS_NEW

    return STATUS_NEW


def is_promotable(
    tp: int,
    triggers: int,
    min_triggers: int = MIN_PROMOTION_TRIGGERS,
    threshold: float = PROMOTION_THRESHOLD,
) -> bool:
    """Determine if cell metrics qualify for promotion."""
    if triggers < min_triggers:
        return False
    score = laplace_score(tp, triggers)
    return score > threshold


def is_extinct(
    tp: int,
    triggers: int,
    threshold: float = EXTINCTION_THRESHOLD,
) -> bool:
    """Determine if cell metrics fall at or below extinction boundary."""
    if triggers <= 0:
        return False
    score = laplace_score(tp, triggers)
    return score <= threshold

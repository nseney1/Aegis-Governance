"""Rule fitness, computed at read time from the outcome ledger (ADR 0005 H6, AD-1; defense #15).

One estimator and one decay, used by status, aegis_list_rules, scan ranking, sync and
the lifecycle:

- **Estimator**: the Wilson score lower bound (90% confidence) of the true-positive
  rate over the rule's verdict rows (tp + fp, weighted). A bare ``trigger`` row says a
  rule was relevant without a verdict, so it is not counted as a failure. A rule with
  no verdicts scores 0.0: nothing is known yet.
- **Decay**: the score halves every ``expiry`` days (``.aegis/config.json``, per rule
  type; ``null`` means never) since the rule's last trigger, so old evidence fades.

``misfire`` is the same bound for the false-positive rate; the lifecycle uses it to
suggest demoting or archiving a rule that mostly fires wrongly. Rule frontmatter is
never read for fitness and never written.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import math
from typing import Any, Dict, Iterable, Mapping, Optional, Tuple

from aegis_core.taxonomy import DEFAULT_CONFIDENCE_LEVEL, WILSON_CONFIDENCE_Z_SCORES

__all__ = [
    "Fitness",
    "compute",
    "decay_factor",
    "for_rules",
    "wilson_interval",
    "wilson_lower_bound",
]

Z = WILSON_CONFIDENCE_Z_SCORES[DEFAULT_CONFIDENCE_LEVEL]


def _num(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        try:
            value = float(value)
        except (TypeError, ValueError):
            return 0.0
    value = float(value)
    return value if math.isfinite(value) and value > 0 else 0.0


def wilson_interval(successes: float, n: float, z: float = Z) -> Tuple[float, float]:
    """The Wilson score interval of ``successes`` out of ``n`` (both may be weighted)."""
    total = _num(n)
    if total == 0.0:
        return 0.0, 1.0
    p = min(_num(successes), total) / total
    denom = 1.0 + z * z / total
    center = (p + z * z / (2.0 * total)) / denom
    spread = z * math.sqrt(max(0.0, (p * (1.0 - p) + z * z / (4.0 * total)) / total)) / denom
    return max(0.0, center - spread), min(1.0, center + spread)


def wilson_lower_bound(successes: float, n: float, z: float = Z) -> float:
    """The lower end of the Wilson interval; 0.0 when ``n`` is 0."""
    if _num(n) == 0.0:
        return 0.0
    return wilson_interval(successes, n, z)[0]


def _parse_ts(value: Any) -> Optional[datetime]:
    if not isinstance(value, str) or not value:
        return None
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


def decay_factor(last_ts: Optional[str], half_life_days: Optional[float], now: Optional[datetime] = None) -> float:
    """``0.5 ** (days since last_ts / half_life_days)``; 1.0 without a half-life or a usable
    timestamp. A timestamp in the future never raises fitness above the undecayed bound."""
    if not half_life_days or half_life_days <= 0:
        return 1.0
    last = _parse_ts(last_ts)
    if last is None:
        return 1.0
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    days = (current - last).total_seconds() / 86400.0
    return 1.0 if days <= 0 else 0.5 ** (days / float(half_life_days))


@dataclass(frozen=True)
class Fitness:
    """A rule's ledger totals and the fitness derived from them."""

    rule: str = ""
    triggers: int = 0
    tp: float = 0
    fp: float = 0
    last_ts: Optional[str] = None
    score: float = 0.0
    misfire: float = 0.0

    @property
    def verdicts(self) -> float:
        return self.tp + self.fp

    def as_dict(self) -> Dict[str, Any]:
        return {
            "triggers": self.triggers,
            "tp": self.tp,
            "fp": self.fp,
            "last_ts": self.last_ts,
            "score": self.score,
        }


def compute(
    totals: Mapping[str, Any],
    half_life_days: Optional[float] = None,
    now: Optional[datetime] = None,
    rule: str = "",
) -> Fitness:
    """Fitness from one rule's ledger totals ``{triggers, tp, fp, last_ts}`` (ledger.aggregate)."""
    tp, fp = totals.get("tp", 0) or 0, totals.get("fp", 0) or 0
    n = _num(tp) + _num(fp)
    score = wilson_lower_bound(tp, n) * decay_factor(totals.get("last_ts"), half_life_days, now)
    return Fitness(
        rule=rule,
        triggers=int(_num(totals.get("triggers", 0))),
        tp=tp,
        fp=fp,
        last_ts=totals.get("last_ts"),
        score=round(score, 4),
        misfire=round(wilson_lower_bound(fp, n), 4),
    )


def for_rules(workspace: Any, rules: Iterable[Any], now: Optional[datetime] = None) -> Dict[str, Fitness]:
    """Fitness of each rule (records with ``id`` and ``type``) from ``workspace``'s ledger.

    The half-life of each rule is the repository's ``expiry`` for its type; an unusable
    config file falls back to the defaults (its problem is reported by ``aegis doctor``).
    """
    from aegis_core.config import ConfigError, RepoConfig
    from aegis_core.telemetry_engine import ledger

    try:
        config = RepoConfig.load(workspace)
    except ConfigError:
        config = RepoConfig()
    totals = ledger.aggregate(workspace)
    return {
        rule.id: compute(totals.get(rule.id, {}), config.expiry_for(rule.type), now, rule.id)
        for rule in rules
    }

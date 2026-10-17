"""Rule fitness, computed at read time from the outcome ledger (ADR 0005 H6, AD-1; v4.3 T4).

One estimator and read-time decay, used by status, aegis_list_rules, scan ranking, sync and
the lifecycle:

- **Estimator**: Wilson score lower bound (90% confidence) and Clopper-Pearson / Beta-Binomial
  bounds over the rule's verdicts and adjudicated labels. Prior mass from packs is capped at
  <= 10 pseudo-labels with explicit disclosure (``prior supplies X% of the evidence``).
- **Overrides**: ``# aegis: allow`` rows are counted as ``contested`` (never ``fp``); high
  override rates flag the rule for human review and never auto-demote it.
- **Four sample-size states**: ``untestable`` (180-day MDE at 80% power > 0.6), ``insufficient``
  (``n < min_n``, showing ``insufficient (n=K)`` and no precision number), ``inconclusive``
  (posterior shown, no transition), and ``decided`` (promotion/demotion transition suggested).
- **Decay**: session-count decay ``w = 2 ** (-delta / H)`` over heartbeat-alive eligible
  sessions since the last reinforcing evidence (with doubt-served ``fallback_unscoped``
  sessions neutral per v4.4 §12.9), plus wall-clock ``expiry`` days fallback when no session
  exposures exist. Traps below ``epsilon`` without ``pin: true`` become archive candidates;
  gates and invariants never archive on silence.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import re
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

from aegis_core.taxonomy import DEFAULT_CONFIDENCE_LEVEL, WILSON_CONFIDENCE_Z_SCORES

__all__ = [
    "DEFAULT_ARCHIVE_EPSILON",
    "DEFAULT_HALF_LIFE_SESSIONS",
    "DEFAULT_MIN_N",
    "Fitness",
    "MAX_PRIOR_MASS",
    "MDE_UNTESTABLE_THRESHOLD",
    "beta_cdf",
    "beta_ppf",
    "cap_prior",
    "clopper_pearson_interval",
    "compute",
    "compute_mde_180d",
    "compute_silence_credit",
    "decay_factor",
    "for_rules",
    "replay_detector_history",
    "session_decay_factor",
    "wilson_interval",
    "wilson_lower_bound",
]

Z = WILSON_CONFIDENCE_Z_SCORES[DEFAULT_CONFIDENCE_LEVEL]
MAX_PRIOR_MASS = 10.0
DEFAULT_MIN_N = 10
DEFAULT_HALF_LIFE_SESSIONS = 20
DEFAULT_ARCHIVE_EPSILON = 0.15
DEFAULT_MDE_HORIZON_DAYS = 180.0
MDE_UNTESTABLE_THRESHOLD = 0.6


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


# ── Exact Binomial / Beta-Binomial (Pure Python stdlib) ─────────────────────


def _betacf(a: float, b: float, x: float) -> float:
    """Lentz's continued fraction for the regularized incomplete beta function."""
    max_iter = 200
    eps = 3.0e-14
    fpmin = 1.0e-300
    qab = a + b
    qap = a + 1.0
    qam = a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < fpmin:
        d = fpmin
    d = 1.0 / d
    h = d
    for m in range(1, max_iter + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < fpmin:
            d = fpmin
        c = 1.0 + aa / c
        if abs(c) < fpmin:
            c = fpmin
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < fpmin:
            d = fpmin
        c = 1.0 + aa / c
        if abs(c) < fpmin:
            c = fpmin
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < eps:
            break
    return h


def beta_cdf(x: float, a: float, b: float) -> float:
    """Regularized incomplete beta function I_x(a, b) = P(Beta(a, b) <= x)."""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    if a <= 0.0 or b <= 0.0:
        return 0.0
    lbeta = math.lgamma(a) + math.lgamma(b) - math.lgamma(a + b)
    bt = math.exp(a * math.log(x) + b * math.log(1.0 - x) - lbeta)
    if x < (a + 1.0) / (a + b + 2.0):
        return max(0.0, min(1.0, bt * _betacf(a, b, x) / a))
    return max(0.0, min(1.0, 1.0 - bt * _betacf(b, a, 1.0 - x) / b))


def beta_ppf(q: float, a: float, b: float) -> float:
    """Inverse of ``beta_cdf`` via bisection."""
    if q <= 0.0:
        return 0.0
    if q >= 1.0:
        return 1.0
    lo, hi = 0.0, 1.0
    for _ in range(52):
        mid = 0.5 * (lo + hi)
        if beta_cdf(mid, a, b) < q:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def cap_prior(
    alpha0: float, beta0: float, max_mass: float = MAX_PRIOR_MASS
) -> Tuple[float, float]:
    """Cap prior pseudo-label mass ``alpha0 + beta0`` at ``max_mass`` (default 10.0)."""
    a = max(0.0, float(alpha0))
    b = max(0.0, float(beta0))
    mass = a + b
    if mass > max_mass and mass > 0.0:
        scale = max_mass / mass
        return a * scale, b * scale
    return a, b


def clopper_pearson_interval(
    tp: float,
    n: float,
    alpha: float = 0.10,
    *,
    prior: Optional[Tuple[float, float]] = None,
) -> Tuple[float, float]:
    """Exact Clopper-Pearson confidence interval (or Beta-Binomial credible interval when
    a capped prior is supplied) at level ``1 - alpha``."""
    k = _num(tp)
    total = _num(n)
    a0, b0 = cap_prior(prior[0], prior[1]) if prior is not None else (0.0, 0.0)
    eff_k = k + a0
    eff_fail = max(0.0, total - k) + b0
    eff_n = eff_k + eff_fail
    if eff_n <= 0.0:
        return 0.0, 1.0
    lo = 0.0 if eff_k <= 0.0 else beta_ppf(alpha / 2.0, eff_k, eff_fail + (1.0 if a0 == 0.0 else 0.0))
    hi = 1.0 if eff_fail <= 0.0 else beta_ppf(1.0 - alpha / 2.0, eff_k + (1.0 if b0 == 0.0 else 0.0), eff_fail)
    return max(0.0, lo), min(1.0, hi)


def compute_mde_180d(
    trigger_rate_per_day: float,
    horizon_days: float = DEFAULT_MDE_HORIZON_DAYS,
) -> float:
    """Minimum detectable effect at 80% power (alpha=0.05, one-sided) over ``horizon_days``."""
    rate = _num(trigger_rate_per_day)
    horizon = _num(horizon_days)
    expected_n = rate * horizon
    if expected_n <= 0.0:
        return 1.0
    # (z_{0.05} + z_{0.20}) * sqrt(p(1-p)) with worst-case p=0.5 -> 2.48647 * 0.5 = 1.24324
    return min(1.0, 1.24324 / math.sqrt(expected_n))


def compute_silence_credit(
    rrr: float,
    *,
    c: float = 0.1,
    heartbeat_alive: bool = True,
    scope_basis: Optional[str] = None,
    clean_sessions: int = 1,
) -> float:
    """Likelihood ratio ``LR = exp(c * RRR)`` for clean exposed sessions where the
    compliance heartbeat was alive and the exposure was not doubt-served."""
    if not heartbeat_alive or scope_basis == "fallback_unscoped":
        return 1.0
    r = _num(rrr)
    k = max(0, int(clean_sessions))
    if r <= 0.0 or k == 0:
        return 1.0
    return math.exp(float(c) * r * k)


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


def session_decay_factor(
    eligible_sessions: int,
    half_life_sessions: Optional[float] = DEFAULT_HALF_LIFE_SESSIONS,
) -> float:
    """``2 ** (-eligible_sessions / half_life_sessions)``; 1.0 when <= 0 or no half-life."""
    if eligible_sessions <= 0 or not half_life_sessions or half_life_sessions <= 0:
        return 1.0
    return float(2.0 ** (-float(eligible_sessions) / float(half_life_sessions)))


@dataclass(frozen=True)
class Fitness:
    """A rule's ledger totals and the fitness and T4 evidence state derived from them."""

    rule: str = ""
    triggers: int = 0
    tp: float = 0
    fp: float = 0
    last_ts: Optional[str] = None
    score: float = 0.0
    misfire: float = 0.0
    state: str = "insufficient"
    adjudicated_n: int = 0
    adjudicated_tp: int = 0
    adjudicated_fp: int = 0
    caught: int = 0
    leaked: int = 0
    contested: int = 0
    override_rate: float = 0.0
    flagged_for_review: bool = False
    precision_lo: float = 0.0
    precision_hi: float = 1.0
    p_below_demote: float = 0.0
    prior_mass: float = 0.0
    prior_share: float = 0.0
    prior_disclosure: Optional[str] = None
    mde: Optional[float] = None
    eligible_sessions: int = 0
    decay_factor: float = 1.0
    effective_weight: float = 1.0
    archive_candidate: bool = False
    silence_lr: float = 1.0
    sessions_count: int = 0
    repos_count: int = 0
    days_span: float = 0.0
    samples: Tuple[Dict[str, Any], ...] = ()
    suggestion: Optional[str] = None

    @property
    def verdicts(self) -> float:
        return self.tp + self.fp

    @property
    def status_label(self) -> Optional[str]:
        n = self.adjudicated_n if self.adjudicated_n > 0 else int(self.verdicts)
        if self.state == "untestable":
            return "untestable (insufficient trigger volume)"
        if self.state == "insufficient" and n > 0:
            return f"insufficient (n={n})"
        return None

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
    *,
    prior: Optional[Tuple[float, float]] = None,
    trigger_rate_per_day: Optional[float] = None,
    min_n: int = DEFAULT_MIN_N,
    eligible_sessions: int = 0,
    half_life_sessions: Optional[float] = None,
    epsilon: float = DEFAULT_ARCHIVE_EPSILON,
    rule_type: str = "trap",
    pinned: bool = False,
    contested: int = 0,
    caught: int = 0,
    leaked: int = 0,
    adjudicated_tp: int = 0,
    adjudicated_fp: int = 0,
    sessions_count: int = 0,
    repos_count: int = 0,
    days_span: float = 0.0,
    samples: Sequence[Mapping[str, Any]] = (),
    silence_lr: float = 1.0,
) -> Fitness:
    """Fitness from one rule's ledger totals ``{triggers, tp, fp, last_ts}`` plus optional T4 inputs."""
    base_tp = _num(totals.get("tp", 0) or 0)
    base_fp = _num(totals.get("fp", 0) or 0)
    adj_n = int(adjudicated_tp) + int(adjudicated_fp)

    # Combine legacy verdicts with adjudicated labels and detector replay findings when not already in totals.
    tp = base_tp + float(adjudicated_tp) + 0.5 * float(caught)
    fp = base_fp + float(adjudicated_fp) + 1.0 * float(leaked)
    # Preserve exact int/float representation when no fractional weights were added.
    if tp == int(tp) and isinstance(totals.get("tp", 0), int) and caught % 2 == 0:
        tp = int(tp)
    if fp == int(fp) and isinstance(totals.get("fp", 0), int):
        fp = int(fp)

    n = _num(tp) + _num(fp)
    triggers = int(_num(totals.get("triggers", 0))) + adj_n + int(caught) + int(leaked)

    a0, b0 = cap_prior(prior[0], prior[1]) if prior is not None else (0.0, 0.0)
    prior_mass = a0 + b0
    prior_share = (prior_mass / (prior_mass + n)) if (prior_mass + n) > 0.0 else 0.0
    prior_disclosure = (
        f"prior supplies {int(round(prior_share * 100))}% of the evidence"
        if prior_mass > 0.0
        else None
    )

    mde: Optional[float] = None
    if trigger_rate_per_day is not None:
        mde = round(compute_mde_180d(trigger_rate_per_day), 4)

    time_decay = decay_factor(totals.get("last_ts"), half_life_days, now)
    sess_decay = (
        session_decay_factor(eligible_sessions, half_life_sessions)
        if half_life_sessions is not None and eligible_sessions > 0
        else 1.0
    )
    combined_decay = sess_decay if eligible_sessions > 0 else time_decay
    effective_weight = round(1.0 * sess_decay, 6) if eligible_sessions > 0 else round(1.0 * time_decay, 6)

    raw_wilson = wilson_lower_bound(_num(tp) + a0, n + prior_mass)
    score = round(raw_wilson * combined_decay, 4) if n > 0 else 0.0
    misfire = round(wilson_lower_bound(_num(fp), n), 4) if n > 0 else 0.0

    cp_lo, cp_hi = clopper_pearson_interval(tp, n, alpha=0.10, prior=prior)
    # Posterior P(precision < 0.7) under Beta(1 + tp + a0, 1 + fp + b0)
    p_below_07 = beta_cdf(0.7, 1.0 + _num(tp) + a0, 1.0 + _num(fp) + b0) if n > 0 else 0.0

    # Contested overrides (# aegis: allow): never counted in fp!
    denom_ov = max(1, int(contested) + int(triggers))
    override_rate = round(float(contested) / float(denom_ov), 4) if contested > 0 else 0.0
    flagged_for_review = bool(contested > 0 and (contested >= 3 or override_rate >= 0.25))

    archive_candidate = bool(
        rule_type == "trap"
        and not pinned
        and eligible_sessions > 0
        and effective_weight < epsilon
    )

    # Determine T4 sample-size state and suggestion.
    demote_ready = bool(n >= 3 and (misfire > 0.5 or p_below_07 >= 0.9 or cp_hi < 0.7))
    if adj_n > 0:
        # Strict T4 promotion criteria when adjudicated labels are used.
        enough_positives = (adjudicated_tp >= 25 and adjudicated_fp == 0) or (
            adj_n >= 42 and adjudicated_fp <= 1 and cp_lo >= 0.88
        )
        enough_diversity = (sessions_count == 0 or sessions_count >= 3) and (
            repos_count >= 2 or days_span >= 14.0 or (repos_count == 0 and days_span == 0.0)
        )
        promote_ready = bool(rule_type == "trap" and enough_positives and enough_diversity)
    else:
        promote_ready = bool(rule_type == "trap" and n >= 20 and score >= 0.85)

    suggestion: Optional[str] = None
    if mde is not None and mde > MDE_UNTESTABLE_THRESHOLD:
        state = "untestable"
    elif demote_ready:
        state = "decided"
        suggestion = "demote" if rule_type in ("gate", "invariant") else "archive"
    elif promote_ready:
        state = "decided"
        suggestion = "promote"
    elif archive_candidate:
        state = "decided" if n >= min_n else "insufficient"
        suggestion = "archive"
    elif n < min_n:
        state = "insufficient"
    else:
        state = "inconclusive"

    return Fitness(
        rule=rule,
        triggers=triggers,
        tp=tp,
        fp=fp,
        last_ts=totals.get("last_ts"),
        score=score,
        misfire=misfire,
        state=state,
        adjudicated_n=adj_n,
        adjudicated_tp=int(adjudicated_tp),
        adjudicated_fp=int(adjudicated_fp),
        caught=int(caught),
        leaked=int(leaked),
        contested=int(contested),
        override_rate=override_rate,
        flagged_for_review=flagged_for_review,
        precision_lo=round(cp_lo, 4),
        precision_hi=round(cp_hi, 4),
        p_below_demote=round(p_below_07, 4),
        prior_mass=round(prior_mass, 4),
        prior_share=round(prior_share, 4),
        prior_disclosure=prior_disclosure,
        mde=mde,
        eligible_sessions=int(eligible_sessions),
        decay_factor=round(combined_decay, 6),
        effective_weight=effective_weight,
        archive_candidate=archive_candidate,
        silence_lr=round(float(silence_lr), 6),
        sessions_count=int(sessions_count),
        repos_count=int(repos_count),
        days_span=round(float(days_span), 2),
        samples=tuple(dict(s) for s in list(samples)[:3]),
        suggestion=suggestion,
    )


def _read_session_expiry_config(workspace: Any) -> Tuple[float, float]:
    """Read ``(half_life_sessions, epsilon)`` from ``.aegis/config.json`` if present."""
    from aegis_core.rules import workspace_root
    from aegis_core.workspace.layout import WorkspaceLayout

    root = Path(workspace_root(workspace))
    cfg_path = WorkspaceLayout(root).config_file
    half_life = float(DEFAULT_HALF_LIFE_SESSIONS)
    epsilon = float(DEFAULT_ARCHIVE_EPSILON)
    try:
        if cfg_path.is_file():
            raw = json.loads(cfg_path.read_text(encoding="utf-8"))
            if isinstance(raw, dict) and isinstance(raw.get("expiry"), dict):
                exp = raw["expiry"]
                if isinstance(exp.get("half_life_sessions"), (int, float)) and exp["half_life_sessions"] > 0:
                    half_life = float(exp["half_life_sessions"])
                if isinstance(exp.get("epsilon"), (int, float)) and exp["epsilon"] > 0:
                    epsilon = float(exp["epsilon"])
    except Exception:
        pass
    return half_life, epsilon


def _extract_rule_prior(rule: Any) -> Optional[Tuple[float, float]]:
    meta = getattr(rule, "meta", None)
    if not isinstance(meta, Mapping):
        return None
    prior_raw = meta.get("prior") or meta.get("pack_prior")
    if isinstance(prior_raw, Mapping):
        a = _num(prior_raw.get("alpha", prior_raw.get("tp", 0)))
        b = _num(prior_raw.get("beta", prior_raw.get("fp", 0)))
        if a + b > 0:
            return (a, b)
    return None


def _extract_rule_trigger_rate(rule: Any) -> Optional[float]:
    meta = getattr(rule, "meta", None)
    if not isinstance(meta, Mapping):
        return None
    for key in ("trigger_rate_per_day", "expected_triggers_per_day"):
        if key in meta and isinstance(meta[key], (int, float)):
            return float(meta[key])
    return None


def _collect_t4_events_for_rules(
    workspace: Any,
    rules: Sequence[Any],
    now: Optional[datetime] = None,
) -> Dict[str, Dict[str, Any]]:
    """Scan raw ledger rows in order to compute per-rule T4 counts, samples, and eligible sessions."""
    from aegis_core import credit
    from aegis_core.storage import read_jsonl
    from aegis_core.telemetry_engine import ledger

    rule_map = {r.id: r for r in rules}
    info: Dict[str, Dict[str, Any]] = {
        r.id: {
            "adjudicated_tp": 0,
            "adjudicated_fp": 0,
            "caught": 0,
            "leaked": 0,
            "contested": 0,
            "sessions": set(),
            "repos": set(),
            "timestamps": [],
            "samples": [],
            "post_reinforce_exposures": {},  # session -> list of (heartbeat_ok, scope_basis)
            "last_ts": None,
        }
        for r in rules
    }
    try:
        raw_rows = read_jsonl(ledger.ledger_path(workspace)).rows
    except Exception:
        return info

    # Also derive confirmed credits if any check/report/ci rows exist.
    event_rows = [
        credit._normalize_event_row(r)
        for r in raw_rows
        if isinstance(r, dict) and r.get("v") == ledger.LEDGER_VERSION and r.get("event") in credit.EVENTS
    ]
    confirmed_checks: Set[Tuple[str, str]] = set()
    if any(r.get("event") == "ci" for r in event_rows):
        try:
            for c in credit.derive(event_rows, landed=credit.landed_lookup(workspace)):
                if c.counts and c.result == "tp":
                    confirmed_checks.add((c.check, c.rule))
        except Exception:
            pass

    for raw in raw_rows:
        if not isinstance(raw, dict):
            continue
        rid = str(raw.get("rule") or raw.get("for_rule") or "")
        if rid not in info:
            continue
        bucket = info[rid]
        ts = raw.get("ts") or raw.get("timestamp")
        ev = raw.get("event")

        # Legacy v1/v2 positive outcome row reinforces the rule and resets decay counter.
        if ev is None:
            outcome = raw.get("outcome") or raw.get("signal")
            if outcome in ("tp", "success", "pass"):
                bucket["post_reinforce_exposures"] = {}
            continue

        if ev == "report" and (str(raw.get("check")), rid) in confirmed_checks:
            bucket["post_reinforce_exposures"] = {}
            continue

        if ev == "adjudication":
            verdict = raw.get("verdict")
            if verdict == "tp":
                bucket["adjudicated_tp"] += 1
                bucket["post_reinforce_exposures"] = {}
            elif verdict == "fp":
                bucket["adjudicated_fp"] += 1
            if raw.get("session"):
                bucket["sessions"].add(str(raw["session"]))
            if raw.get("repo"):
                bucket["repos"].add(str(raw["repo"]))
            if isinstance(ts, str) and ts:
                bucket["timestamps"].append(ts)
                if bucket["last_ts"] is None or ts > bucket["last_ts"]:
                    bucket["last_ts"] = ts
            if len(bucket["samples"]) < 3:
                bucket["samples"].append(
                    {
                        "kind": "adjudication",
                        "verdict": verdict,
                        "ref": raw.get("ref"),
                        "file": raw.get("file"),
                        "line": raw.get("line"),
                        "summary": raw.get("summary") or raw.get("snippet") or "",
                    }
                )
        elif ev == "detection":
            disp = raw.get("disposition")
            if disp == "caught":
                bucket["caught"] += 1
                bucket["post_reinforce_exposures"] = {}
            elif disp == "leaked":
                bucket["leaked"] += 1
            if isinstance(ts, str) and ts:
                if bucket["last_ts"] is None or ts > bucket["last_ts"]:
                    bucket["last_ts"] = ts
            if len(bucket["samples"]) < 3:
                bucket["samples"].append(
                    {
                        "kind": "detection",
                        "disposition": disp,
                        "file": raw.get("file"),
                        "pattern": raw.get("pattern"),
                        "branch": raw.get("branch"),
                        "rev": raw.get("rev"),
                    }
                )
        elif ev == "override":
            bucket["contested"] += 1
        elif ev == "exposure":
            sess = str(raw.get("session") or "")
            if not sess:
                continue
            hb_ok = raw.get("heartbeat") is not False and raw.get("heartbeat_alive") is not False
            basis = raw.get("scope_basis")
            bucket["post_reinforce_exposures"].setdefault(sess, []).append((hb_ok, basis))

    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)

    for rid, bucket in info.items():
        rule_obj = rule_map[rid]
        is_scoped = bool(getattr(rule_obj, "target_paths", None))
        eligible = 0
        for _sess, records in bucket["post_reinforce_exposures"].items():
            if not all(hb for hb, _b in records):
                continue
            if is_scoped or getattr(rule_obj, "type", "") == "trap":
                # v4.4 §12.9: only sessions where EVERY exposure row has no scope_basis
                # or scope_basis == 'match' are eligible; 'fallback_unscoped' is neutral.
                if not all(b in (None, "", "match") for _hb, b in records):
                    continue
            eligible += 1
        bucket["eligible_sessions"] = eligible

        # Compute days span from rule creation or adjudication timestamps.
        days_span = 0.0
        created_raw = (getattr(rule_obj, "meta", {}) or {}).get("created")
        if isinstance(created_raw, str) and created_raw:
            parsed_created = _parse_ts(
                created_raw if "T" in created_raw else f"{created_raw}T00:00:00Z"
            )
            if parsed_created is not None:
                days_span = max(0.0, (moment - parsed_created).total_seconds() / 86400.0)
        bucket["days_span"] = days_span

    return info


def for_rules(
    workspace: Any, rules: Iterable[Any], now: Optional[datetime] = None, view: Any = None,
) -> Dict[str, Fitness]:
    """Fitness of each rule (records with ``id`` and ``type``) from ``workspace``'s ledger,
    or from ``view`` (a ``ledger.read`` result) when the caller already read it."""
    from aegis_core.config import ConfigError, RepoConfig
    from aegis_core.telemetry_engine import ledger

    rule_list = list(rules)
    try:
        config = RepoConfig.load(workspace)
    except ConfigError:
        config = RepoConfig()
    half_life_sessions, epsilon = _read_session_expiry_config(workspace)
    totals = ledger.aggregate_rows((view if view is not None else ledger.read(workspace)).rows)
    t4_by_rule = _collect_t4_events_for_rules(workspace, rule_list, now=now)

    out: Dict[str, Fitness] = {}
    for rule in rule_list:
        rid = rule.id
        rtype = getattr(rule, "type", "trap") or "trap"
        meta = getattr(rule, "meta", {}) or {}
        pinned = bool(meta.get("pin") is True or meta.get("pinned") is True)
        rule_totals = dict(totals.get(rid, {}))
        t4 = t4_by_rule.get(rid, {})
        if not rule_totals.get("last_ts") and t4.get("last_ts"):
            rule_totals["last_ts"] = t4["last_ts"]
        out[rid] = compute(
            rule_totals,
            config.expiry_for(rtype),
            now,
            rid,
            prior=_extract_rule_prior(rule),
            trigger_rate_per_day=_extract_rule_trigger_rate(rule),
            eligible_sessions=int(t4.get("eligible_sessions", 0)),
            half_life_sessions=half_life_sessions,
            epsilon=epsilon,
            rule_type=rtype,
            pinned=pinned,
            contested=int(t4.get("contested", 0)),
            caught=int(t4.get("caught", 0)),
            leaked=int(t4.get("leaked", 0)),
            adjudicated_tp=int(t4.get("adjudicated_tp", 0)),
            adjudicated_fp=int(t4.get("adjudicated_fp", 0)),
            sessions_count=len(t4.get("sessions", ())),
            repos_count=len(t4.get("repos", ())),
            days_span=float(t4.get("days_span", 0.0)),
            samples=t4.get("samples", ()),
        )
    return out


# ── Detector Replay across Git History (§3 T4) ───────────────────────────────

_VIOLATION_PATTERN_RE = re.compile(r"Forbidden (?:call|import|decorator) '([^']+)'")
_MERGE_BRANCH_RE = re.compile(r"Merge branch '([^']+)'")


def _violations_at_commit(
    root: Path, commit: str, rules: Sequence[Any]
) -> Set[Tuple[str, str, str]]:
    """Return ``{(rule_id, rel_path, pattern)}`` for all ``forbid_ast`` hits at ``commit``."""
    from aegis_core import gitsafe
    from aegis_core.ast.policy import evaluate_forbid_ast_with_overrides, extract_normalized_ast

    res = gitsafe.run(["ls-tree", "-r", "--name-only", commit], root)
    if res.returncode != 0:
        return set()
    files = [
        line.strip()
        for line in res.stdout.decode("utf-8", "replace").splitlines()
        if line.strip().endswith(".py")
    ]
    hits: Set[Tuple[str, str, str]] = set()
    for rel in files:
        applicable = [r for r in rules if r.applies_to(rel)]
        if not applicable:
            continue
        try:
            blob = gitsafe.read_blob(root, commit, rel)
        except Exception:
            blob = None
        if not blob:
            continue
        source = blob.decode("utf-8", "replace")
        try:
            norm_ast = extract_normalized_ast(rel, workspace_root=root, code=source)
        except Exception:
            continue
        if norm_ast is None:
            continue
        for rule in applicable:
            spec = (getattr(rule, "meta", {}) or {}).get("forbid_ast")
            if not isinstance(spec, dict):
                continue
            try:
                violations, _overrides = evaluate_forbid_ast_with_overrides(
                    norm_ast, spec, rule_id=rule.id, source=source
                )
            except Exception:
                continue
            for msg in violations:
                match = _VIOLATION_PATTERN_RE.search(msg)
                pattern = match.group(1) if match else msg
                hits.add((rule.id, rel, pattern))
    return hits


def replay_detector_history(
    workspace: Any,
    rules: Optional[Iterable[Any]] = None,
    *,
    branch: str = "main",
    persist: bool = True,
) -> List[Dict[str, Any]]:
    """Run ``forbid_ast`` detectors across git history, classifying findings as:
    - ``caught`` (weight 0.5): introduced in an intermediate commit and removed before merge.
    - ``leaked`` (weight 1.0): present in a merged commit (or on ``branch`` and later reverted/fixed).
    Deduplicated by ``(rule, file, pattern, branch)``."""
    from aegis_core import credit, gitsafe
    from aegis_core.rules import load_rules, workspace_root

    root = Path(workspace_root(workspace)).resolve()
    loaded = list(rules) if rules is not None else list(load_rules(root).served)
    forbid_rules = [
        r
        for r in loaded
        if isinstance((getattr(r, "meta", {}) or {}).get("forbid_ast"), Mapping)
    ]
    if not forbid_rules:
        return []

    rev_res = gitsafe.run(["rev-list", "--parents", "--reverse", "HEAD"], root)
    if rev_res.returncode != 0:
        return []
    commit_lines = [
        line.strip().split()
        for line in rev_res.stdout.decode("utf-8", "replace").splitlines()
        if line.strip()
    ]
    if not commit_lines:
        return []

    hits_cache: Dict[str, Set[Tuple[str, str, str]]] = {}

    def hits_for(sha: str) -> Set[Tuple[str, str, str]]:
        if sha not in hits_cache:
            hits_cache[sha] = _violations_at_commit(root, sha, forbid_rules)
        return hits_cache[sha]

    def commit_subject(sha: str) -> str:
        r = gitsafe.run(["log", "-1", "--format=%s", sha], root)
        return r.stdout.decode("utf-8", "replace").strip() if r.returncode == 0 else ""

    findings: Dict[Tuple[str, str, str, str], Dict[str, Any]] = {}
    merge_commits = [parts for parts in commit_lines if len(parts) >= 3]

    if merge_commits:
        for parts in merge_commits:
            merge_sha, p1, p2 = parts[0], parts[1], parts[2]
            subj = commit_subject(merge_sha)
            m_branch = _MERGE_BRANCH_RE.search(subj)
            branch_label = m_branch.group(1) if m_branch else f"{branch}:{merge_sha[:8]}"

            # Commits on the feature branch (p1..p2)
            br_res = gitsafe.run(["rev-list", "--reverse", f"{p1}..{p2}"], root)
            branch_shas = [
                s.strip()
                for s in br_res.stdout.decode("utf-8", "replace").splitlines()
                if s.strip()
            ]
            base_hits = hits_for(p1)
            merge_hits = hits_for(merge_sha)

            # Leaked: present in the merge commit itself (and not already in base p1).
            for rule_id, rel, pattern in sorted(merge_hits - base_hits):
                key = (rule_id, rel, pattern, branch_label)
                findings[key] = {
                    "rule": rule_id,
                    "file": rel,
                    "pattern": pattern,
                    "disposition": "leaked",
                    "weight": 1.0,
                    "branch": branch_label,
                    "rev": merge_sha,
                }

            # Caught: introduced in an intermediate commit of p1..p2 and absent in merge_sha.
            for b_sha in branch_shas:
                for rule_id, rel, pattern in sorted(hits_for(b_sha) - base_hits):
                    if (rule_id, rel, pattern) in merge_hits:
                        continue
                    key = (rule_id, rel, pattern, branch_label)
                    if key not in findings:
                        findings[key] = {
                            "rule": rule_id,
                            "file": rel,
                            "pattern": pattern,
                            "disposition": "caught",
                            "weight": 0.5,
                            "branch": branch_label,
                            "rev": b_sha,
                            "fix_rev": merge_sha,
                        }
    else:
        # Linear history fallback
        shas = [parts[0] for parts in commit_lines]
        tip_hits = hits_for(shas[-1])
        for idx, sha in enumerate(shas):
            cur_hits = hits_for(sha)
            prev_hits = hits_for(shas[idx - 1]) if idx > 0 else set()
            for rule_id, rel, pattern in sorted(cur_hits - prev_hits):
                key = (rule_id, rel, pattern, branch)
                if (rule_id, rel, pattern) in tip_hits:
                    findings[key] = {
                        "rule": rule_id,
                        "file": rel,
                        "pattern": pattern,
                        "disposition": "leaked",
                        "weight": 1.0,
                        "branch": branch,
                        "rev": sha,
                    }
                else:
                    # Removed in a later commit: check if the removal commit was a revert.
                    fix_sha = next(
                        (later for later in shas[idx + 1 :] if (rule_id, rel, pattern) not in hits_for(later)),
                        shas[-1],
                    )
                    subj_lower = commit_subject(fix_sha).lower()
                    disp = "leaked" if "revert" in subj_lower else "caught"
                    findings[key] = {
                        "rule": rule_id,
                        "file": rel,
                        "pattern": pattern,
                        "disposition": disp,
                        "weight": 1.0 if disp == "leaked" else 0.5,
                        "branch": branch,
                        "rev": sha,
                        "fix_rev": fix_sha,
                    }

    results: List[Dict[str, Any]] = []
    for item in findings.values():
        if persist:
            row = credit.record_detection(
                root,
                item["rule"],
                item["file"],
                item["pattern"],
                disposition=item["disposition"],
                rev=item.get("rev"),
                branch=item["branch"],
                fix_rev=item.get("fix_rev"),
                weight=item["weight"],
            )
            results.append(row)
        else:
            results.append(dict(item))
    return results

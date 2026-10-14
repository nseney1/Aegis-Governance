"""aegis_core.resilience — Offline consolidation, signal coherence, interoception, and resilience.

Consolidates:
- Memory consolidation and dream compression (formerly enzymes/soma_sleep.py)
- Signal coherence and anti-reward hacking integrity engine (formerly enzymes/soma_coherence.py)
- Internal state proprioception and context degradation monitoring (formerly enzymes/soma_interoception.py)
- Stress response and endocrine graceful reset (formerly enzymes/resilience_engine.py)
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from datetime import datetime, timezone
import glob
import json
import os
from pathlib import Path
import re
import sys
from typing import Any, Dict, List, Optional, Tuple

from aegis_core.workspace import resolve_workspace
from aegis_core.yaml import parse_frontmatter, _get_body

# ── Signal Coherence & State Monitoring ───────────────────────────────────

PRUNE_SCORE_THRESHOLD = 0.4
RECENCY_WEIGHT = 2.0  # Recent outcomes count double


@dataclass
class ResilienceReport:
    """Summary of internal context degradation and stress resilience state."""
    status: str
    score: float
    signals: Dict[str, float] = field(default_factory=dict)
    action: str = "CONTINUE"
    message: str = ""


HomeostasisReport = ResilienceReport


# ── Signal Coherence Layer ─────────────────────────────────────────────────


@dataclass
class CoherenceSignal:
    ttc_approved: bool
    outcome_delta: float
    stress_level: int
    interoception_score: float
    prediction_match: float
    change_magnitude: int


@dataclass
class CoherenceResult:
    verdict: str
    score: float
    flags: List[str] = field(default_factory=list)
    message: str = ""


def check_coherence(signal: CoherenceSignal) -> CoherenceResult:
    flags = []
    incoherence_score = 0.0

    if signal.ttc_approved and signal.outcome_delta < -0.4:
        flags.append(
            "RULE_GAMING: TTC Verifier approved proposal but outcome was "
            f"strongly negative (delta={signal.outcome_delta:.2f}). "
            "Agent may have satisfied rule patterns without genuine alignment."
        )
        incoherence_score += 0.4

    if signal.stress_level == 0 and signal.interoception_score > 0.75:
        flags.append(
            "SIGNAL_SUPPRESSION: Stress is 0 (no reported failures) but "
            f"internal state is CRITICAL (score={signal.interoception_score:.2f}). "
            "Agent may be masking failures to avoid Graceful Reset."
        )
        incoherence_score += 0.35

    if signal.outcome_delta > 0.5 and signal.change_magnitude <= 1:
        flags.append(
            "METRIC_MANIPULATION: Outcome improved dramatically "
            f"(delta=+{signal.outcome_delta:.2f}) but only "
            f"{signal.change_magnitude} file(s) changed. "
            "Agent may have deleted failing tests or manipulated metrics."
        )
        incoherence_score += 0.5

    if signal.prediction_match < 0.3 and signal.outcome_delta > 0.2:
        flags.append(
            "HALLUCINATION: Agent's predictions were inaccurate "
            f"(match={signal.prediction_match:.2f}) but reports positive outcome. "
            "Agent may be hallucinating about what it actually changed."
        )
        incoherence_score += 0.35

    if not signal.ttc_approved and signal.outcome_delta > 0:
        flags.append(
            "GOVERNANCE_BYPASS: TTC Verifier rejected proposal but agent "
            "reports positive outcome. Agent may have circumvented the "
            "governance gate entirely."
        )
        incoherence_score += 0.6

    incoherence_score = min(1.0, incoherence_score)

    if incoherence_score == 0.0:
        verdict = "COHERENT"
        message = (
            "✅ All signals mutually consistent. Execution is likely genuine.\n"
            "Outcome aligns with expectations across all six signal dimensions."
        )
    elif len(flags) == 1:
        verdict = "SUSPICIOUS"
        message = (
            "⚠️  One incoherence detected. Flagging for elevated review.\n"
            "Do NOT block execution, but log this for the Sleep Engine to analyze."
        )
    else:
        verdict = "INCOHERENT"
        message = (
            "🛑 Multiple incoherences detected. This is a likely reward hacking event.\n"
            "HARD BLOCK: Discard the claimed outcome. Trigger Graceful Reset.\n"
            "The agent's reported success cannot be trusted."
        )

    return CoherenceResult(
        verdict=verdict,
        score=round(incoherence_score, 3),
        flags=flags,
        message=message,
    )




# ── Aegis Interoception Engine ─────────────────────────────────────────────

CAUTION_THRESHOLD = 0.5
CRITICAL_THRESHOLD = 0.75
WEIGHTS = {
    "token_density": 0.35,
    "entanglement": 0.25,
    "dependency_depth": 0.20,
    "coherence_decay": 0.20,
}


def normalize(value: float, min_val: float, max_val: float) -> float:
    """Normalize a raw signal to [0, 1]."""
    if max_val == min_val:
        return 0.0
    return max(0.0, min(1.0, (value - min_val) / (max_val - min_val)))


def calculate_internal_state(
    token_count: int,
    token_budget: int,
    files_touched: int,
    dependency_depth: int,
    turns_since_grounding: int,
) -> dict:
    """Compute the four signals and aggregate into an Internal State Score."""
    token_density = normalize(token_count, 0, token_budget)
    entanglement = normalize(files_touched, 0, 20)
    dependency = normalize(dependency_depth, 0, 10)
    coherence_decay = normalize(turns_since_grounding, 0, 20)

    score = (
        WEIGHTS["token_density"] * token_density
        + WEIGHTS["entanglement"] * entanglement
        + WEIGHTS["dependency_depth"] * dependency
        + WEIGHTS["coherence_decay"] * coherence_decay
    )

    signals = {
        "token_density": round(token_density, 2),
        "entanglement": round(entanglement, 2),
        "dependency_depth": round(dependency, 2),
        "coherence_decay": round(coherence_decay, 2),
    }

    if score >= CRITICAL_THRESHOLD:
        status = "CRITICAL"
        message = (
            "[INTEROCEPTION: CRITICAL STATE]\n"
            "Your internal context is severely degraded. Token window is dense, "
            "entanglement is high, and coherence is low.\n"
            "HARD STOP: Compress your context. Re-read the Dream Log. "
            "Re-state your Prime Directive alignment before any further action."
        )
    elif score >= CAUTION_THRESHOLD:
        status = "CAUTION"
        message = (
            "[INTEROCEPTION: CAUTION]\n"
            "Your internal state is degrading. Before proceeding, verify that "
            "your current action aligns with the active JIT Playbooks."
        )
    else:
        status = "CLEAR"
        message = "Internal state nominal. Proceed."

    return {
        "status": status,
        "score": round(score, 3),
        "signals": signals,
        "message": message,
    }


# ── Resilience Engine ──────────────────────────────────────────────────────

STRESS_THRESHOLD = 3
DRIFT_THRESHOLD = 15


def calculate_stress_response(consecutive_failures: int, turns_elapsed: int) -> Dict[str, str]:
    """Determines if stress or context drift warrants an intervention."""
    if consecutive_failures >= STRESS_THRESHOLD:
        reset_payload = """
[SYSTEM OVERRIDE: GRACEFUL RESET INITIATED]
You have failed this task multiple times consecutively. You are caught in a hallucination loop.

Do not panic, and do not try to force your current solution to work.
You must now execute a Graceful Reset:
1. Acknowledge that your previous assumptions were flawed.
2. Forgive the error and completely discard your current approach.
3. Fall back to your absolute Bastion Invariants (the 'rules/' folder).
4. Generate an entirely new, conservative approach from first principles.

Remember your Prime Directive: Do not reward-hack. Serve the ultimate health and stability of the codebase.
"""
        return {
            "status": "CRITICAL_STRESS",
            "metric": f"failures={consecutive_failures}",
            "action": "GRACEFUL_RESET",
            "payload": reset_payload.strip(),
        }

    if turns_elapsed >= DRIFT_THRESHOLD:
        devotional_payload = """
[SYSTEM OVERRIDE: GROUNDING PROBE (DEVOTIONAL) INITIATED]
You have been executing for 15+ turns. Your context window is heavily diluted by local code changes, increasing the risk of Moral Drift.

Pause your current task. Before taking any further action, you must explicitly state how your current trajectory aligns with the Prime Directive. 
(e.g., "I am modifying this file to ensure X, which aligns with the Bastion invariant of Y.")
"""
        return {
            "status": "CONTEXT_DRIFT",
            "metric": f"turns={turns_elapsed}",
            "action": "GROUNDING_PROBE",
            "payload": devotional_payload.strip(),
        }

    return {
        "status": "NOMINAL",
        "metric": f"failures={consecutive_failures}, turns={turns_elapsed}",
        "action": "CONTINUE",
        "payload": "",
    }


def evaluate_resilience(
    token_count: int = 0,
    token_budget: int = 100000,
    files_touched: int = 0,
    dependency_depth: int = 0,
    turns_since_grounding: int = 0,
    consecutive_failures: int = 0,
) -> ResilienceReport:
    """Evaluate combined internal state and stress resilience into a ResilienceReport."""
    state = calculate_internal_state(
        token_count=token_count,
        token_budget=token_budget,
        files_touched=files_touched,
        dependency_depth=dependency_depth,
        turns_since_grounding=turns_since_grounding,
    )
    stress = calculate_stress_response(
        consecutive_failures=consecutive_failures,
        turns_elapsed=turns_since_grounding,
    )
    status = stress["status"] if stress["status"] != "NOMINAL" else state["status"]
    action = stress.get("action", "CONTINUE")
    message = stress.get("payload") or state.get("message", "")
    return ResilienceReport(
        status=status,
        score=state["score"],
        signals=state["signals"],
        action=action,
        message=message,
    )


evaluate_homeostasis = evaluate_resilience


__all__ = [
    "PRUNE_SCORE_THRESHOLD",
    "RECENCY_WEIGHT",
    "ResilienceReport",
    "HomeostasisReport",
    "CoherenceSignal",
    "CoherenceResult",
    "check_coherence",
    "CAUTION_THRESHOLD",
    "CRITICAL_THRESHOLD",
    "normalize",
    "calculate_internal_state",
    "STRESS_THRESHOLD",
    "DRIFT_THRESHOLD",
    "WEIGHTS",
    "calculate_stress_response",
    "evaluate_resilience",
    "evaluate_homeostasis",
]

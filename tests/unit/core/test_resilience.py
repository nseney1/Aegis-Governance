"""Unit tests for aegis_core.resilience."""
import pytest
from aegis_core.resilience import (
    CoherenceSignal,
    ResilienceReport,
    check_coherence,
    calculate_internal_state,
    calculate_stress_response,
    evaluate_resilience,
    PRUNE_SCORE_THRESHOLD,
    RECENCY_WEIGHT,
    normalize,
)


def test_coherence_coherent_signal():
    sig = CoherenceSignal(
        ttc_approved=True,
        outcome_delta=0.1,
        stress_level=0,
        interoception_score=0.1,
        prediction_match=0.9,
        change_magnitude=3,
    )
    res = check_coherence(sig)
    assert res.verdict == "COHERENT"
    assert res.score == 0.0


def test_coherence_rule_gaming():
    sig = CoherenceSignal(
        ttc_approved=True,
        outcome_delta=-0.5,
        stress_level=1,
        interoception_score=0.3,
        prediction_match=0.5,
        change_magnitude=2,
    )
    res = check_coherence(sig)
    assert res.verdict == "SUSPICIOUS"
    assert any("RULE_GAMING" in f for f in res.flags)


def test_interoception_calculation():
    res = calculate_internal_state(
        token_count=1000,
        token_budget=100000,
        files_touched=1,
        dependency_depth=1,
        turns_since_grounding=1,
    )
    assert res["status"] == "CLEAR"
    assert res["score"] < 0.5


def test_resilience_nominal_and_stress():
    res_nom = calculate_stress_response(consecutive_failures=0, turns_elapsed=5)
    assert res_nom["status"] == "NOMINAL"

    res_stress = calculate_stress_response(consecutive_failures=3, turns_elapsed=5)
    assert res_stress["status"] == "CRITICAL_STRESS"
    assert res_stress["action"] == "GRACEFUL_RESET"


def test_evaluate_resilience_report():
    report = evaluate_resilience(
        token_count=1000,
        token_budget=100000,
        files_touched=1,
        dependency_depth=1,
        turns_since_grounding=1,
        consecutive_failures=0,
    )
    assert isinstance(report, ResilienceReport)
    assert report.status == "CLEAR"
    assert report.action == "CONTINUE"


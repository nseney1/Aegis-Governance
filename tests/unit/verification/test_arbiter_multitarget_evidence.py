"""Behavioral tests for BUG-078: Layer 1 Evidence Dictionary Collision in Arbiter.

In arbitrate(), layer1_by_tool must not overwrite earlier tool evidence when multiple
target files are evaluated. If any target file fails for a tool (verdict=False),
the arbiter must treat that tool evidence as failing for the adjudicated category,
preventing false convergences when one target passed but another target failed.
"""
import pytest
from aegis_core.verification import ToolEvidence, Prediction, Claim, RiskCategory, Severity, Verdict
from aegis_core.verification.arbiter import arbitrate


def test_multitarget_tool_failure_not_masked_by_passing_target():
    """If call_graph fails on file_a.py but passes on file_b.py, MISSING_WIRE must NOT converge."""
    evidence_a = ToolEvidence(tool="call_graph", target="file_a.py", verdict=False, detail="Orphan function found")
    evidence_b = ToolEvidence(tool="call_graph", target="file_b.py", verdict=True, detail="All calls wired")

    # Layer 1 evidence has both items (file_a failing first, file_b passing second)
    layer1_evidence = [evidence_a, evidence_b]

    # Both Spec Agent and Code Agent addressed MISSING_WIRE
    pred = Prediction(
        category=RiskCategory.MISSING_WIRE,
        severity=Severity.HIGH,
        risk="Unwired function in file_a",
        mechanism="Call omitted from entrypoint",
        affected_function="do_something",
    )
    claim = Claim(
        category=RiskCategory.MISSING_WIRE,
        claim="Everything wired properly",
        evidence_file="file_a.py",
        evidence_line=10,
    )

    result = arbitrate(
        predictions=[pred],
        claims=[claim],
        layer1_evidence=layer1_evidence,
    )

    # Because file_a failed call_graph, this should be a confirmed_risk or contradicted_claim, NOT a clean convergence
    assert RiskCategory.MISSING_WIRE not in result.convergences, (
        "BUG-078: Arbiter falsely declared convergence for MISSING_WIRE because file_b pass overwrote file_a failure!"
    )
    assert any(d.category == RiskCategory.MISSING_WIRE and d.divergence_type == "confirmed_risk" for d in result.divergences)
    assert result.verdict == Verdict.BLOCK

from __future__ import annotations

"""Arbiter: Deterministic divergence detector.

Compares Spec Agent predictions against Code Agent claims, with Layer 1
tool evidence as tiebreaker. Pure set logic — no LLM judgment.

The Arbiter answers three questions:
1. Did the Spec Agent predict a risk that the Code Agent didn't address? (blind spot)
2. Did the Code Agent claim something that Layer 1 tools contradict? (false claim)
3. Did both agree but Layer 1 shows a problem anyway? (shared blind spot)
"""
from . import (
    ArbitrationResult, Claim, Divergence, Prediction,
    RiskCategory, Severity, ToolEvidence, Verdict,
)


def arbitrate(
    predictions: list[Prediction],
    claims: list[Claim],
    layer1_evidence: list[ToolEvidence],
    *,
    spec_agent_failed: bool = False,
) -> ArbitrationResult:
    """Compare predictions vs claims vs tool evidence.

    Divergence detection is pure set operations on RiskCategory enums.
    No natural language comparison. No LLM.

    Returns ArbitrationResult with divergences, convergences, and verdict.
    """
    divergences: list[Divergence] = []
    convergences: list[RiskCategory] = []

    # Index by category for O(1) lookup
    pred_by_cat: dict[RiskCategory, list[Prediction]] = {}
    for p in predictions:
        pred_by_cat.setdefault(p.category, []).append(p)

    claim_by_cat: dict[RiskCategory, list[Claim]] = {}
    for c in claims:
        claim_by_cat.setdefault(c.category, []).append(c)

    # Index Layer 1 failures by relevance (BUG-078: group by tool to prevent multi-target collisions)
    layer1_failures = [e for e in layer1_evidence if not e.verdict]
    layer1_by_tool: dict[str, list[ToolEvidence]] = {}
    for e in layer1_evidence:
        layer1_by_tool.setdefault(e.tool, []).append(e)

    # Map Layer 1 tool names to risk categories they can adjudicate
    TOOL_TO_CATEGORY = {
        "persistence_checker": RiskCategory.PERSISTENCE_GAP,
        "branch_coverage": RiskCategory.DEAD_CODE,
        "mutation_tester": RiskCategory.TAUTOLOGICAL_TEST,
        "call_graph": RiskCategory.MISSING_WIRE,
        "import_guard": RiskCategory.BOUNDARY_VIOLATION,
    }

    all_categories = set(pred_by_cat.keys()) | set(claim_by_cat.keys())

    for cat in all_categories:
        preds = pred_by_cat.get(cat, [])
        cls = claim_by_cat.get(cat, [])

        # Find relevant Layer 1 evidence for this category
        # If any target file failed for this tool, prioritize that failure
        relevant_evidence = None
        for tool_name, tool_cat in TOOL_TO_CATEGORY.items():
            if tool_cat == cat and tool_name in layer1_by_tool:
                tool_evs = layer1_by_tool[tool_name]
                failing = next((ev for ev in tool_evs if not ev.verdict), None)
                relevant_evidence = failing if failing else tool_evs[0]
                break

        if preds and not cls:
            # Spec Agent predicted a risk, Code Agent didn't address it
            for p in preds:
                divergences.append(Divergence(
                    divergence_type="unmatched_prediction",
                    category=cat,
                    prediction=p,
                    tool_evidence=relevant_evidence,
                    resolution="Code Agent did not address this predicted risk",
                ))

        elif cls and not preds:
            # Code Agent claimed something Spec Agent didn't worry about
            # Low concern — but check Layer 1
            if relevant_evidence and not relevant_evidence.verdict:
                for c in cls:
                    divergences.append(Divergence(
                        divergence_type="contradicted_claim",
                        category=cat,
                        claim=c,
                        tool_evidence=relevant_evidence,
                        resolution="Claim contradicted by Layer 1 tool evidence",
                    ))
            else:
                convergences.append(cat)

        elif preds and cls:
            # Both agents addressed this category
            if relevant_evidence and not relevant_evidence.verdict:
                # Layer 1 FAILS — the claim is wrong despite addressing the risk
                for p in preds:
                    divergences.append(Divergence(
                        divergence_type="confirmed_risk",
                        category=cat,
                        prediction=p,
                        claim=cls[0],
                        tool_evidence=relevant_evidence,
                        resolution="Spec Agent prediction confirmed by Layer 1 failure",
                    ))
            else:
                convergences.append(cat)

    # Check for Layer 1 failures not covered by any prediction or claim
    for evidence in layer1_failures:
        tool_cat = TOOL_TO_CATEGORY.get(evidence.tool)
        if tool_cat and tool_cat not in all_categories:
            divergences.append(Divergence(
                divergence_type="undetected_by_both",
                category=tool_cat,
                tool_evidence=evidence,
                resolution="Neither agent identified this — caught only by Layer 1 tools",
            ))

    # Verdict logic
    verdict = _compute_verdict(
        divergences, layer1_failures,
        predictions=predictions,
        spec_agent_failed=spec_agent_failed,
    )

    return ArbitrationResult(
        divergences=divergences,
        convergences=convergences,
        verdict=verdict,
        layer1_results=layer1_evidence,
        predictions=predictions,
        claims=claims,
    )


def _compute_verdict(
    divergences: list[Divergence],
    layer1_failures: list[ToolEvidence],
    *,
    predictions: list[Prediction] | None = None,
    spec_agent_failed: bool = False,
) -> Verdict:
    """Deterministic verdict computation.

    BLOCK if:
      - Any Layer 1 tool FAILS
      - Any divergence has a critical prediction
      - Any claim is contradicted by Layer 1
      - Spec Agent failed and produced no predictions (fail-closed)

    REVISE if:
      - Any unmatched prediction with severity >= HIGH

    SHIP otherwise.
    """
    if layer1_failures:
        return Verdict.BLOCK

    # Fail-closed: if spec agent produced no predictions, don't silently ship
    if spec_agent_failed and not (predictions or []):
        return Verdict.BLOCK

    for d in divergences:
        if d.divergence_type == "contradicted_claim":
            return Verdict.BLOCK
        if d.divergence_type == "confirmed_risk":
            return Verdict.BLOCK
        if d.divergence_type == "undetected_by_both":
            return Verdict.BLOCK

    for d in divergences:
        if d.prediction and d.prediction.severity == Severity.CRITICAL:
            return Verdict.BLOCK

    for d in divergences:
        if d.prediction and d.prediction.severity == Severity.HIGH:
            return Verdict.REVISE

    return Verdict.SHIP


def format_report(result: ArbitrationResult) -> str:
    """Human-readable divergence report."""
    lines = ["═══ Two-Layer Verification Report ═══", ""]

    # Layer 1 summary
    lines.append("── Layer 1: Tool Evidence ──")
    for e in result.layer1_results:
        icon = "✅" if e.verdict else "🔴"
        lines.append(f"  {icon} {e.tool}: {e.target} → {'PASS' if e.verdict else 'FAIL'}")
        if not e.verdict:
            lines.append(f"     Detail: {e.detail}")
    lines.append("")

    # Convergences
    if result.convergences:
        lines.append("── Convergences (agreement) ──")
        for cat in result.convergences:
            lines.append(f"  ✅ {cat.value}")
        lines.append("")

    # Divergences
    if result.divergences:
        lines.append("── Divergences (disagreement) ──")
        for d in result.divergences:
            icon = {"unmatched_prediction": "⚠️",
                     "contradicted_claim": "🔴",
                     "confirmed_risk": "🔴",
                     "undetected_by_both": "💀"}[d.divergence_type]
            lines.append(f"  {icon} [{d.divergence_type}] {d.category.value}")
            if d.prediction:
                lines.append(f"     Prediction: {d.prediction.risk}")
            if d.claim:
                lines.append(f"     Claim: {d.claim.claim}")
            if d.tool_evidence:
                lines.append(f"     Tool: {d.tool_evidence.detail}")
            lines.append(f"     Resolution: {d.resolution}")
        lines.append("")

    lines.append(f"Verdict: {result.verdict.value.upper()}")
    return '\n'.join(lines)

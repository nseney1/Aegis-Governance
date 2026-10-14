"""Tests for Partitioned 2-Tier Token Budget and Atomic Directive Compression (Phase 22 / v0.119.0).

Validates:
1. Normal allocation: Tier 1 (Gates, 60% = 1200 tokens) and Tier 2 (Advisory, 40% = 800 tokens).
2. Headroom flow: Unused Tier 1 token budget flows into Tier 2 dynamic headroom.
3. Tier 1 over-subscription (>1200 tokens of gates): Tier 2 advisory rules are dropped to 0 tokens.
4. Incompressible Gate Guarantee: Under extreme gate pressure, gates are NEVER dropped;
   overflow gates compress to Atomic Invariant Directives so all gates fit within budget.
5. Tier 2 over-subscription: Advisory cells are selected strictly in descending Salience order.
"""
from __future__ import annotations

import pytest

from aegis_mcp.jit_engine import (
    compress_to_atomic_directive,
    pack_two_tier_context,
)


class TestTwoTierPacking:
    """Verifies 2-tier token budgeting and incompressible gate guarantees."""

    def test_both_tiers_fit_normal(self):
        """When both gates and advisory cells are small, both are included in full fidelity."""
        gates = [
            {
                "id": "gate-auth",
                "type": "gate",
                "enforcement": "gate",
                "hypothesis": "Auth tokens must be validated before processing.",
                "body": "Detailed security guidance on token parsing.",
                "_salience": 5.0,
            }
        ]
        advisory = [
            {
                "id": "wall-logging",
                "type": "wall",
                "hypothesis": "Log operations with structured context.",
                "body": "Detailed logging instructions.",
                "_salience": 1.5,
            }
        ]

        result = pack_two_tier_context(
            gates=gates,
            advisory=advisory,
            total_budget=2000,
        )

        assert len(result["expressed_gates"]) == 1
        assert len(result["expressed_advisory"]) == 1
        assert result["expressed_gates"][0]["compressed"] is False
        assert result["total_tokens"] <= 2000

    def test_headroom_flows_to_tier2(self):
        """When gates consume only 200 tokens, advisory rules can consume remaining 1800 tokens."""
        gates = [
            {
                "id": "gate-1",
                "type": "gate",
                "enforcement": "gate",
                "hypothesis": "Small gate",
                "body": "Short text",
                "_salience": 5.0,
            }
        ]
        # Create 5 advisory cells, each ~250 tokens
        advisory = [
            {
                "id": f"wall-{i}",
                "type": "wall",
                "hypothesis": f"Advisory rule {i}",
                "body": "word " * 180,  # ~243 tokens each
                "_salience": 2.0 - (i * 0.1),
            }
            for i in range(5)
        ]

        result = pack_two_tier_context(
            gates=gates,
            advisory=advisory,
            total_budget=2000,
        )

        # Should fit multiple advisory cells beyond the default 800 token ceiling
        assert len(result["expressed_gates"]) == 1
        assert len(result["expressed_advisory"]) >= 4

    def test_tier1_oversubscription_drops_tier2(self):
        """When gates exceed 1200 tokens, Tier 2 advisory cells are dropped to 0."""
        # 3 large gates, ~500 tokens each = ~1500 tokens
        gates = [
            {
                "id": f"gate-heavy-{i}",
                "type": "gate",
                "enforcement": "gate",
                "hypothesis": f"Critical security gate {i}",
                "body": "security " * 370,
                "_salience": 5.0,
            }
            for i in range(3)
        ]
        advisory = [
            {
                "id": "wall-advisory",
                "type": "wall",
                "hypothesis": "Advisory rule",
                "body": "Some advice",
                "_salience": 1.0,
            }
        ]

        result = pack_two_tier_context(
            gates=gates,
            advisory=advisory,
            total_budget=2000,
        )

        assert len(result["expressed_advisory"]) == 0
        assert len(result["expressed_gates"]) == 3

    def test_incompressible_gate_guarantee_extreme_pressure(self):
        """When 10 large gates (>3000 tokens) are triggered, NO gates are dropped.

        Overflow gates are compressed into Atomic Invariant Directives.
        """
        gates = [
            {
                "id": f"gate-critical-{i}",
                "type": "gate",
                "enforcement": "gate",
                "hypothesis": f"Must uphold security invariant {i}",
                "prediction": f"Violation causes security failure {i}",
                "target_paths": ["*.py"],
                "body": "long historical context and explanation " * 80,  # ~400 tokens each
                "_salience": 5.0 - (i * 0.05),
            }
            for i in range(10)  # 10 * 400 = ~4000 tokens full fidelity
        ]

        result = pack_two_tier_context(
            gates=gates,
            advisory=[],
            total_budget=2000,
        )

        # Incompressible guarantee: All 10 gates MUST be expressed
        assert len(result["expressed_gates"]) == 10
        # Total tokens must be strictly under total budget
        assert result["total_tokens"] <= 2000
        # At least some gates must be compressed
        compressed_count = sum(1 for g in result["expressed_gates"] if g["compressed"])
        assert compressed_count > 0

    def test_tier2_oversubscription_salience_ranking(self):
        """When advisory cells exceed the advisory budget, higher Salience cells win."""
        gates = []
        advisory = [
            {
                "id": "wall-low-salience",
                "type": "wall",
                "hypothesis": "Low priority advice",
                "body": "word " * 300,
                "_salience": 0.5,
            },
            {
                "id": "wall-high-salience",
                "type": "wall",
                "hypothesis": "High priority advice",
                "body": "word " * 300,
                "_salience": 1.9,
            },
            {
                "id": "wall-medium-salience",
                "type": "wall",
                "hypothesis": "Medium priority advice",
                "body": "word " * 300,
                "_salience": 1.2,
            },
        ]

        result = pack_two_tier_context(
            gates=gates,
            advisory=advisory,
            total_budget=1000,
        )

        expressed_ids = [a["id"] for a in result["expressed_advisory"]]
        assert "wall-high-salience" in expressed_ids
        assert "wall-medium-salience" in expressed_ids
        assert "wall-low-salience" not in expressed_ids

    def test_compress_to_atomic_directive(self):
        """Atomic directive strips verbose prose and keeps invariant + pattern."""
        gate = {
            "id": "gate-no-eval",
            "type": "gate",
            "hypothesis": "Never use eval() or exec() with untrusted user input.",
            "prediction": "Arbitrary code execution vulnerability.",
            "target_paths": ["*.py"],
            "ast_triggers": {"calls": ["eval", "exec"]},
            "body": "Detailed history of CVEs caused by eval in 2024 and examples.",
        }

        directive = compress_to_atomic_directive(gate)
        assert "[GATE: ATOMIC]" in directive
        assert "gate-no-eval" in directive
        assert "Never use eval()" in directive
        assert "Detailed history of CVEs" not in directive

"""Tests for the Cold-Start Safe Salience Scoring Engine (Phase 22 / v0.119.0).

Validates:
1. Exploration prior (S_base = 0.20) guarantees non-zero salience for new cells (no starvation).
2. Untested security gates receive W_gate = 5.0 and S_gate_untested = 1.0 priority.
3. Wilson Lower Bound (WLB_95, z=1.96) scales score with empirical observations.
4. Clamped temporal decay floor (R_min = 0.20) prevents stable invariants from decaying to zero.
5. Monotonic clock skew guard protects against future timestamps.
6. Specificity multipliers reward higher-precision targeting (AST > exact > glob).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import pytest

from aegis_core.scoring import (
    SALIENT_DECAY_FLOOR,
    SALIENT_EXPLORATION_PRIOR,
    SALIENT_GATE_UNTESTED,
    SALIENT_GATE_WEIGHT,
    SALIENT_VACUOLE_WEIGHT,
    SALIENT_WALL_WEIGHT,
    compute_salience,
)


class TestSalienceEngine:
    """Verifies closed-form Salience formula and cold-start guarantees."""

    def test_untested_gate_priority(self):
        """Untested security gates must receive priority salience of 5.0."""
        gate_cell = {
            "id": "gate-security-auth",
            "type": "gate",
            "enforcement": "gate",
            "fitness": {"triggers": 0, "true_positives": 0, "false_positives": 0},
        }
        salience = compute_salience(gate_cell, match_type="glob_match")
        assert salience == pytest.approx(5.0, abs=1e-4)

    def test_untested_wall_prior(self):
        """Untested walls receive W_wall (2.0) * S_base (0.20) = 0.40."""
        wall_cell = {
            "id": "wall-import-guard",
            "type": "wall",
            "enforcement": "wall",
            "fitness": {"triggers": 0, "true_positives": 0},
        }
        salience = compute_salience(wall_cell, match_type="glob_match")
        assert salience == pytest.approx(2.0 * 0.20, abs=1e-4)

    def test_untested_vacuole_cold_start_non_starvation(self):
        """Untested vacuoles receive S_base (0.20) and are never starved (score > 0)."""
        vacuole_cell = {
            "id": "vacuole-heuristic-pattern",
            "type": "vacuole",
            "fitness": {"triggers": 0, "true_positives": 0},
        }
        salience = compute_salience(vacuole_cell, match_type="glob_match")
        assert salience == pytest.approx(0.20, abs=1e-4)
        assert salience > 0.0

    def test_wilson_lower_bound_scaling(self):
        """Verified empirical evidence scales Salience higher than the exploration prior."""
        cell = {
            "id": "wall-verified-pattern",
            "type": "wall",
            "fitness": {"triggers": 100, "true_positives": 98, "false_positives": 2},
        }
        salience = compute_salience(cell, match_type="glob_match")
        # With 98/100, WLB_95 is approximately 0.929
        # Salience = 2.0 * (0.20 + 0.80 * 0.929) * 1.0 * 1.0 ≈ 1.886
        assert salience > 1.8
        assert salience <= 2.0

    def test_temporal_decay_clamped_to_floor(self):
        """Very old cells decay toward R_min = 0.20 but never drop below it."""
        now = datetime.now(timezone.utc)
        ancient_date = (now - timedelta(days=365)).strftime("%Y-%m-%dT%H:%M:%SZ")

        cell = {
            "id": "wall-ancient-rule",
            "type": "wall",
            "fitness": {
                "triggers": 50,
                "true_positives": 45,
                "last_trigger_date": ancient_date,
            },
        }
        salience_ancient = compute_salience(cell, now=now, match_type="glob_match")
        salience_fresh = compute_salience(
            {**cell, "fitness": {**cell["fitness"], "last_trigger_date": now.strftime("%Y-%m-%dT%H:%M:%SZ")}},
            now=now,
            match_type="glob_match",
        )

        assert salience_ancient < salience_fresh
        # Even after a year, R(t) is clamped at >= 0.20
        # Expected minimum = fresh_salience * 0.20
        assert salience_ancient >= (salience_fresh * 0.20) - 1e-4

    def test_clock_skew_protection(self):
        """Future timestamps do not cause negative delta or crash; R(t) evaluates to 1.0."""
        now = datetime.now(timezone.utc)
        future_date = (now + timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ")

        cell = {
            "id": "wall-future-rule",
            "type": "wall",
            "fitness": {
                "triggers": 10,
                "true_positives": 10,
                "last_trigger_date": future_date,
            },
        }
        salience_skew = compute_salience(cell, now=now, match_type="glob_match")
        salience_now = compute_salience(
            {**cell, "fitness": {**cell["fitness"], "last_trigger_date": now.strftime("%Y-%m-%dT%H:%M:%SZ")}},
            now=now,
            match_type="glob_match",
        )
        assert salience_skew == pytest.approx(salience_now, abs=1e-4)

    def test_specificity_multipliers(self):
        """AST matches rank higher than exact paths, which rank higher than globs."""
        cell = {
            "id": "wall-rule",
            "type": "wall",
            "fitness": {"triggers": 10, "true_positives": 9},
        }
        s_ast = compute_salience(cell, match_type="ast_match")
        s_exact = compute_salience(cell, match_type="exact_path")
        s_glob = compute_salience(cell, match_type="glob_match")
        s_base = compute_salience(cell, match_type="base")

        assert s_ast > s_exact > s_glob > s_base
        assert s_ast == pytest.approx(s_glob * 1.5, abs=1e-4)
        assert s_exact == pytest.approx(s_glob * 1.2, abs=1e-4)
        assert s_base == pytest.approx(s_glob * 0.8, abs=1e-4)

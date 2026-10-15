from pathlib import Path
"""Behavioral tests for escaped defect tracking and antifragile bonus.

TDD Phase: Tests written BEFORE implementation changes (Phase 2.0).
Tests against current behavior establish the baseline.
"""
import sys


REPO_ROOT = str(next(p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").exists()))
sys.path.insert(0, REPO_ROOT)

from aegis_sdk.rules import RuleFitness
from aegis_sdk.analysis import antifragile_bonus


class TestAntifragileBonus:
    """Tests for the antifragile bonus calculation."""

    def test_zero_stress_no_bonus(self):
        """Rule with 0 stress events gets no bonus (multiplier = 1.0)."""
        assert antifragile_bonus(0) == 1.0

    def test_one_stress_event(self):
        """One stress event → 1.05 multiplier."""
        assert abs(antifragile_bonus(1) - 1.05) < 0.001

    def test_five_stress_events(self):
        """Five stress events → 1.25 multiplier."""
        assert abs(antifragile_bonus(5) - 1.25) < 0.001

    def test_cap_at_10(self):
        """Bonus caps at 10 events (1.5 multiplier)."""
        assert abs(antifragile_bonus(10) - 1.5) < 0.001
        assert abs(antifragile_bonus(100) - 1.5) < 0.001

    def test_custom_cap(self):
        """Custom cap value is respected."""
        assert abs(antifragile_bonus(5, cap=5) - 1.25) < 0.001
        assert abs(antifragile_bonus(10, cap=5) - 1.25) < 0.001

    def test_cell_fitness_stress_survived_field(self):
        """RuleFitness.stress_survived defaults to 0."""
        f = RuleFitness()
        assert f.stress_survived == 0

    def test_cell_fitness_stress_survived_custom(self):
        """RuleFitness.stress_survived can be set."""
        f = RuleFitness(stress_survived=3)
        bonus = antifragile_bonus(f.stress_survived)
        assert abs(bonus - 1.15) < 0.001



from pathlib import Path
"""Threshold recalibration boundary tests.

Verifies that scoring thresholds for promotion, survival, extinction,
and apoptosis produce correct decisions at boundary values.
"""
import os
import sys

import pytest

REPO_ROOT = str(next(p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").exists()))
sys.path.insert(0, REPO_ROOT)

from aegis_sdk.scoring import bayesian_posterior, laplace_score, _wilson_interval
from aegis_sdk.rules import Cell, CellFitness


class TestLaplaceThresholds:
    """Current Laplace-based thresholds (v0.73 baseline)."""

    def test_promotion_boundary_above(self):
        """Score just above 0.85 with triggers >= 20 → promotable."""
        # tp=19, triggers=20 → (19+1)/(20+2) = 0.909
        cell = Cell(name='t', type='vacuole',
                    fitness=CellFitness(triggers=20, true_positives=19))
        assert cell.is_promotable is True

    def test_promotion_boundary_below(self):
        """Score just below 0.85 → not promotable."""
        # tp=17, triggers=20 → (17+1)/(20+2) = 0.818
        cell = Cell(name='t', type='vacuole',
                    fitness=CellFitness(triggers=20, true_positives=17))
        assert cell.is_promotable is False

    def test_promotion_insufficient_triggers(self):
        """Perfect score but triggers < 20 → not promotable."""
        cell = Cell(name='t', type='vacuole',
                    fitness=CellFitness(triggers=10, true_positives=10))
        assert cell.is_promotable is False

    def test_extinction_boundary_above(self):
        """Score just above 0.15 → not extinct."""
        # tp=2, triggers=10 → (2+1)/(10+2) = 0.25
        cell = Cell(name='t', type='vacuole',
                    fitness=CellFitness(triggers=10, true_positives=2))
        assert cell.is_extinct is False

    def test_extinction_boundary_below(self):
        """Score at 0.15 → extinct."""
        # tp=0, triggers=10 → (0+1)/(10+2) = 0.083
        cell = Cell(name='t', type='vacuole',
                    fitness=CellFitness(triggers=10, true_positives=0))
        assert cell.is_extinct is True

    def test_zero_triggers_neither(self):
        """Zero triggers → neither extinct nor promotable."""
        cell = Cell(name='t', type='vacuole',
                    fitness=CellFitness(triggers=0, true_positives=0))
        assert cell.is_extinct is False
        assert cell.is_promotable is False


class TestWilsonBoundaries:
    """Wilson interval boundary tests for bayesian_posterior."""

    def test_high_confidence_narrows_interval(self):
        """Higher confidence → wider interval."""
        r90 = bayesian_posterior(tp=10, fp=5, confidence=0.90)
        r95 = bayesian_posterior(tp=10, fp=5, confidence=0.95)
        width90 = r90['upper'] - r90['lower']
        width95 = r95['upper'] - r95['lower']
        assert width95 > width90, "95% CI should be wider than 90% CI"

    def test_all_success_high_lower(self):
        """All successes → high lower bound."""
        r = bayesian_posterior(tp=20, fp=0)
        assert r['lower'] > 0.7, f"Expected lower > 0.7, got {r['lower']}"
        assert r['certainty'] == 'high'

    def test_all_failure_low_upper(self):
        """All failures → low upper bound."""
        r = bayesian_posterior(tp=0, fp=20)
        assert r['upper'] < 0.3, f"Expected upper < 0.3, got {r['upper']}"
        assert r['certainty'] == 'high'

    def test_balanced_centered(self):
        """Equal tp and fp → centered around 0.5."""
        r = bayesian_posterior(tp=10, fp=10)
        assert 0.35 < r['mean'] < 0.65
        assert 0.2 < r['lower']
        assert r['upper'] < 0.8

    def test_single_observation_wide(self):
        """n=1 → wide interval."""
        r = bayesian_posterior(tp=1, fp=0)
        width = r['upper'] - r['lower']
        assert width > 0.3, f"Single observation should have wide interval, got {width}"
        assert r['certainty'] == 'low'

    def test_certainty_transitions(self):
        """Verify certainty levels at exact boundaries."""
        assert bayesian_posterior(tp=2, fp=2)['certainty'] == 'low'     # n=4
        assert bayesian_posterior(tp=3, fp=2)['certainty'] == 'medium'  # n=5
        assert bayesian_posterior(tp=10, fp=9)['certainty'] == 'medium' # n=19
        assert bayesian_posterior(tp=10, fp=10)['certainty'] == 'high'  # n=20

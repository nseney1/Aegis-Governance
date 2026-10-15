from pathlib import Path
"""Threshold recalibration boundary tests.

Verifies that scoring thresholds for promotion, survival, extinction,
and apoptosis produce correct decisions at boundary values.
"""
import sys


REPO_ROOT = str(next(p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").exists()))
sys.path.insert(0, REPO_ROOT)

from aegis_core.scoring import bayesian_posterior


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

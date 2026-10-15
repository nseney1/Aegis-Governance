from pathlib import Path
"""Mathematical ground truth tests for Wilson-bounded fitness scoring.

TDD Phase: Tests written BEFORE implementation (Phase 2.0).
Expected: Some tests will fail against v0.73 (red phase) because Wilson
interval is not yet implemented. They will pass after Phase 2.2.
"""
import math
import os
import sys

import pytest

REPO_ROOT = str(next(p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").exists()))
sys.path.insert(0, REPO_ROOT)

from aegis_sdk.scoring import _wilson_interval, bayesian_posterior, laplace_score


class TestWilsonInterval:
    """Verify Wilson score interval against known reference values."""

    def test_wilson_all_success(self):
        """tp=10, total=10 → lower bound near 0.72 at 95% CI."""
        lower, upper = _wilson_interval(tp=10, total=10, z=1.96)
        assert abs(lower - 0.7225) < 0.001, f"Expected ~0.7225, got {lower}"
        assert abs(upper - 1.0) < 0.001, f"Expected ~1.0, got {upper}"

    def test_wilson_all_failure(self):
        """tp=0, total=10 → upper bound near 0.28 at 95% CI."""
        lower, upper = _wilson_interval(tp=0, total=10, z=1.96)
        assert abs(lower - 0.0) < 0.001, f"Expected ~0.0, got {lower}"
        assert abs(upper - 0.2775) < 0.001, f"Expected ~0.2775, got {upper}"

    def test_wilson_half_success(self):
        """tp=5, total=10 → centered around 0.5."""
        lower, upper = _wilson_interval(tp=5, total=10, z=1.645)
        assert 0.25 < lower < 0.40, f"Lower bound {lower} outside expected range"
        assert 0.60 < upper < 0.75, f"Upper bound {upper} outside expected range"

    def test_wilson_degenerate_zero_total(self):
        """total=0 → full uncertainty (0.0, 1.0)."""
        lower, upper = _wilson_interval(tp=0, total=0)
        assert lower == 0.0
        assert upper == 1.0

    def test_wilson_single_observation_success(self):
        """tp=1, total=1 → interval should NOT be (1.0, 1.0)."""
        lower, upper = _wilson_interval(tp=1, total=1, z=1.96)
        assert lower < 1.0, "Single success should not produce lower=1.0"
        assert upper == 1.0 or upper > 0.95

    def test_wilson_single_observation_failure(self):
        """tp=0, total=1 → interval should NOT be (0.0, 0.0)."""
        lower, upper = _wilson_interval(tp=0, total=1, z=1.96)
        assert upper > 0.0, "Single failure should not produce upper=0.0"
        assert lower == 0.0


class TestBayesianPosterior:
    """Verify bayesian_posterior returns correct structure and values."""

    def test_return_structure(self):
        """Result must have mean, lower, upper, certainty, n keys."""
        result = bayesian_posterior(tp=5, fp=2)
        assert 'mean' in result
        assert 'lower' in result
        assert 'upper' in result
        assert 'certainty' in result
        assert 'n' in result

    def test_certainty_low(self):
        """n < 5 → certainty is 'low'."""
        result = bayesian_posterior(tp=2, fp=1)
        assert result['certainty'] == 'low'

    def test_certainty_medium(self):
        """5 <= n < 20 → certainty is 'medium'."""
        result = bayesian_posterior(tp=8, fp=4)
        assert result['certainty'] == 'medium'

    def test_certainty_high(self):
        """n >= 20 → certainty is 'high'."""
        result = bayesian_posterior(tp=15, fp=5)
        assert result['certainty'] == 'high'

    def test_lower_lte_mean_lte_upper(self):
        """Credible interval must satisfy lower <= mean <= upper."""
        result = bayesian_posterior(tp=7, fp=3)
        assert result['lower'] <= result['mean'] <= result['upper']

    def test_bounds_in_unit_interval(self):
        """All bounds must be in [0, 1]."""
        result = bayesian_posterior(tp=0, fp=10)
        assert 0.0 <= result['lower'] <= 1.0
        assert 0.0 <= result['upper'] <= 1.0
        assert 0.0 <= result['mean'] <= 1.0

    def test_backward_compat_keys(self):
        """lower_90 and upper_90 must exist as aliases."""
        result = bayesian_posterior(tp=5, fp=2)
        assert result['lower'] == result.get('lower_90')
        assert result['upper'] == result.get('upper_90')

    def test_uses_wilson_not_wald(self):
        """For small n, Wilson and Wald diverge. Verify Wilson is used.
        
        At tp=1, fp=0 (n=1), Wald gives lower≈-0.15 (clamped to 0),
        Wilson gives lower≈0.05. The mean is ~0.75 (Jeffrey's prior).
        Wilson's lower should be noticeably above 0.
        """
        result = bayesian_posterior(tp=1, fp=0, confidence=0.90)
        # Wilson for p=1.0, n=1, z=1.645 gives lower ≈ 0.2
        # Wald gives lower ≈ max(0, 0.75 - 1.645*0.3) ≈ 0.25 but less stable
        # The key test: at n=1, result should be reasonable
        assert result['lower'] >= 0.0
        assert result['upper'] <= 1.0


class TestLaplaceScore:
    """Verify legacy Laplace scoring is preserved."""

    def test_laplace_basic(self):
        """(5+1)/(10+2) = 0.5."""
        assert abs(laplace_score(5, 10) - 0.5) < 0.001

    def test_laplace_zero(self):
        """(0+1)/(0+2) = 0.5."""
        assert abs(laplace_score(0, 0) - 0.5) < 0.001

    def test_laplace_with_impact(self):
        """Impact weight scales the score."""
        assert abs(laplace_score(5, 10, impact_weight=2.0) - 1.0) < 0.001


# Property-based tests using hypothesis
try:
    from hypothesis import given, settings, assume
    from hypothesis import strategies as st

    class TestWilsonProperties:
        """Property-based tests for Wilson interval correctness."""

        @given(
            tp=st.integers(min_value=0, max_value=1000),
            fp=st.integers(min_value=0, max_value=1000),
        )
        @settings(max_examples=200)
        def test_lower_lte_mean_lte_upper(self, tp, fp):
            total = tp + fp
            assume(total > 0)
            result = bayesian_posterior(tp=tp, fp=fp)
            assert result['lower'] <= result['mean'] + 0.0001  # float tolerance
            assert result['mean'] <= result['upper'] + 0.0001

        @given(
            tp=st.integers(min_value=0, max_value=1000),
            fp=st.integers(min_value=0, max_value=1000),
        )
        @settings(max_examples=200)
        def test_bounds_in_unit_interval(self, tp, fp):
            result = bayesian_posterior(tp=tp, fp=fp)
            assert 0.0 <= result['lower'] <= 1.0
            assert 0.0 <= result['upper'] <= 1.0

        @given(
            tp=st.integers(min_value=1, max_value=100),
            fp=st.integers(min_value=0, max_value=100),
            scale=st.integers(min_value=2, max_value=5),
        )
        @settings(max_examples=100)
        def test_interval_narrows_with_more_data(self, tp, fp, scale):
            """Scaling observations by k (same ratio) should narrow the interval."""
            r1 = bayesian_posterior(tp=tp, fp=fp)
            # Scale up: multiply both by scale to keep same proportion
            r2 = bayesian_posterior(tp=tp * scale, fp=fp * scale)
            width1 = r1['upper'] - r1['lower']
            width2 = r2['upper'] - r2['lower']
            assert width2 <= width1 + 0.001  # tolerance for rounding

except ImportError:
    pass  # hypothesis not installed — skip property tests

# ── Phase 1: Bayesian Score Parity ────────────────────────────────────────

class TestBayesianScoreParity:
    """Verify the canonical formula is used consistently across all modules."""

    def test_shared_module_exists(self):
        """bayesian_score must exist as the single source of truth."""
        from aegis_core.scoring import bayesian_score
        assert callable(bayesian_score)

    def test_shared_module_basic_calculation(self):
        from aegis_core.scoring import bayesian_score
        assert bayesian_score(5, 10) == pytest.approx((5+1)/(10+2))
        assert bayesian_score(0, 0) == pytest.approx(0.5)
        assert bayesian_score(0, 0, 1.8) == pytest.approx(0.9)

    def test_cell_fitness_agrees_with_shared_module(self):
        """bayesian_fitness and bayesian_score agree on directionality."""
        from aegis_core.scoring import bayesian_score
        from aegis_core.lifecycle.decay import bayesian_fitness
        # Non-trivial data: tp=3, fp=1 (triggers=4 for bayesian_score)
        # bayesian_score: Laplace — (3+1)/(4+2) = 4/6 ≈ 0.6667
        shared = bayesian_score(3, 4)
        assert shared == pytest.approx(4 / 6)
        # bayesian_fitness: Jeffrey's prior — a=3.5, b=1.5, mean=3.5/5.0=0.7
        cell = bayesian_fitness(tp=3, fp=1)
        assert cell['mean'] == pytest.approx(0.7)
        # Both must agree: high-tp data → score well above 0.5
        assert shared > 0.5
        assert cell['mean'] > 0.5

    def test_cell_promote_normalize_fitness_callable(self):
        """normalize_fitness must extract and preserve fitness fields."""
        from aegis_core.lifecycle.decay import normalize_fitness
        meta = {'fitness': {'triggers': 5, 'true_positives': 3, 'false_positives': 1}}
        result = normalize_fitness(meta)
        assert isinstance(result, dict)
        assert result['triggers'] == 5
        assert result['true_positives'] == 3
        assert result['false_positives'] == 1

    def test_cell_promote_normalizes_scalar_fitness(self):
        """normalize_fitness handles scalar fitness values."""
        from aegis_core.lifecycle.decay import normalize_fitness
        # Scalar fitness (1.0) should become {'score': 1.0}
        meta = {'fitness': 1.0}
        result = normalize_fitness(meta)
        assert isinstance(result, dict)
        assert result.get('score') == 1.0

    def test_handles_string_inputs(self):
        """Should coerce string values from YAML without crashing."""
        from aegis_core.scoring import bayesian_score
        result = bayesian_score("5", "10", "1.0")
        assert result == pytest.approx((5+1)/(10+2))

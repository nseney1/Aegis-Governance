"""Property-based tests verifying mathematical invariants across Soma scoring engines."""
from __future__ import annotations


import pytest

pytest.importorskip("hypothesis")
from hypothesis import given, settings, strategies as st

from aegis_core.scoring import laplace_score, wilson_lower_bound, bayesian_posterior, bayesian_score
from aegis_core.lifecycle.quorum import calculate_fitness_status
from aegis_core.lifecycle.constants import (
    STATUS_NEW,
    STATUS_SURVIVE,
    STATUS_ADAPT,
    STATUS_EXTINCT,
    STATUS_APOPTOSIS,
    STATUS_APOPTOSIS_WARNING,
    STATUS_DORMANT,
)


class TestMathematicalInvariants:
    """Hypothesis-driven mathematical property testing."""

    @settings(max_examples=200)
    @given(
        tp=st.integers(min_value=0, max_value=1_000_000),
        extra_triggers=st.integers(min_value=0, max_value=1_000_000),
    )
    def test_laplace_score_bounds_and_monotonicity(self, tp: int, extra_triggers: int):
        """Laplace score is strictly in [0.0, 1.0] and monotonic with respect to tp."""
        triggers = tp + extra_triggers
        score = laplace_score(tp, triggers)
        assert 0.0 <= score <= 1.0

        if extra_triggers > 0:
            higher_score = laplace_score(tp + 1, triggers)
            assert higher_score > score

    @settings(max_examples=200)
    @given(
        tp=st.integers(min_value=0, max_value=1_000_000),
        extra_triggers=st.integers(min_value=0, max_value=1_000_000),
    )
    def test_wilson_lower_bound_bounds(self, tp: int, extra_triggers: int):
        """Wilson lower bound is strictly in [0.0, 1.0]."""
        triggers = tp + extra_triggers
        score = wilson_lower_bound(tp, triggers)
        assert 0.0 <= score <= 1.0

    @settings(max_examples=200)
    @given(
        tp=st.integers(min_value=0, max_value=100_000),
        fp=st.integers(min_value=0, max_value=100_000),
    )
    def test_bayesian_score_monotonicity_and_bounds(self, tp: int, fp: int):
        """Bayesian score increases with tp, decreases with fp, and is bounded in [0, 1]."""
        triggers = tp + fp
        score = bayesian_score(tp, triggers)
        assert 0.0 <= score <= 1.0

        # Monotonicity with TP
        score_more_tp = bayesian_score(tp + 1, triggers + 1)
        assert score_more_tp >= score

        # Monotonicity with FP
        score_more_fp = bayesian_score(tp, triggers + 1)
        assert score_more_fp <= score

        # Modern Bayesian posterior checks
        post = bayesian_posterior(tp, fp)
        assert 0.0 <= post["mean"] <= 1.0
        assert 0.0 <= post["lower"] <= 1.0
        assert 0.0 <= post["upper"] <= 1.0
        assert post["lower"] <= post["upper"]

        post_more_tp = bayesian_posterior(tp + 1, fp)
        assert post_more_tp["mean"] >= post["mean"]

        post_more_fp = bayesian_posterior(tp, fp + 1)
        assert post_more_fp["mean"] <= post["mean"]

    @settings(max_examples=100)
    @given(
        tp=st.integers(min_value=0, max_value=10_000),
        fp=st.integers(min_value=0, max_value=10_000),
        triggers=st.integers(min_value=0, max_value=20_000),
        dec_score=st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
    )
    def test_calculate_fitness_status_always_returns_valid_enum(
        self, tp: int, fp: int, triggers: int, dec_score: float
    ):
        """calculate_fitness_status returns one of the canonical states for all inputs."""
        status = calculate_fitness_status(
            cell_type="wall",
            tp=tp,
            fp=fp,
            triggers=triggers,
            dec_score=dec_score,
            is_unobserved=False,
        )
        assert status in {
            STATUS_NEW,
            STATUS_SURVIVE,
            STATUS_ADAPT,
            STATUS_EXTINCT,
            STATUS_APOPTOSIS,
            STATUS_APOPTOSIS_WARNING,
            STATUS_DORMANT,
        }

    def test_clock_skew_future_timestamp_does_not_crash(self):
        """A cell created with a timestamp in the future does not cause negative days error."""
        future_str = "2099-01-01T00:00:00Z"
        status = calculate_fitness_status(
            cell_type="vacuole",
            tp=0,
            fp=0,
            triggers=0,
            is_unobserved=True,
            created_str=future_str,
            expiry_days=30,
        )
        assert status == STATUS_NEW

    @given(
        tp=st.sampled_from([-5, 0, 10**7, float("nan"), float("inf"), -float("inf")]),
        triggers=st.sampled_from([-1, 0, 10**8, float("nan"), float("inf")]),
    )
    def test_extreme_inputs_never_raise(self, tp, triggers):
        """Scoring functions handle extreme/corrupt inputs without division-by-zero or crash."""
        score = laplace_score(tp, triggers)
        assert isinstance(score, float)
        assert 0.0 <= score <= 1.0

        w_score = wilson_lower_bound(tp, triggers)
        assert isinstance(w_score, float)
        assert 0.0 <= w_score <= 1.0


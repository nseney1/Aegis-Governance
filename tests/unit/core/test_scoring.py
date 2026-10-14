"""Unit tests for aegis_core.scoring (Layer 0 Core)."""
from __future__ import annotations

import math
from fractions import Fraction
import pytest

from aegis_core.scoring import (
    _to_num,
    _wilson_interval,
    bayesian_posterior,
    bayesian_score,
    compute_cell_fitness,
    laplace_score,
    wilson_lower_bound,
    calculate_snr,
)


class TestScoringCore:
    def test_to_num_valid_inputs(self):
        assert _to_num(5) == 5.0
        assert _to_num("10") == 10.0
        assert _to_num("3/4") == 0.75
        assert _to_num(3.14) == 3.14

    def test_to_num_invalid_and_edge_inputs(self):
        assert _to_num(None) == 0.0
        assert _to_num(True) == 0.0
        assert _to_num(False) == 0.0
        assert _to_num("invalid") == 0.0
        assert _to_num(float("inf")) == 0.0
        assert _to_num(-5) == 0.0

    def test_wilson_interval_bounds(self):
        low, high = _wilson_interval(0, 0)
        assert low == 0.0
        assert high == 1.0

        low, high = _wilson_interval(10, 10)
        assert 0.0 <= low <= high <= 1.0
        assert low > 0.6  # 10/10 successes has high lower bound

        low, high = _wilson_interval(0, 10)
        assert low == 0.0
        assert high < 0.4

    def test_bayesian_posterior(self):
        res = bayesian_posterior(8, 2, confidence=0.90)
        assert "mean" in res
        assert "lower" in res
        assert "upper" in res
        assert "certainty" in res
        assert res["n"] == 10
        assert 0.0 <= res["lower"] <= res["mean"] <= res["upper"] <= 1.0
        assert res["certainty"] == "medium"

    def test_laplace_score_and_weight(self):
        # 0 tp out of 0 triggers -> (0+1)/(0+2) = 0.5
        assert laplace_score(0, 0) == 0.5
        # 10 tp out of 10 triggers -> (10+1)/(10+2) = 11/12
        assert abs(laplace_score(10, 10) - (11 / 12)) < 1e-6
        # With impact weight
        assert abs(laplace_score(10, 10, impact_weight=2.0) - (11 / 12 * 2.0)) < 1e-6
        # Negative impact weight clamped to 0
        assert laplace_score(10, 10, impact_weight=-1.0) == 0.0

    def test_bayesian_score_alias(self):
        assert bayesian_score(5, 10) == laplace_score(5, 10)

    def test_wilson_lower_bound(self):
        bound = wilson_lower_bound(9, 10)
        assert 0.0 <= bound <= 1.0
        assert bound > 0.5

    def test_compute_cell_fitness(self):
        cell_dict = {
            "fitness": {"score": 0.8, "true_positives": 8, "triggers": 10},
            "impact_weight": 1.0,
        }
        score = compute_cell_fitness(cell_dict)
        assert abs(score - (9 / 12)) < 1e-6

        cell_flat = {
            "true_positives": "5",
            "triggers": "10",
            "impact_weight": "1.5",
        }
        score_flat = compute_cell_fitness(cell_flat)
        assert abs(score_flat - (6 / 12 * 1.5)) < 1e-6

    def test_calculate_snr(self):
        # Balanced tp == fp -> 0.0 dB
        assert calculate_snr(5, 5) == 0.0
        # 10x ratio -> 10.0 dB
        assert calculate_snr(10, 1) == 10.0
        # Infinite SNR (tp > 0, fp == 0) -> None
        assert calculate_snr(5, 0) is None
        # Pure noise (tp == 0, fp > 0) -> -99.0 dB
        assert calculate_snr(0, 5) == -99.0
        # Zero triggers (tp == 0, fp == 0) -> 0.0 dB
        assert calculate_snr(0, 0) == 0.0
        # Float inputs
        assert calculate_snr(10.0, 1.0) == 10.0
        # None inputs
        assert calculate_snr(None, None) == 0.0

    def test_bayesian_posterior_n_type(self):
        res = bayesian_posterior(5.0, 5.0)
        assert isinstance(res["n"], int)
        assert res["n"] == 10

        res_float = bayesian_posterior(5.5, 4.2)
        assert isinstance(res_float["n"], float)
        assert res_float["n"] == 9.7

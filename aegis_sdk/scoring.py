"""Unified scoring module for soma-governance (SDK interface).
Re-exports canonical scoring functions from aegis_core.scoring.
"""
from __future__ import annotations

from aegis_core.scoring import (
    _to_num,
    _wilson_interval,
    bayesian_posterior,
    bayesian_score,
    calculate_composite_fitness,
    calculate_snr,
    compute_cell_fitness,
    laplace_score,
    wilson_lower_bound,
)

__all__ = [
    "_wilson_interval",
    "_to_num",
    "bayesian_posterior",
    "wilson_lower_bound",
    "laplace_score",
    "bayesian_score",
    "compute_cell_fitness",
    "calculate_composite_fitness",
    "calculate_snr",
]

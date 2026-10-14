"""Unit tests for aegis_sdk.analysis utilities."""
from __future__ import annotations

import pytest
from aegis_sdk.analysis import (
    shannon_diversity,
    letter_grade,
    specificity_penalty,
    antifragile_bonus,
)


def test_shannon_diversity():
    # Empty or single-type distribution evaluates to monoculture
    assert shannon_diversity({})["assessment"] == "monoculture"
    assert shannon_diversity({"vacuole": 10})["assessment"] == "monoculture"

    # Balanced distribution evaluates to healthy
    res = shannon_diversity({"vacuole": 10, "wall": 10, "membrane": 10})
    assert res["evenness"] > 0.8
    assert res["assessment"] == "healthy"

    # Imbalanced distribution
    res_imbalanced = shannon_diversity({"vacuole": 100, "wall": 2, "membrane": 1})
    assert res_imbalanced["evenness"] < 0.6


def test_letter_grade():
    assert letter_grade(98.0) == "A+"
    assert letter_grade(94.0) == "A"
    assert letter_grade(91.0) == "A-"
    assert letter_grade(88.0) == "B+"
    assert letter_grade(84.0) == "B"
    assert letter_grade(81.0) == "B-"
    assert letter_grade(78.0) == "C+"
    assert letter_grade(74.0) == "C"
    assert letter_grade(71.0) == "C-"
    assert letter_grade(68.0) == "D+"
    assert letter_grade(62.0) == "D"
    assert letter_grade(50.0) == "F"


def test_specificity_penalty():
    assert specificity_penalty(0.5) == 1.0
    assert specificity_penalty(0.8) == 1.0
    assert specificity_penalty(0.9) == pytest.approx(0.1)
    assert specificity_penalty(1.0) == pytest.approx(0.0)


def test_antifragile_bonus():
    assert antifragile_bonus(0) == 1.0
    assert antifragile_bonus(2) == pytest.approx(1.10)
    assert antifragile_bonus(10) == pytest.approx(1.50)
    # Capped at cap=10
    assert antifragile_bonus(20) == pytest.approx(1.50)

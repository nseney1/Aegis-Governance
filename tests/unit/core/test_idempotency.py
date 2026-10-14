"""Tests verifying strict mathematical and operational idempotency f(f(x)) = f(x)."""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from aegis_core.lifecycle import (
    apply_exponential_decay,
    is_promotable,
    is_extinct,
)
from aegis_core.quarantine import safe_parse_cell_file


class TestIdempotencyContracts:
    """Test suite asserting idempotency contracts across core operations."""

    def test_decay_within_interval_is_strictly_idempotent(self):
        """Calling apply_exponential_decay multiple times within min_interval returns identical state."""
        fitness = {
            "triggers": 100,
            "true_positives": 90,
            "false_positives": 10,
            "last_decay_epoch": int(time.time()),
        }

        first_pass = apply_exponential_decay(fitness, decay_factor=0.9, min_interval_seconds=3600)
        second_pass = apply_exponential_decay(first_pass, decay_factor=0.9, min_interval_seconds=3600)
        third_pass = apply_exponential_decay(second_pass, decay_factor=0.9, min_interval_seconds=3600)

        assert first_pass == fitness
        assert second_pass == fitness
        assert third_pass == fitness

    def test_predicates_are_pure_and_idempotent(self):
        """is_promotable and is_extinct return identical values on repeated invocations."""
        for tp, triggers in [(25, 25), (10, 50), (1, 100), (0, 0)]:
            p1 = is_promotable(tp, triggers)
            p2 = is_promotable(tp, triggers)
            assert p1 == p2

            e1 = is_extinct(tp, triggers)
            e2 = is_extinct(tp, triggers)
            assert e1 == e2

    def test_safe_parse_cell_idempotency_on_healthy_file(self, tmp_path: Path):
        """safe_parse_cell_file is pure and idempotent when reading a healthy file."""
        cell = tmp_path / "cell.md"
        cell.write_text("---\nid: test\ntype: wall\n---\nBody\n", encoding="utf-8")

        m1, b1, s1 = safe_parse_cell_file(cell, workspace=tmp_path)
        m2, b2, s2 = safe_parse_cell_file(cell, workspace=tmp_path)

        assert m1 == m2
        assert b1 == b2
        assert s1 == s2 == "ok"

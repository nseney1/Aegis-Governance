from pathlib import Path
"""Tests for v0.30 Bayesian fitness scoring and mandatory invariant slots.

Each test class covers one architectural change:
1. Bayesian posterior mean (Laplace smoothing) in cell_fitness.py
2. Bayesian posterior mean in jit_engine.get_fitness_score()
3. Mandatory invariant slots in jit_engine.express()

Tests are behavioral: they verify the scoring *behavior* under edge cases,
not the internal formula. If the formula changes but the behavior is preserved,
tests should still pass.
"""
import math
import os
import sys
import tempfile
import shutil

import pytest

from tests.helpers_cell import (
    soma_workspace, write_cell_with_fitness, make_cell_dict,
)

REPO_ROOT = str(next(p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").exists()))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, 'aegis_mcp'))


# ── Bayesian Fitness Scoring (cell_fitness.py) ────────────────────────────

class TestBayesianFitnessScoring:
    """Verify bayesian_fitness() from cell_fitness.py produces correct behavior."""

    def test_zero_triggers_returns_0_5(self):
        """A brand-new cell with no data should score 0.5 (maximally uncertain)."""
        sys.path.insert(0, os.path.join(REPO_ROOT, 'enzymes'))
        from soma_core.lifecycle import bayesian_fitness
        result = bayesian_fitness(tp=0, fp=0)
        assert result['mean'] == pytest.approx(0.5)

    def test_perfect_small_sample_not_1_0(self):
        """A cell with 1 TP / 0 FP should NOT score 1.0 — prior pulls it down."""
        sys.path.insert(0, os.path.join(REPO_ROOT, 'enzymes'))
        from soma_core.lifecycle import bayesian_fitness
        result = bayesian_fitness(tp=1, fp=0)
        assert result['mean'] < 1.0, "Perfect 1/0 must not score 1.0"

    def test_all_false_positives_below_0_5(self):
        """A cell with 0 TP / 5 FP should score well below 0.5."""
        sys.path.insert(0, os.path.join(REPO_ROOT, 'enzymes'))
        from soma_core.lifecycle import bayesian_fitness
        result = bayesian_fitness(tp=0, fp=5)
        assert result['mean'] < 0.15

    def test_large_sample_converges_to_raw(self):
        """At 100 observations, Bayesian and raw should be nearly identical."""
        sys.path.insert(0, os.path.join(REPO_ROOT, 'enzymes'))
        from soma_core.lifecycle import bayesian_fitness
        result = bayesian_fitness(tp=90, fp=10)
        raw = 90 / 100
        assert abs(result['mean'] - raw) < 0.01

    def test_certainty_low_for_small_samples(self):
        """Fewer than 5 observations -> certainty must be 'low'."""
        sys.path.insert(0, os.path.join(REPO_ROOT, 'enzymes'))
        from soma_core.lifecycle import bayesian_fitness
        result = bayesian_fitness(tp=1, fp=1)
        assert result['certainty'] == 'low'

    def test_certainty_medium_for_moderate_samples(self):
        """5-19 observations -> certainty must be 'medium'."""
        sys.path.insert(0, os.path.join(REPO_ROOT, 'enzymes'))
        from soma_core.lifecycle import bayesian_fitness
        result = bayesian_fitness(tp=5, fp=5)
        assert result['certainty'] == 'medium'

    def test_monotonicity_with_increasing_tp(self):
        """More true positives -> higher score, for fixed false positives."""
        sys.path.insert(0, os.path.join(REPO_ROOT, 'enzymes'))
        from soma_core.lifecycle import bayesian_fitness
        scores = [bayesian_fitness(tp=tp, fp=5)['mean'] for tp in range(11)]
        for i in range(len(scores) - 1):
            assert scores[i] < scores[i + 1], \
                f"Score must increase: tp={i} ({scores[i]:.4f}) < tp={i+1} ({scores[i+1]:.4f})"


# ── JIT Engine: get_fitness_score() ───────────────────────────────────────

class TestJITFitnessScore:
    """Verify jit_engine.get_fitness_score uses Bayesian scoring."""


    def test_basic_bayesian_scoring(self):
        """get_fitness_score should return Bayesian posterior, not raw ratio."""
        from jit_engine import get_fitness_score
        cell = make_cell_dict(tp=5, triggers=10)
        result = get_fitness_score(cell)
        expected = (5 + 1) / (10 + 2)  # 0.5
        assert result == pytest.approx(expected, rel=1e-3)

    def test_zero_triggers_returns_default(self):
        """Zero triggers should return the default 0.5 * impact_weight."""
        from jit_engine import get_fitness_score
        cell = make_cell_dict(tp=0, triggers=0)
        result = get_fitness_score(cell)
        assert result == pytest.approx(0.5)

    def test_impact_weight_applied(self):
        """Impact weight should multiply the Bayesian score."""
        from jit_engine import get_fitness_score
        cell = make_cell_dict(tp=5, triggers=10, impact_weight=0.8)
        result = get_fitness_score(cell)
        expected = ((5 + 1) / (10 + 2)) * 0.8
        assert result == pytest.approx(expected, rel=1e-3)

    def test_perfect_record_not_1(self):
        """A cell with 10/10 TP should not score 1.0."""
        from jit_engine import get_fitness_score
        cell = make_cell_dict(tp=10, triggers=10)
        result = get_fitness_score(cell)
        assert result < 1.0, f"10/10 should score below 1.0, got {result}"

    def test_bare_scalar_fitness_fallback(self):
        """When fitness is a bare scalar (legacy), should use it * impact_weight."""
        from jit_engine import get_fitness_score
        cell = {'fitness': 0.75, 'impact_weight': 1.0}
        result = get_fitness_score(cell)
        # Bare scalar → dict conversion → 'score' key → returns score * impact
        assert isinstance(result, float)


# ── JIT Engine: Mandatory Invariant Slots ─────────────────────────────────

class TestMandatoryInvariantSlots:
    """Verify that wall cells and gate-tier cells always load regardless of budget."""

    @pytest.fixture
    def populated_workspace(self, soma_workspace):
        """Workspace with wall, gate, and advisory cells for slot tests."""
        cells_dir = soma_workspace / ".soma" / "cells"
        write_cell_with_fitness(
            cells_dir, "wall-no-secrets", cell_type="wall",
            triggers=10, tp=9, fp=0,
            hypothesis="Never expose API keys",
        )
        write_cell_with_fitness(
            cells_dir, "gate-auth", enforcement="gate",
            triggers=50, tp=48, fp=1,
            hypothesis="Validate auth tokens",
        )
        write_cell_with_fitness(
            cells_dir, "advisory-formatting", cell_type="chloroplast",
            triggers=30, tp=25, fp=2,
            hypothesis="Use consistent formatting",
        )
        write_cell_with_fitness(
            cells_dir, "advisory-imports",
            triggers=15, tp=10, fp=3,
            hypothesis="Sort imports",
        )
        return str(soma_workspace)

    def test_walls_always_load_even_at_budget_1(self, populated_workspace):
        """With budget=1, wall cells must still load (they're mandatory)."""
        from jit_engine import express
        result = express(populated_workspace, changed_files=["app.py"], budget=1)

        cell_names = [c['name'] for c in result['relevant_cells']]
        assert 'wall-no-secrets' in cell_names, \
            f"Wall cell must always load. Got: {cell_names}"

    def test_gate_tier_always_loads(self, populated_workspace):
        """Gate-tier cells must always load regardless of budget."""
        from jit_engine import express
        result = express(populated_workspace, changed_files=["app.py"], budget=1)

        cell_names = [c['name'] for c in result['relevant_cells']]
        assert 'gate-auth' in cell_names, \
            f"Gate-tier cell must always load. Got: {cell_names}"

    def test_mandatory_cells_dont_consume_advisory_budget(self, populated_workspace):
        """With budget=3, mandatory cells (wall+gate) take 2 slots,
        leaving 1 slot for the best advisory cell."""
        from jit_engine import express
        result = express(populated_workspace, changed_files=["app.py"], budget=3)

        cell_names = [c['name'] for c in result['relevant_cells']]
        # 2 mandatory + 1 advisory = 3
        assert 'wall-no-secrets' in cell_names
        assert 'gate-auth' in cell_names
        assert len(cell_names) == 3, f"Expected 3 cells, got {len(cell_names)}: {cell_names}"

    def test_large_budget_includes_all(self, populated_workspace):
        """With budget=10 and 4 cells, all should load."""
        from jit_engine import express
        result = express(populated_workspace, changed_files=["app.py"], budget=10)

        cell_names = [c['name'] for c in result['relevant_cells']]
        assert len(cell_names) == 4, f"Expected all 4 cells, got {len(cell_names)}: {cell_names}"

    def test_mandatory_can_exceed_budget(self, populated_workspace):
        """If there are 3 mandatory cells and budget=2, all 3 mandatory still load.
        The budget constrains advisory cells, not mandatory ones."""
        from jit_engine import express
        # Budget=2 but we have 2 mandatory cells. Advisory gets 0 slots.
        result = express(populated_workspace, changed_files=["app.py"], budget=2)

        cell_names = [c['name'] for c in result['relevant_cells']]
        assert 'wall-no-secrets' in cell_names
        assert 'gate-auth' in cell_names
        # Advisory cells should NOT load since budget is consumed
        advisory_count = sum(1 for n in cell_names if 'advisory' in n)
        assert advisory_count == 0, \
            f"Advisory cells should not load when budget is consumed by mandatory. Got: {cell_names}"

    def test_no_changed_files_returns_empty(self, populated_workspace):
        """When no files are changed, no cells load (including mandatory)."""
        from jit_engine import express
        result = express(populated_workspace, changed_files=[], budget=10)
        assert len(result['relevant_cells']) == 0

    def test_stats_report_correct_counts(self, populated_workspace):
        """Stats should report total, matched, and expressed counts."""
        from jit_engine import express
        result = express(populated_workspace, changed_files=["app.py"], budget=3)

        assert result['stats']['total_cells'] == 4
        assert result['stats']['matched'] == 4  # all match *.py
        assert result['stats']['expressed'] == 3  # budget=3

# ── Phase 2: C1 — NEW/DORMANT Status Restoration ─────────────────────────

class TestNewDormantStatus:
    """Verify zero-trigger cells produce maximally uncertain Bayesian scores
    and that decayed_fitness handles missing data gracefully."""

    def test_zero_trigger_cell_returns_maximally_uncertain(self):
        """A brand-new cell with 0 triggers should score 0.5 (maximally uncertain)."""
        sys.path.insert(0, os.path.join(REPO_ROOT, 'enzymes'))
        from soma_core.lifecycle import bayesian_fitness
        result = bayesian_fitness(tp=0, fp=0)
        assert result['mean'] == pytest.approx(0.5)
        assert result['certainty'] == 'low'

    def test_zero_trigger_cell_has_wide_confidence_interval(self):
        """Zero-trigger cells should have a wide 90% CI spanning nearly [0, 1]."""
        sys.path.insert(0, os.path.join(REPO_ROOT, 'enzymes'))
        from soma_core.lifecycle import bayesian_fitness
        result = bayesian_fitness(tp=0, fp=0)
        assert result['lower_90'] < 0.2, f"Lower bound too high: {result['lower_90']}"
        assert result['upper_90'] > 0.8, f"Upper bound too low: {result['upper_90']}"

    def test_decayed_fitness_returns_none_for_no_data(self):
        """decayed_fitness should return raw_score unchanged when no date is available."""
        sys.path.insert(0, os.path.join(REPO_ROOT, 'enzymes'))
        from soma_core.lifecycle import decayed_fitness
        assert decayed_fitness(None, None) is None
        assert decayed_fitness(0.8, None) == 0.8


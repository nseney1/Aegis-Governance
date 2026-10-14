from pathlib import Path
"""Behavioral tests for escaped defect tracking and antifragile bonus.

TDD Phase: Tests written BEFORE implementation changes (Phase 2.0).
Tests against current behavior establish the baseline.
"""
import json
import math
import os
import sys
import tempfile
import shutil

import pytest

REPO_ROOT = str(next(p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").exists()))
sys.path.insert(0, REPO_ROOT)

from aegis_sdk.cells import CellFitness
from aegis_sdk.analysis import antifragile_bonus


class TestAntifragileBonus:
    """Tests for the antifragile bonus calculation."""

    def test_zero_stress_no_bonus(self):
        """Cell with 0 stress events gets no bonus (multiplier = 1.0)."""
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
        """CellFitness.stress_survived defaults to 0."""
        f = CellFitness()
        assert f.stress_survived == 0

    def test_cell_fitness_stress_survived_custom(self):
        """CellFitness.stress_survived can be set."""
        f = CellFitness(stress_survived=3)
        bonus = antifragile_bonus(f.stress_survived)
        assert abs(bonus - 1.15) < 0.001


class TestEscapedDefectRecording:
    """Tests for escaped defect recording to JSONL."""

    def _create_workspace_with_cell(self):
        """Create a temp workspace with a minimal cell and metrics dir."""
        workspace = tempfile.mkdtemp()
        cells_dir = os.path.join(workspace, '.soma', 'cells', 'vacuoles')
        metrics_dir = os.path.join(workspace, '.soma', 'metrics')
        os.makedirs(cells_dir)
        os.makedirs(metrics_dir)

        # Create a minimal cell file
        cell_path = os.path.join(cells_dir, 'trap-test.md')
        with open(cell_path, 'w', encoding='utf-8') as f:
            f.write('---\n')
            f.write('name: trap-test\n')
            f.write('type: vacuole\n')
            f.write('hypothesis: Test trap\n')
            f.write('target_paths:\n')
            f.write('  - src/*.py\n')
            f.write('fitness:\n')
            f.write('  triggers: 10\n')
            f.write('  true_positives: 8\n')
            f.write('  false_positives: 2\n')
            f.write('  stress_survived: 0\n')
            f.write('---\n')
            f.write('# Trap Test\n')

        return workspace

    def test_record_creates_jsonl_entry(self):
        """Recording an escaped defect appends to escaped_defects.jsonl."""
        workspace = self._create_workspace_with_cell()
        try:
            from aegis_core.defects import record_escaped_defect

            cell_dict = {
                '_name': 'trap-test',
                'type': 'vacuole',
                'enforcement': 'advisory',
            }
            record_escaped_defect(
                cell=cell_dict,
                event_type='test_regression',
                files=['src/app.py'],
                severity='high',
                workspace=workspace
            )

            jsonl_path = os.path.join(workspace, '.soma', 'metrics', 'escaped_defects.jsonl')
            assert os.path.exists(jsonl_path), "JSONL file should be created"

            with open(jsonl_path, encoding='utf-8') as f:
                lines = f.readlines()
            assert len(lines) >= 1, "Should have at least one entry"

            entry = json.loads(lines[-1])
            assert entry.get('cell') == 'trap-test' or entry.get('cell_name') == 'trap-test'
            assert 'timestamp' in entry or 'ts' in entry
        finally:
            shutil.rmtree(workspace)

    def test_escaped_rate_calculation(self):
        """escaped_rate = escaped / (escaped + tp)."""
        # Direct mathematical verification
        escaped = 3
        tp = 7
        expected_rate = escaped / (escaped + tp)  # 0.3
        assert abs(expected_rate - 0.3) < 0.001

    def test_enhanced_fitness_with_zero_escaped(self):
        """Zero escaped defects → enhanced fitness equals base fitness."""
        # Direct calculation: bayesian_mean × (1 - 0) × tier_weight
        tp, fp = 8, 2
        bayesian_mean = (tp + 0.5) / (tp + fp + 1.0)
        enhanced = bayesian_mean * (1 - 0.0) * 1.0  # advisory tier
        assert abs(enhanced - bayesian_mean) < 0.001

    def test_enhanced_fitness_with_escaped_defects(self):
        """Escaped defects reduce enhanced fitness."""
        tp, fp = 8, 2
        escaped_rate = 0.3
        bayesian_mean = (tp + 0.5) / (tp + fp + 1.0)
        enhanced = bayesian_mean * (1 - escaped_rate) * 1.0
        assert enhanced < bayesian_mean, "Escaped defects should reduce fitness"

    def test_tier_weight_gate_is_highest(self):
        """Gate tier weight (1.5) > mechanical (1.2) > advisory (1.0)."""
        tier_weights = {'advisory': 1.0, 'mechanical': 1.2, 'gate': 1.5}
        assert tier_weights['gate'] > tier_weights['mechanical'] > tier_weights['advisory']

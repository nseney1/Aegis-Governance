from pathlib import Path
"""Behavioral tests for the soma_sdk public API.

TDD Phase: Tests written BEFORE implementation (Phase 2.0).
Tests against current behavior establish the baseline.
Tests for new features (parse_cell_file, CellPathTraversalError) are
skipped until their respective Phase 2 sub-phases implement them.
"""
import math
import os
import sys
import tempfile
import textwrap

import pytest
from aegis_core.yaml import dump_frontmatter, parse_yaml_subset

REPO_ROOT = str(next(p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").exists()))
sys.path.insert(0, REPO_ROOT)

from aegis_sdk.cells import Cell, CellFitness, parse_cell_file, write_cell_frontmatter
from aegis_sdk.errors import CellPathTraversalError, CellParseError


class TestCellFitnessBaseline:
    """Tests against CURRENT CellFitness behavior (v0.73 baseline)."""

    def test_raw_score_basic(self):
        f = CellFitness(triggers=10, true_positives=7)
        assert f.raw_score == 0.7

    def test_raw_score_zero_triggers(self):
        f = CellFitness(triggers=0, true_positives=0)
        assert f.raw_score is None

    def test_snr_db_positive(self):
        f = CellFitness(triggers=10, true_positives=8, false_positives=2)
        expected = round(10 * math.log10(8 / 2), 1)
        assert f.snr_db == expected

    def test_snr_db_no_fp(self):
        """tp > 0 and fp == 0 → None (infinite SNR)."""
        f = CellFitness(triggers=5, true_positives=5, false_positives=0)
        assert f.snr_db is None

    def test_snr_db_no_tp(self):
        """tp == 0 and fp > 0 → -99.0 (pure noise, zero signal, JSON-safe)."""
        f = CellFitness(triggers=5, true_positives=0, false_positives=5)
        assert f.snr_db == -99.0

    def test_snr_db_zero_triggers(self):
        """tp == 0 and fp == 0 → 0.0 (baseline/undefined)."""
        f = CellFitness(triggers=0, true_positives=0, false_positives=0)
        assert f.snr_db == 0.0

    def test_bayesian_returns_dict(self):
        f = CellFitness(triggers=10, true_positives=7, false_positives=3)
        result = f.bayesian()
        assert isinstance(result, dict)
        assert 'mean' in result
        assert 'lower' in result
        assert 'upper' in result
        assert 'certainty' in result

    def test_bayesian_ordering(self):
        f = CellFitness(triggers=20, true_positives=15, false_positives=5)
        result = f.bayesian()
        assert result['lower'] <= result['mean'] <= result['upper']


class TestCellBaseline:
    """Tests against CURRENT Cell behavior (v0.73 baseline)."""

    def test_is_wall(self):
        c = Cell(name='test', type='wall')
        assert c.is_wall is True

    def test_is_not_wall(self):
        c = Cell(name='test', type='vacuole')
        assert c.is_wall is False

    def test_is_extinct_high_fitness(self):
        """Cell with good fitness is NOT extinct."""
        c = Cell(name='test', type='vacuole',
                 fitness=CellFitness(triggers=20, true_positives=18))
        assert c.is_extinct is False

    def test_is_extinct_low_fitness(self):
        """Cell with very low fitness IS extinct."""
        c = Cell(name='test', type='vacuole',
                 fitness=CellFitness(triggers=20, true_positives=1))
        assert c.is_extinct is True

    def test_is_extinct_zero_triggers(self):
        """Cell with zero triggers is NOT extinct (no data)."""
        c = Cell(name='test', type='vacuole',
                 fitness=CellFitness(triggers=0, true_positives=0))
        assert c.is_extinct is False

    def test_is_promotable_high_fitness(self):
        """Cell with score > 0.85 AND triggers >= 20 is promotable."""
        c = Cell(name='test', type='vacuole',
                 fitness=CellFitness(triggers=20, true_positives=19))
        assert c.is_promotable is True

    def test_is_promotable_insufficient_triggers(self):
        """Cell with good score but triggers < 20 is NOT promotable."""
        c = Cell(name='test', type='vacuole',
                 fitness=CellFitness(triggers=5, true_positives=5))
        assert c.is_promotable is False

    def test_is_promotable_low_score(self):
        """Cell with enough triggers but low score is NOT promotable."""
        c = Cell(name='test', type='vacuole',
                 fitness=CellFitness(triggers=20, true_positives=10))
        assert c.is_promotable is False

    def test_is_promotable_with_age(self):
        """is_promotable_with_age validates minimum age in days."""
        from datetime import datetime, timezone, timedelta
        c = Cell(name='test', type='vacuole',
                 fitness=CellFitness(triggers=20, true_positives=19))
        c.created_date = datetime.now(timezone.utc) - timedelta(days=10)
        assert c.is_promotable_with_age(min_age_days=30) is False
        assert c.is_promotable_with_age(min_age_days=5) is True

    def test_cell_fitness_yaml_roundtrip(self):
        """CellFitness data survives YAML serialize → deserialize."""
        original = CellFitness(
            triggers=15, true_positives=12,
            false_positives=3, score=0.8, stress_survived=2
        )
        data = {
            'triggers': original.triggers,
            'true_positives': original.true_positives,
            'false_positives': original.false_positives,
            'score': original.score,
            'stress_survived': original.stress_survived,
        }
        yaml_str = dump_frontmatter(data)
        loaded = parse_yaml_subset(yaml_str)
        restored = CellFitness(**loaded)
        assert restored.triggers == original.triggers
        assert restored.true_positives == original.true_positives
        assert restored.false_positives == original.false_positives
        assert restored.score == original.score
        assert restored.stress_survived == original.stress_survived


class TestParseCellFile:
    """Tests for parse_cell_file — Phase 2.1 deliverable."""

    def test_parse_valid_cell(self):
        """Valid cell file returns (frontmatter_dict, body_text)."""
        with tempfile.NamedTemporaryFile(
            mode='w', suffix='.md', delete=False, encoding='utf-8'
        ) as f:
            f.write(textwrap.dedent("""\
                ---
                name: test-cell
                type: vacuole
                hypothesis: Test hypothesis
                target_paths:
                  - src/*.py
                ---
                # Test Cell Body
                This is the body.
            """))
            f.flush()
            frontmatter, body = parse_cell_file(f.name)
            assert frontmatter['name'] == 'test-cell'
            assert frontmatter['type'] == 'vacuole'
            assert 'src/*.py' in frontmatter['target_paths']
            assert 'Test Cell Body' in body
        os.unlink(f.name)

    def test_parse_roundtrip(self):
        """parse → write → parse produces identical output."""
        with tempfile.NamedTemporaryFile(
            mode='w', suffix='.md', delete=False, encoding='utf-8'
        ) as f:
            f.write(textwrap.dedent("""\
                ---
                name: roundtrip-test
                type: wall
                hypothesis: Roundtrip
                ---
                Body text here.
            """))
            f.flush()
            fm1, body1 = parse_cell_file(f.name)
            write_cell_frontmatter(f.name, fm1, body1)
            fm2, body2 = parse_cell_file(f.name)
            assert fm1 == fm2
            assert body1.strip() == body2.strip()
        os.unlink(f.name)

    def test_parse_no_frontmatter_raises(self):
        """File without --- frontmatter raises CellParseError."""
        with tempfile.NamedTemporaryFile(
            mode='w', suffix='.md', delete=False, encoding='utf-8'
        ) as f:
            f.write('No frontmatter here.')
            f.flush()
            with pytest.raises(CellParseError):
                parse_cell_file(f.name)
        os.unlink(f.name)


class TestPathTraversal:
    """Tests for path traversal guards — Phase 2.3 deliverable."""

    def test_load_cell_path_traversal(self):
        """Attempting to load '../etc/passwd' raises CellPathTraversalError."""
        with pytest.raises(CellPathTraversalError):
            # This function will be added to aegis_sdk.cells
            from aegis_sdk.cells import load_cell
            load_cell('../etc/passwd')

    def test_load_cell_absolute_path_traversal(self):
        """Attempting to load '/etc/passwd' raises CellPathTraversalError."""
        with pytest.raises(CellPathTraversalError):
            from aegis_sdk.cells import load_cell
            load_cell('/etc/passwd')

def test_load_cell_uses_created_field(tmp_path):
    """load_cell must read 'created' field from cell frontmatter."""
    from aegis_sdk.cells import load_cell
    cell_file = tmp_path / ".aegis" / "rules" / "vacuoles" / "created-test.md"
    cell_file.parent.mkdir(parents=True, exist_ok=True)
    cell_file.write_text("""---
id: created-test
type: vacuole
hypothesis: test
created: "2025-01-01T00:00:00Z"
---
body
""", encoding="utf-8")
    cell = load_cell("created-test", cells_dir=str(tmp_path / ".aegis" / "rules"))
    assert cell.created_date == "2025-01-01T00:00:00Z" or getattr(cell.created_date, "year", None) == 2025

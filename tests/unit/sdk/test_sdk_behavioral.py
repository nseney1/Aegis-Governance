from pathlib import Path
"""Behavioral tests for the soma_sdk public API.

TDD Phase: Tests written BEFORE implementation (Phase 2.0).
Tests against current behavior establish the baseline.
Tests for new features (parse_rule_file, RulePathTraversalError) are
skipped until their respective Phase 2 sub-phases implement them.
"""
import math
import os
import sys
import tempfile
import textwrap

import pytest
from aegis_core.yaml_engine.serializer import dump_frontmatter
from aegis_core.yaml_engine.parser import parse_yaml_subset

REPO_ROOT = str(next(p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").exists()))
sys.path.insert(0, REPO_ROOT)

from aegis_sdk.rules import Rule, RuleFitness, parse_rule_file, write_rule_frontmatter
from aegis_sdk.errors import RulePathTraversalError, RuleParseError


class TestCellFitnessBaseline:
    """Tests against CURRENT RuleFitness behavior (v0.73 baseline)."""

    def test_raw_score_basic(self):
        f = RuleFitness(triggers=10, true_positives=7)
        assert f.raw_score == 0.7

    def test_raw_score_zero_triggers(self):
        f = RuleFitness(triggers=0, true_positives=0)
        assert f.raw_score is None

    def test_snr_db_positive(self):
        f = RuleFitness(triggers=10, true_positives=8, false_positives=2)
        expected = round(10 * math.log10(8 / 2), 1)
        assert f.snr_db == expected

    def test_snr_db_no_fp(self):
        """tp > 0 and fp == 0 → None (infinite SNR)."""
        f = RuleFitness(triggers=5, true_positives=5, false_positives=0)
        assert f.snr_db is None

    def test_snr_db_no_tp(self):
        """tp == 0 and fp > 0 → -99.0 (pure noise, zero signal, JSON-safe)."""
        f = RuleFitness(triggers=5, true_positives=0, false_positives=5)
        assert f.snr_db == -99.0

    def test_snr_db_zero_triggers(self):
        """tp == 0 and fp == 0 → 0.0 (baseline/undefined)."""
        f = RuleFitness(triggers=0, true_positives=0, false_positives=0)
        assert f.snr_db == 0.0

    def test_bayesian_returns_dict(self):
        f = RuleFitness(triggers=10, true_positives=7, false_positives=3)
        result = f.bayesian()
        assert isinstance(result, dict)
        assert 'mean' in result
        assert 'lower' in result
        assert 'upper' in result
        assert 'certainty' in result

    def test_bayesian_ordering(self):
        f = RuleFitness(triggers=20, true_positives=15, false_positives=5)
        result = f.bayesian()
        assert result['lower'] <= result['mean'] <= result['upper']


class TestCellBaseline:
    """Tests against CURRENT Rule behavior (v0.73 baseline)."""

    def test_is_wall(self):
        c = Rule(name='test', type='wall')
        assert c.is_wall is True

    def test_is_not_wall(self):
        c = Rule(name='test', type='vacuole')
        assert c.is_wall is False

    def test_is_extinct_high_fitness(self):
        """Rule with good fitness is NOT extinct."""
        c = Rule(name='test', type='vacuole',
                 fitness=RuleFitness(triggers=20, true_positives=18))
        assert c.is_extinct is False

    def test_is_extinct_low_fitness(self):
        """Rule with very low fitness IS extinct."""
        c = Rule(name='test', type='vacuole',
                 fitness=RuleFitness(triggers=20, true_positives=1))
        assert c.is_extinct is True

    def test_is_extinct_zero_triggers(self):
        """Rule with zero triggers is NOT extinct (no data)."""
        c = Rule(name='test', type='vacuole',
                 fitness=RuleFitness(triggers=0, true_positives=0))
        assert c.is_extinct is False

    def test_is_promotable_high_fitness(self):
        """Rule with score > 0.85 AND triggers >= 20 is promotable."""
        c = Rule(name='test', type='vacuole',
                 fitness=RuleFitness(triggers=20, true_positives=19))
        assert c.is_promotable is True

    def test_is_promotable_insufficient_triggers(self):
        """Rule with good score but triggers < 20 is NOT promotable."""
        c = Rule(name='test', type='vacuole',
                 fitness=RuleFitness(triggers=5, true_positives=5))
        assert c.is_promotable is False

    def test_is_promotable_low_score(self):
        """Rule with enough triggers but low score is NOT promotable."""
        c = Rule(name='test', type='vacuole',
                 fitness=RuleFitness(triggers=20, true_positives=10))
        assert c.is_promotable is False

    def test_is_promotable_with_age(self):
        """is_promotable_with_age validates minimum age in days."""
        from datetime import datetime, timezone, timedelta
        c = Rule(name='test', type='vacuole',
                 fitness=RuleFitness(triggers=20, true_positives=19))
        c.created_date = datetime.now(timezone.utc) - timedelta(days=10)
        assert c.is_promotable_with_age(min_age_days=30) is False
        assert c.is_promotable_with_age(min_age_days=5) is True

    def test_cell_fitness_yaml_roundtrip(self):
        """RuleFitness data survives YAML serialize → deserialize."""
        original = RuleFitness(
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
        restored = RuleFitness(**loaded)
        assert restored.triggers == original.triggers
        assert restored.true_positives == original.true_positives
        assert restored.false_positives == original.false_positives
        assert restored.score == original.score
        assert restored.stress_survived == original.stress_survived


class TestParseCellFile:
    """Tests for parse_rule_file — Phase 2.1 deliverable."""

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
                # Test Rule Body
                This is the body.
            """))
            f.flush()
            frontmatter, body = parse_rule_file(f.name)
            assert frontmatter['name'] == 'test-cell'
            assert frontmatter['type'] == 'vacuole'
            assert 'src/*.py' in frontmatter['target_paths']
            assert 'Test Rule Body' in body
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
            fm1, body1 = parse_rule_file(f.name)
            write_rule_frontmatter(f.name, fm1, body1)
            fm2, body2 = parse_rule_file(f.name)
            assert fm1 == fm2
            assert body1.strip() == body2.strip()
        os.unlink(f.name)

    def test_parse_no_frontmatter_raises(self):
        """File without --- frontmatter raises RuleParseError."""
        with tempfile.NamedTemporaryFile(
            mode='w', suffix='.md', delete=False, encoding='utf-8'
        ) as f:
            f.write('No frontmatter here.')
            f.flush()
            with pytest.raises(RuleParseError):
                parse_rule_file(f.name)
        os.unlink(f.name)


class TestPathTraversal:
    """Tests for path traversal guards — Phase 2.3 deliverable."""

    def test_load_cell_path_traversal(self):
        """Attempting to load '../etc/passwd' raises RulePathTraversalError."""
        with pytest.raises(RulePathTraversalError):
            # This function will be added to aegis_sdk.rules
            from aegis_sdk.rules import load_rule
            load_rule('../etc/passwd')

    def test_load_cell_absolute_path_traversal(self):
        """Attempting to load '/etc/passwd' raises RulePathTraversalError."""
        with pytest.raises(RulePathTraversalError):
            from aegis_sdk.rules import load_rule
            load_rule('/etc/passwd')

def test_load_cell_uses_created_field(tmp_path):
    """load_rule must read 'created' field from cell frontmatter."""
    from aegis_sdk.rules import load_rule
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
    cell = load_rule("created-test", cells_dir=str(tmp_path / ".aegis" / "rules"))
    assert cell.created_date == "2025-01-01T00:00:00Z" or getattr(cell.created_date, "year", None) == 2025

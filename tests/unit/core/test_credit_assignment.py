from pathlib import Path
"""Behavioral tests for Phase 3.1 credit assignment.

Tests scope-narrowed per-file credit distribution, fractional exactness,
and signal provenance.
"""
import sys

REPO_ROOT = str(next(p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").exists()))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)




def _make_cell_dict(name, target_paths):
    """Create a triggered-cell dict matching match_cells_to_changes output."""
    return {
        'id': name,
        '_name': name,
        '_path': f'/tmp/{name}.md',
        'target_paths': target_paths,
    }


class TestScopeNarrowing:
    """Credit only flows to cells whose target_paths match specific changed files."""

    def test_cell_matching_tests_gets_no_credit_for_src(self):
        from aegis_core.outcomes.fitness import compute_credit_weights
        cells = [_make_cell_dict('c-tests', ['tests/*.py'])]
        weights = compute_credit_weights(cells, ['src/foo.py'])
        assert weights['c-tests'] == 0.0

    def test_cell_matching_src_gets_credit_for_src(self):
        from aegis_core.outcomes.fitness import compute_credit_weights
        cells = [_make_cell_dict('c-src', ['src/*.py'])]
        weights = compute_credit_weights(cells, ['src/foo.py'])
        assert weights['c-src'] == 1.0

    def test_cell_matching_nothing_gets_zero_credit(self):
        from aegis_core.outcomes.fitness import compute_credit_weights
        cells = [_make_cell_dict('c-docs', ['docs/*.md'])]
        weights = compute_credit_weights(cells, ['src/foo.py'])
        assert weights['c-docs'] == 0.0


class TestCreditConservation:
    """Per-file credit must sum to exactly 1.0."""

    def test_three_cells_same_file_get_one_third_each(self):
        from aegis_core.outcomes.fitness import compute_credit_weights
        cells = [
            _make_cell_dict('a', ['src/*.py']),
            _make_cell_dict('b', ['src/*.py']),
            _make_cell_dict('c', ['src/*.py']),
        ]
        weights = compute_credit_weights(cells, ['src/foo.py'])
        for name in ['a', 'b', 'c']:
            assert abs(weights[name] - 1 / 3) < 1e-9

    def test_one_cell_unique_file_gets_full_credit(self):
        from aegis_core.outcomes.fitness import compute_credit_weights
        cells = [
            _make_cell_dict('sole', ['src/*.py']),
            _make_cell_dict('other', ['tests/*.py']),
        ]
        weights = compute_credit_weights(cells, ['src/foo.py'])
        assert weights['sole'] == 1.0
        assert weights['other'] == 0.0

    def test_per_file_credit_sums_to_one(self):
        from aegis_core.outcomes.fitness import compute_credit_weights
        cells = [
            _make_cell_dict('x', ['src/*.py']),
            _make_cell_dict('y', ['src/*.py']),
            _make_cell_dict('z', ['src/*.py', 'tests/*.py']),
        ]
        weights = compute_credit_weights(cells, ['src/bar.py'])
        total = sum(weights[n] for n in ['x', 'y', 'z'])
        assert abs(total - 1.0) < 1e-9

    def test_five_cells_same_file_get_one_fifth_each(self):
        from aegis_core.outcomes.fitness import compute_credit_weights
        cells = [_make_cell_dict(f'c{i}', ['src/*.py']) for i in range(5)]
        weights = compute_credit_weights(cells, ['src/foo.py'])
        for i in range(5):
            assert abs(weights[f'c{i}'] - 0.2) < 1e-9



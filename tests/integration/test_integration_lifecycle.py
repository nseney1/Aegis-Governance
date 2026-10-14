from pathlib import Path
"""Integration test: end-to-end cell lifecycle.

Verifies the complete chain: create cell → parse → compute fitness →
check promotion/extinction status.
"""
import os
import sys
import tempfile
import shutil

import pytest

REPO_ROOT = str(next(p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").exists()))
sys.path.insert(0, REPO_ROOT)

from aegis_sdk.cells import (
    Cell, CellFitness, parse_cell_file, write_cell_frontmatter, load_cell
)
from aegis_sdk.scoring import bayesian_posterior, laplace_score
from aegis_sdk.errors import CellNotFoundError, CellParseError, CellPathTraversalError


class TestCellLifecycle:
    """End-to-end cell lifecycle."""

    def _create_cell_workspace(self, cell_name, cell_type, hypothesis,
                                target_paths, fitness_data=None):
        """Create a temp workspace with a single cell."""
        workspace = tempfile.mkdtemp()
        subdir = 'walls' if cell_type == 'wall' else 'vacuoles'
        cells_dir = os.path.join(workspace, '.aegis', "rules", subdir)
        os.makedirs(cells_dir)

        frontmatter = {
            'name': cell_name,
            'type': cell_type,
            'hypothesis': hypothesis,
            'target_paths': target_paths,
        }
        if fitness_data:
            frontmatter['fitness'] = fitness_data

        filepath = os.path.join(cells_dir, f'{cell_name}.md')
        write_cell_frontmatter(filepath, frontmatter, f'# {cell_name}\nBody text.\n')
        return workspace, filepath

    def test_create_parse_roundtrip(self):
        """write_cell_frontmatter → parse_cell_file produces identical data."""
        workspace, filepath = self._create_cell_workspace(
            'test-lifecycle', 'vacuole', 'Test hypothesis', ['src/*.py']
        )
        try:
            fm, body = parse_cell_file(filepath)
            assert fm['name'] == 'test-lifecycle'
            assert fm['type'] == 'vacuole'
            assert fm['hypothesis'] == 'Test hypothesis'
            assert 'src/*.py' in fm['target_paths']
            assert 'Body text.' in body
        finally:
            shutil.rmtree(workspace)

    def test_load_cell_from_workspace(self):
        """load_cell finds and loads a cell by ID."""
        workspace, filepath = self._create_cell_workspace(
            'loadable-cell', 'wall', 'Loadable', ['lib/*.py'],
            fitness_data={'triggers': 10, 'true_positives': 8, 'false_positives': 2}
        )
        try:
            cells_dir = os.path.join(workspace, '.aegis', "rules")
            cell = load_cell('loadable-cell', cells_dir=cells_dir)
            assert cell.name == 'loadable-cell'
            assert cell.type == 'wall'
            assert cell.is_wall is True
            assert cell.fitness.triggers == 10
            assert cell.fitness.true_positives == 8
        finally:
            shutil.rmtree(workspace)

    def test_cell_not_found(self):
        """load_cell raises CellNotFoundError for nonexistent cell."""
        workspace = tempfile.mkdtemp()
        cells_dir = os.path.join(workspace, '.aegis', "rules")
        os.makedirs(cells_dir)
        try:
            with pytest.raises(CellNotFoundError):
                load_cell('nonexistent', cells_dir=cells_dir)
        finally:
            shutil.rmtree(workspace)

    def test_fitness_scoring_chain(self):
        """Cell fitness → laplace_score → bayesian_posterior chain."""
        f = CellFitness(triggers=30, true_positives=25, false_positives=5)
        # Laplace score
        ls = laplace_score(f.true_positives, f.triggers)
        assert 0.7 < ls < 0.9
        # Bayesian posterior
        bp = bayesian_posterior(f.true_positives, f.false_positives)
        assert bp['certainty'] == 'high'  # n=30 >= 20
        assert bp['lower'] <= bp['mean'] <= bp['upper']
        assert 0 <= bp['lower'] <= 1

    def test_promotion_lifecycle(self):
        """Cell with high fitness is promotable."""
        cell = Cell(
            name='strong-cell', type='vacuole',
            fitness=CellFitness(triggers=25, true_positives=24, false_positives=1)
        )
        assert cell.is_promotable is True
        assert cell.is_extinct is False

    def test_extinction_lifecycle(self):
        """Cell with poor fitness is extinct."""
        cell = Cell(
            name='weak-cell', type='vacuole',
            fitness=CellFitness(triggers=20, true_positives=1, false_positives=19)
        )
        assert cell.is_extinct is True
        assert cell.is_promotable is False

    def test_path_traversal_blocked(self):
        """Path traversal in cell_id is blocked."""
        with pytest.raises(CellPathTraversalError):
            load_cell('../../../etc/passwd')
        with pytest.raises(CellPathTraversalError):
            load_cell('/etc/passwd')

    def test_write_then_load_preserves_fitness(self):
        """Write cell with fitness → load → fitness values match."""
        workspace, filepath = self._create_cell_workspace(
            'fitness-roundtrip', 'vacuole', 'Roundtrip test', ['*.py'],
            fitness_data={
                'triggers': 50, 'true_positives': 40,
                'false_positives': 10, 'stress_survived': 3
            }
        )
        try:
            cells_dir = os.path.join(workspace, '.aegis', "rules")
            cell = load_cell('fitness-roundtrip', cells_dir=cells_dir)
            assert cell.fitness.triggers == 50
            assert cell.fitness.true_positives == 40
            assert cell.fitness.false_positives == 10
            assert cell.fitness.stress_survived == 3
        finally:
            shutil.rmtree(workspace)

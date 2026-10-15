from pathlib import Path
"""Behavioral tests for outcome_engine.py — signal-in/fitness-out interface.

Tests match_cells_to_changes, compute_fitness_signals, and update_cell_fitness.

NOTE: outcome_engine.py has bare imports (soma_resolve) that require enzymes/ on
sys.path. We use lazy imports inside test methods to avoid collection errors.
"""
import os
import sys
from aegis_core.yaml import dump_frontmatter

REPO_ROOT = str(next(p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").exists()))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)



def _make_cell(workspace, cell_id, target_paths, cell_type='vacuole', fitness=None):
    """Create a minimal valid cell file in the workspace."""
    type_dir = {
        'vacuole': 'vacuoles', 'wall': 'walls', 'membrane': 'membranes',
    }.get(cell_type, 'vacuoles')
    cells_dir = os.path.join(workspace, '.aegis', "rules", type_dir)
    os.makedirs(cells_dir, exist_ok=True)
    fm = {
        'id': cell_id,
        'type': cell_type,
        'target_paths': target_paths,
        'hypothesis': f'Test hypothesis for {cell_id}',
        'prediction': f'Test prediction for {cell_id}',
    }
    if fitness is not None:
        fm['fitness'] = fitness
    content = dump_frontmatter(fm, body="Body text\n")
    path = os.path.join(cells_dir, f'{cell_id}.md')
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)
    return path


class TestMatchCellsToChanges:
    """Tests for matching cells to changed files."""

    def test_cell_with_matching_target_is_returned(self, tmp_path):
        from aegis_core.outcomes.engine import match_cells_to_changes
        ws = str(tmp_path)
        _make_cell(ws, 'cell-src', ['src/*.py'])
        result = match_cells_to_changes(ws, ['src/foo.py'])
        assert len(result) >= 1
        cell_ids = [c.get('id', c.get('_name', '')) for c in result]
        assert any('cell-src' in cid for cid in cell_ids)

    def test_cell_with_non_matching_target_excluded(self, tmp_path):
        from aegis_core.outcomes.engine import match_cells_to_changes
        ws = str(tmp_path)
        _make_cell(ws, 'cell-tests', ['tests/*.py'])
        result = match_cells_to_changes(ws, ['src/foo.py'])
        cell_ids = [c.get('id', c.get('_name', '')) for c in result]
        assert not any('cell-tests' in cid for cid in cell_ids)

    def test_empty_changed_files_returns_empty(self, tmp_path):
        from aegis_core.outcomes.engine import match_cells_to_changes
        ws = str(tmp_path)
        _make_cell(ws, 'cell-any', ['src/*.py'])
        result = match_cells_to_changes(ws, [])
        assert result == []

    def test_multiple_cells_only_matching_returned(self, tmp_path):
        from aegis_core.outcomes.engine import match_cells_to_changes
        ws = str(tmp_path)
        _make_cell(ws, 'cell-match', ['src/*.py'])
        _make_cell(ws, 'cell-nomatch', ['docs/*.md'])
        result = match_cells_to_changes(ws, ['src/bar.py'])
        cell_ids = [c.get('id', c.get('_name', '')) for c in result]
        assert any('cell-match' in cid for cid in cell_ids)
        assert not any('cell-nomatch' in cid for cid in cell_ids)

    def test_wildcard_glob_matching(self, tmp_path):
        from aegis_core.outcomes.engine import match_cells_to_changes
        ws = str(tmp_path)
        _make_cell(ws, 'cell-deep', ['src/**/*.py'])
        result = match_cells_to_changes(ws, ['src/sub/deep.py'])
        assert len(result) >= 1


# ── Bug 1: Outcome Engine Path ──────────────────────────────────────────

class TestOutcomeEngineExecution:
    """Direct tests for aegis_core.outcomes.engine functions."""

    def test_get_changed_files(self, monkeypatch, tmp_path):
        from aegis_core.outcomes.engine import _get_changed_files
        import subprocess

        # 1. git diff success
        def mock_check_output(cmd, **kwargs):
            if "diff" in cmd:
                return "src/app.py\nsrc/util.py\n"
            return ""
        monkeypatch.setattr(subprocess, "check_output", mock_check_output)
        files = _get_changed_files(str(tmp_path))
        assert files == ["src/app.py", "src/util.py"]

        # 2. git status fallback
        def mock_status(cmd, **kwargs):
            if "diff" in cmd:
                raise OSError("diff failed")
            return " M src/status.py\n?? untracked.py\n"
        monkeypatch.setattr(subprocess, "check_output", mock_status)
        files = _get_changed_files(str(tmp_path))
        assert "src/status.py" in files or "untracked.py" in files

        # 3. both fail
        def mock_fail(cmd, **kwargs):
            raise OSError("git error")
        monkeypatch.setattr(subprocess, "check_output", mock_fail)
        assert _get_changed_files(str(tmp_path)) == []


"""Phase 4.1 — Quorum sensing behavioral tests.

Tests verify quorum detection behavior, escalation, output format, and edge cases.
These tests call the extracted quorum evaluation function directly (not the CLI).
"""
import json
import os
import pytest
from textwrap import dedent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_cell(ws, subdir, name, *, target_paths=None, minimum_mode='breeze',
               hypothesis='', fitness_score=None, cell_type='vacuole'):
    """Create a minimal cell file in the workspace."""
    cells_dir = os.path.join(ws, '.aegis', "rules", subdir)
    os.makedirs(cells_dir, exist_ok=True)
    lines = [
        '---',
        f'type: {cell_type}',
        f'hypothesis: "{hypothesis}"',
        f'minimum_mode: {minimum_mode}',
    ]
    if target_paths:
        lines.append('target_paths:')
        for p in target_paths:
            lines.append(f'  - "{p}"')
    lines.extend([
        'fitness:',
        '  triggers: 10',
        '  true_positives: 8',
        '  false_positives: 2',
        f'  score: {fitness_score if fitness_score is not None else "null"}',
        '---',
        f'Body of {name}.',
    ])
    content = '\n'.join(lines) + '\n'
    path = os.path.join(cells_dir, f'{name}.md')
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)
    return path


# ---------------------------------------------------------------------------
# Phase 4.1a: Quorum Threshold
# ---------------------------------------------------------------------------

class TestQuorumThreshold:
    """Quorum fires when triggered cell count >= threshold."""

    def test_quorum_fires_when_at_threshold(self, tmp_path):
        ws = str(tmp_path)
        _make_cell(ws, 'vacuoles', 'cell-a', target_paths=['src/*.py'])
        _make_cell(ws, 'vacuoles', 'cell-b', target_paths=['src/*.py'])
        _make_cell(ws, 'vacuoles', 'cell-c', target_paths=['src/*.py'])
        from aegis_core.telemetry import evaluate_quorum
        result = evaluate_quorum(
            cells_dir=os.path.join(ws, '.aegis', "rules"),
            changed_files=['src/main.py'],
            threshold=3
        )
        assert result['quorum'] is True
        assert result['cells_triggered'] >= 3

    def test_quorum_silent_below_threshold(self, tmp_path):
        ws = str(tmp_path)
        _make_cell(ws, 'vacuoles', 'cell-a', target_paths=['src/*.py'])
        _make_cell(ws, 'vacuoles', 'cell-b', target_paths=['src/*.py'])
        from aegis_core.telemetry import evaluate_quorum
        result = evaluate_quorum(
            cells_dir=os.path.join(ws, '.aegis', "rules"),
            changed_files=['src/main.py'],
            threshold=3
        )
        assert result['quorum'] is False
        assert result['cells_triggered'] == 2

    def test_threshold_of_one_always_fires(self, tmp_path):
        ws = str(tmp_path)
        _make_cell(ws, 'vacuoles', 'cell-a', target_paths=['*.py'])
        from aegis_core.telemetry import evaluate_quorum
        result = evaluate_quorum(
            cells_dir=os.path.join(ws, '.aegis', "rules"),
            changed_files=['foo.py'],
            threshold=1
        )
        assert result['quorum'] is True


# ---------------------------------------------------------------------------
# Phase 4.1b: Quorum Disagree
# ---------------------------------------------------------------------------

class TestQuorumDisagree:
    """Cells matching different files don't form quorum unless both are changed."""

    def test_cells_different_targets_no_quorum(self, tmp_path):
        """Two cells with non-overlapping target_paths don't form quorum
        when only one file is changed."""
        ws = str(tmp_path)
        _make_cell(ws, 'vacuoles', 'cell-a', target_paths=['src/*.py'])
        _make_cell(ws, 'vacuoles', 'cell-b', target_paths=['tests/*.py'])
        from aegis_core.telemetry import evaluate_quorum
        result = evaluate_quorum(
            cells_dir=os.path.join(ws, '.aegis', "rules"),
            changed_files=['src/main.py'],
            threshold=2
        )
        assert result['quorum'] is False
        assert result['cells_triggered'] == 1

    def test_cells_both_triggered_forms_quorum(self, tmp_path):
        """Both files changed means both cells trigger → quorum."""
        ws = str(tmp_path)
        _make_cell(ws, 'vacuoles', 'cell-a', target_paths=['src/*.py'])
        _make_cell(ws, 'vacuoles', 'cell-b', target_paths=['tests/*.py'])
        from aegis_core.telemetry import evaluate_quorum
        result = evaluate_quorum(
            cells_dir=os.path.join(ws, '.aegis', "rules"),
            changed_files=['src/main.py', 'tests/test_foo.py'],
            threshold=2
        )
        assert result['quorum'] is True
        assert result['cells_triggered'] == 2


# ---------------------------------------------------------------------------
# Phase 4.1c: Quorum Escalation
# ---------------------------------------------------------------------------

class TestQuorumEscalation:
    """Quorum escalates to the highest minimum_mode among triggered cells."""

    def test_escalates_to_highest_mode(self, tmp_path):
        ws = str(tmp_path)
        _make_cell(ws, 'vacuoles', 'cell-a', target_paths=['src/*.py'],
                   minimum_mode='breeze')
        _make_cell(ws, 'vacuoles', 'cell-b', target_paths=['src/*.py'],
                   minimum_mode='tempest')
        _make_cell(ws, 'vacuoles', 'cell-c', target_paths=['src/*.py'],
                   minimum_mode='gale')
        from aegis_core.telemetry import evaluate_quorum
        result = evaluate_quorum(
            cells_dir=os.path.join(ws, '.aegis', "rules"),
            changed_files=['src/main.py'],
            threshold=2
        )
        assert result['quorum'] is True
        assert result['escalate_to'] == 'fortress'

    def test_single_mode_escalates_to_itself(self, tmp_path):
        ws = str(tmp_path)
        _make_cell(ws, 'vacuoles', 'cell-a', target_paths=['*.py'],
                   minimum_mode='gale')
        _make_cell(ws, 'vacuoles', 'cell-b', target_paths=['*.py'],
                   minimum_mode='gale')
        from aegis_core.telemetry import evaluate_quorum
        result = evaluate_quorum(
            cells_dir=os.path.join(ws, '.aegis', "rules"),
            changed_files=['foo.py'],
            threshold=2
        )
        assert result['escalate_to'] == 'sweep'


# ---------------------------------------------------------------------------
# Phase 4.1d: Quorum Output
# ---------------------------------------------------------------------------

class TestQuorumOutput:
    """Quorum result has expected schema."""

    def test_quorum_result_schema(self, tmp_path):
        ws = str(tmp_path)
        _make_cell(ws, 'vacuoles', 'cell-a', target_paths=['*.py'])
        _make_cell(ws, 'vacuoles', 'cell-b', target_paths=['*.py'])
        from aegis_core.telemetry import evaluate_quorum
        result = evaluate_quorum(
            cells_dir=os.path.join(ws, '.aegis', "rules"),
            changed_files=['foo.py'],
            threshold=2
        )
        assert 'quorum' in result
        assert 'cells_triggered' in result
        assert isinstance(result['cells_triggered'], int)

    def test_quorum_true_has_triggered_cells_list(self, tmp_path):
        ws = str(tmp_path)
        _make_cell(ws, 'vacuoles', 'cell-a', target_paths=['*.py'])
        _make_cell(ws, 'vacuoles', 'cell-b', target_paths=['*.py'])
        from aegis_core.telemetry import evaluate_quorum
        result = evaluate_quorum(
            cells_dir=os.path.join(ws, '.aegis', "rules"),
            changed_files=['foo.py'],
            threshold=2
        )
        assert 'triggered_cells' in result
        assert len(result['triggered_cells']) == 2
        # Each triggered cell should have name and type
        for cell in result['triggered_cells']:
            assert 'name' in cell
            assert 'type' in cell


# ---------------------------------------------------------------------------
# Phase 4.1e: Edge Cases
# ---------------------------------------------------------------------------

class TestQuorumEdgeCases:
    """Edge case handling."""

    def test_empty_cells_dir(self, tmp_path):
        ws = str(tmp_path)
        cells_dir = os.path.join(ws, '.aegis', "rules")
        os.makedirs(cells_dir, exist_ok=True)
        from aegis_core.telemetry import evaluate_quorum
        result = evaluate_quorum(
            cells_dir=cells_dir,
            changed_files=['src/main.py'],
            threshold=3
        )
        assert result['quorum'] is False
        assert result['cells_triggered'] == 0

    def test_no_changed_files(self, tmp_path):
        ws = str(tmp_path)
        _make_cell(ws, 'vacuoles', 'cell-a', target_paths=['*.py'])
        from aegis_core.telemetry import evaluate_quorum
        result = evaluate_quorum(
            cells_dir=os.path.join(ws, '.aegis', "rules"),
            changed_files=[],
            threshold=1
        )
        assert result['quorum'] is False
        assert result['cells_triggered'] == 0

    def test_windows_path_separators(self, tmp_path):
        ws = str(tmp_path)
        _make_cell(ws, 'vacuoles', 'cell-a', target_paths=['src/*.py'])
        from aegis_core.telemetry import evaluate_quorum
        win_changed = [r'src\main.py']
        result = evaluate_quorum(
            cells_dir=os.path.join(ws, '.aegis', "rules"),
            changed_files=win_changed,
            threshold=1
        )
        assert result['cells_triggered'] == 1
        assert result['quorum'] is True



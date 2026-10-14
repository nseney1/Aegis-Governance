from pathlib import Path
"""Behavioral tests for outcome_engine.py — signal-in/fitness-out interface.

Tests match_cells_to_changes, compute_fitness_signals, and update_cell_fitness.

NOTE: outcome_engine.py has bare imports (soma_resolve) that require enzymes/ on
sys.path. We use lazy imports inside test methods to avoid collection errors.
"""
import os
import sys
import json
import pytest
from aegis_core.yaml import dump_frontmatter

REPO_ROOT = str(next(p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").exists()))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from aegis_sdk.cells import parse_cell_file


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


class TestComputeFitnessSignals:
    """Tests for computing fitness signals from outcomes."""

    def test_test_passed_produces_positive_signal(self):
        from aegis_core.telemetry import compute_fitness_signals
        cells = [{'id': 'c1', '_name': 'c1', '_path': '/tmp/c1.md',
                  'target_paths': ['src/*.py']}]
        outcomes = {'test': {'verified': True, 'passed': True, 'exit_code': 0}}
        signals = compute_fitness_signals(cells, outcomes)
        assert len(signals) >= 1
        assert signals[0]['signal'] >= 0  # Non-negative for passed test

    def test_test_failed_produces_negative_signal(self):
        from aegis_core.telemetry import compute_fitness_signals
        cells = [{'id': 'c1', '_name': 'c1', '_path': '/tmp/c1.md',
                  'target_paths': ['src/*.py']}]
        outcomes = {'test': {'verified': True, 'passed': False, 'exit_code': 1}}
        signals = compute_fitness_signals(cells, outcomes)
        assert len(signals) >= 1
        assert signals[0]['signal'] <= 0  # Non-positive for failed test

    def test_signal_clamped_to_range(self):
        from aegis_core.telemetry import compute_fitness_signals
        cells = [{'id': 'c1', '_name': 'c1', '_path': '/tmp/c1.md',
                  'target_paths': ['src/*.py']}]
        outcomes = {
            'test': {'verified': True, 'passed': False, 'exit_code': 1},
            'build': {'exit_code': 1},
            'git': {'reverted': True},
            'mcp': [{'reported_success': True}],
        }
        signals = compute_fitness_signals(cells, outcomes)
        for sig in signals:
            assert -2.0 <= sig['signal'] <= 2.0

    def test_signal_has_required_keys(self):
        from aegis_core.telemetry import compute_fitness_signals
        cells = [{'id': 'c1', '_name': 'c1', '_path': '/tmp/c1.md',
                  'target_paths': ['src/*.py']}]
        outcomes = {'test': {'verified': True, 'passed': True, 'exit_code': 0}}
        signals = compute_fitness_signals(cells, outcomes)
        assert len(signals) >= 1
        sig = signals[0]
        assert 'cell' in sig or '_name' in sig
        assert 'signal' in sig

    def test_empty_cells_returns_empty_signals(self):
        from aegis_core.telemetry import compute_fitness_signals
        signals = compute_fitness_signals([], {'test': {'passed': True}})
        assert signals == []


class TestUpdateCellFitness:
    """Tests for updating cell fitness in frontmatter."""

    def test_positive_signal_increments_true_positives(self, tmp_path):
        from aegis_core.telemetry import update_cell_fitness
        ws = str(tmp_path)
        path = _make_cell(ws, 'cell-pos', ['src/*.py'],
                          fitness={'triggers': 5, 'true_positives': 3,
                                   'false_positives': 1, 'score': 0.5})
        signals = [{'cell': 'cell-pos', '_path': path, 'signal': 1.0,
                     'reasons': ['test passed'], 'verified': True}]
        update_cell_fitness(ws, signals)
        fm, _ = parse_cell_file(path)
        from fractions import Fraction
        assert Fraction(str(fm['fitness']['true_positives'])) >= 4

    def test_negative_signal_increments_false_positives(self, tmp_path):
        from aegis_core.telemetry import update_cell_fitness
        ws = str(tmp_path)
        path = _make_cell(ws, 'cell-neg', ['src/*.py'],
                          fitness={'triggers': 5, 'true_positives': 3,
                                   'false_positives': 1, 'score': 0.5})
        signals = [{'cell': 'cell-neg', '_path': path, 'signal': -1.0,
                     'reasons': ['test failed'], 'verified': True}]
        update_cell_fitness(ws, signals)
        fm, _ = parse_cell_file(path)
        from fractions import Fraction
        assert Fraction(str(fm['fitness']['false_positives'])) >= 2

    def test_triggers_always_incremented(self, tmp_path):
        from aegis_core.telemetry import update_cell_fitness
        ws = str(tmp_path)
        path = _make_cell(ws, 'cell-trg', ['src/*.py'],
                          fitness={'triggers': 5, 'true_positives': 3,
                                   'false_positives': 1, 'score': 0.5})
        signals = [{'cell': 'cell-trg', '_path': path, 'signal': 0.5,
                     'reasons': ['partial'], 'verified': True}]
        update_cell_fitness(ws, signals)
        fm, _ = parse_cell_file(path)
        assert int(fm['fitness']['triggers']) >= 6

    def test_frontmatter_survives_roundtrip(self, tmp_path):
        from aegis_core.telemetry import update_cell_fitness
        ws = str(tmp_path)
        path = _make_cell(ws, 'cell-rt', ['src/*.py'],
                          fitness={'triggers': 5, 'true_positives': 3,
                                   'false_positives': 1, 'score': 0.5})
        signals = [{'cell': 'cell-rt', '_path': path, 'signal': 1.0,
                     'reasons': ['test'], 'verified': True}]
        update_cell_fitness(ws, signals)
        fm, body = parse_cell_file(path)
        assert fm['id'] == 'cell-rt'
        assert fm['type'] == 'vacuole'
        assert 'Body text' in body

    def test_corrupt_cell_no_crash(self, tmp_path):
        from aegis_core.telemetry import update_cell_fitness
        ws = str(tmp_path)
        cells_dir = os.path.join(ws, '.aegis', "rules", 'vacuoles')
        os.makedirs(cells_dir, exist_ok=True)
        corrupt_path = os.path.join(cells_dir, 'corrupt.md')
        with open(corrupt_path, 'w', encoding='utf-8') as f:
            f.write('not valid yaml at all')
        signals = [{'cell': 'corrupt', '_path': corrupt_path, 'signal': 1.0,
                     'reasons': ['test'], 'verified': True}]
        # Should not raise — handles gracefully
        update_cell_fitness(ws, signals)

    def test_missing_fitness_field_initialized(self, tmp_path):
        from aegis_core.telemetry import update_cell_fitness
        ws = str(tmp_path)
        path = _make_cell(ws, 'cell-nofitness', ['src/*.py'])
        signals = [{'cell': 'cell-nofitness', '_path': path, 'signal': 1.0,
                     'reasons': ['test'], 'verified': True}]
        update_cell_fitness(ws, signals)
        fm, _ = parse_cell_file(path)
        assert 'fitness' in fm
        assert int(fm['fitness'].get('triggers', 0)) >= 1

    def test_fractional_credit_deterministic(self, tmp_path):
        from aegis_core.telemetry import update_cell_fitness
        ws = str(tmp_path)
        path = _make_cell(ws, 'cell-frac', ['src/*.py'],
                          fitness={'triggers': 1, 'true_positives': "1/3",
                                   'false_positives': 0, 'score': 0.33})
        signals = [{'cell': 'cell-frac', '_path': path, 'signal': 1.0,
                     'reasons': ['test'], 'verified': True, 'credit_weight': 1.0/3.0}]
        update_cell_fitness(ws, signals)
        
        # Another update
        update_cell_fitness(ws, signals)
        
        fm, _ = parse_cell_file(path)
        assert fm['fitness']['true_positives'] in ["1.0", "1", "1/1"] or str(fm['fitness']['true_positives']) in ["1.0", "1", "1/1"]

class TestAppendFitnessLogGenerationFence:
    def test_outcome_engine_appends_are_generation_fenced(self, tmp_path):
        from aegis_core.telemetry import append_fitness_log
        ws = str(tmp_path)
        os.makedirs(os.path.join(ws, ".aegis"), exist_ok=True)
        with open(os.path.join(ws, ".aegis", "epoch_generation"), "w", encoding="utf-8") as f:
            f.write("2\n")
        sig = [{"cell": "c", "_path": "x", "signal": 0.5, "verified": True, "reasons": []}]
        assert append_fitness_log(ws, sig, {}, expected_generation=1) is False
        assert not os.path.exists(os.path.join(ws, ".aegis", "evidence", "signals.jsonl"))
        assert append_fitness_log(ws, sig, {}, expected_generation=2) is True

# ── Bug 1: Outcome Engine Path ──────────────────────────────────────────

class TestBug1OutcomeEnginePath:
    """Bug 1: capture_mcp_outcomes must read from .aegis/evidence/outcomes.jsonl."""

    def test_reads_from_evidence_dir(self, tmp_path):
        """outcome_engine reads from .aegis/evidence/outcomes.jsonl, not .aegis/outcomes.jsonl."""
        from aegis_core.telemetry import capture_mcp_outcomes

        # Write to the CORRECT path
        evidence_dir = tmp_path / '.aegis' / 'evidence'
        evidence_dir.mkdir(parents=True)
        signals_file = evidence_dir / 'signals.jsonl'
        record = {'cell_id': 'trap-example', 'outcome': 'success',
                  'timestamp': '2026-10-01T00:00:00Z'}
        signals_file.write_text(json.dumps(record) + '\n', encoding='utf-8')

        results = capture_mcp_outcomes(str(tmp_path))
        assert len(results) == 1
        assert results[0]['cell_id'] == 'trap-example'

    def test_ignores_old_path(self, tmp_path):
        """outcome_engine does NOT read from the old .aegis/outcomes.jsonl path."""
        from aegis_core.telemetry import capture_mcp_outcomes

        # Write to the OLD (wrong) path
        old_dir = tmp_path / '.aegis'
        old_dir.mkdir(parents=True)
        old_file = old_dir / 'outcomes.jsonl'
        old_file.write_text(json.dumps({'cell_id': 'stale'}) + '\n', encoding='utf-8')

        # Correct path doesn't exist
        results = capture_mcp_outcomes(str(tmp_path))
        assert len(results) == 0, 'Should not read from old .aegis/outcomes.jsonl path'


class TestBug2OutcomeEngineSchema:
    """Bug 2: compute_fitness_signals must handle both cells_used and cell_id schemas."""

    def test_cell_id_schema_matches(self, tmp_path):
        """MCP records with cell_id (string) are matched to cells."""
        from aegis_core.telemetry import compute_fitness_signals

        triggered_cells = [{
            '_name': 'trap-example',
            '_path': str(tmp_path / 'cell.md'),
            'target_paths': ['enzymes/*'],
        }]
        outcomes = {
            'tests': {'verified': True, 'passed': True, 'framework': 'pytest'},
            'build': {'verified': False, 'passed': None},
            'git': {'reverts': 0, 'rework_count': 0},
            'mcp': [{'cell_id': 'trap-example', 'outcome': 'success'}],
        }

        signals = compute_fitness_signals(triggered_cells, outcomes)
        assert len(signals) == 1
        # success + tests passed = positive signal (agent reported success correctly)
        assert signals[0]['signal'] > 0
        assert any('agent reported success' in r for r in signals[0]['reasons'])

    def test_cells_used_schema_still_works(self, tmp_path):
        """Legacy records with cells_used (list) still match."""
        from aegis_core.telemetry import compute_fitness_signals

        triggered_cells = [{
            '_name': 'trap-example',
            '_path': str(tmp_path / 'cell.md'),
            'target_paths': ['enzymes/*'],
        }]
        outcomes = {
            'tests': {'verified': True, 'passed': True, 'framework': 'pytest'},
            'build': {'verified': False, 'passed': None},
            'git': {'reverts': 0, 'rework_count': 0},
            'mcp': [{'cells_used': ['trap-example'], 'outcome': 'success'}],
        }

        signals = compute_fitness_signals(triggered_cells, outcomes)
        assert len(signals) == 1
        assert any('agent reported success' in r for r in signals[0]['reasons'])


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

    def test_run_outcome_engine_no_cells_dir(self, tmp_path):
        from aegis_core.outcomes.engine import run_outcome_engine
        assert run_outcome_engine(str(tmp_path)) == 0

    def test_run_outcome_engine_no_matches(self, tmp_path):
        from aegis_core.outcomes.engine import run_outcome_engine
        cells_dir = tmp_path / ".aegis" / "rules" / "vacuoles"
        cells_dir.mkdir(parents=True)
        assert run_outcome_engine(str(tmp_path)) == 0

    def test_run_outcome_engine_full_flow(self, monkeypatch, tmp_path):
        from aegis_core.outcomes.engine import run_outcome_engine
        ws = str(tmp_path)
        _make_cell(ws, "cell-active", ["src/*.py"])

        # Mock dependencies in run_outcome_engine
        monkeypatch.setattr("aegis_core.outcomes.engine._get_changed_files", lambda w: ["src/code.py"])
        monkeypatch.setattr("aegis_core.outcomes.telemetry.capture_test_outcome", lambda w: {"verified": True, "passed": True, "framework": "pytest"})
        monkeypatch.setattr("aegis_core.outcomes.telemetry.capture_mcp_outcomes", lambda w: [{"cell_id": "cell-active", "outcome": "success"}])
        monkeypatch.setattr("aegis_core.outcomes.insights.read_human_insight_signals", lambda w: ([{"signal_type": "blind_spot"}, {"_path": "/path/boost.md", "cell": "boost", "signal": 1.0, "verified": True, "reasons": ["boost"]}], 100))

        code = run_outcome_engine(ws)
        assert code == 0

    def test_run_outcome_engine_append_log_failure(self, monkeypatch, tmp_path):
        from aegis_core.outcomes.engine import run_outcome_engine
        ws = str(tmp_path)
        _make_cell(ws, "cell-active", ["src/*.py"])

        monkeypatch.setattr("aegis_core.outcomes.engine._get_changed_files", lambda w: ["src/code.py"])
        monkeypatch.setattr("aegis_core.outcomes.fitness.append_fitness_log", lambda *args, **kwargs: False)

        code = run_outcome_engine(ws)
        assert code == 0

    def test_run_outcome_engine_empty_signals(self, monkeypatch, tmp_path):
        from aegis_core.outcomes.engine import run_outcome_engine
        ws = str(tmp_path)
        _make_cell(ws, "cell-active", ["src/*.py"])

        monkeypatch.setattr("aegis_core.outcomes.engine._get_changed_files", lambda w: ["src/code.py"])
        monkeypatch.setattr("aegis_core.outcomes.fitness.compute_fitness_signals", lambda *args, **kwargs: [])

        code = run_outcome_engine(ws)
        assert code == 0

    def test_main_entrypoint(self, monkeypatch, tmp_path):
        from aegis_core.outcomes.engine import main
        import sys
        ws = str(tmp_path)
        reconfigured = []
        monkeypatch.setattr(sys.stdout, "reconfigure", lambda **kwargs: reconfigured.append(kwargs))
        monkeypatch.setattr("aegis_core.outcomes.engine.run_outcome_engine", lambda w=None: 42 if w is not None else 24)

        assert main(workspace=ws) == 42
        assert len(reconfigured) == 1

        assert main() == 24
        assert len(reconfigured) == 2

    def test_run_outcome_engine_mod_branches(self, tmp_path):
        from aegis_core.outcomes.engine import run_outcome_engine
        import types
        ws = str(tmp_path)
        custom_mod = types.ModuleType("custom_mod")
        custom_mod.resolve_workspace = lambda: ws
        assert run_outcome_engine(mod=custom_mod) == 0





from pathlib import Path
"""Tests for the oracle checkpoint — mid-session fitness feedback.

Verifies that:
1. Checkpoint reads canonical signals.jsonl evidence and produces actionable summaries
2. Cells with zero triggers get "unobserved" classification
3. Cells with high false positives get "noisy" classification
4. Expired cells (via cell_expiry) are flagged
5. Output includes actionable recommendations
6. Empty/missing evidence produces a safe default report
"""
import json
import os
import sys
from datetime import datetime, timedelta

import pytest
from aegis_core.yaml import dump_frontmatter

REPO_ROOT = str(next(p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").exists()))
sys.path.insert(0, REPO_ROOT)


def make_cell(cells_dir, name, cell_type="vacuole", created_days_ago=10,
              expiry_days=60, expiry_sessions=20):
    """Helper: create a minimal cell file."""
    created = (datetime.now() - timedelta(days=created_days_ago)).strftime("%Y-%m-%d")
    fm = {
        'id': name,
        'type': cell_type,
        'enforcement': 'advisory',
        'hypothesis': f'Test cell {name}',
        'prediction': 'test',
        'falsification': 'test',
        'target_paths': ['*.py'],
        'expiry_sessions': expiry_sessions,
        'expiry_days': expiry_days,
        'created': created,
    }
    subdir = os.path.join(cells_dir, f"{cell_type}s")
    os.makedirs(subdir, exist_ok=True)
    filepath = os.path.join(subdir, f"{name}.md")
    with open(filepath, 'w') as f:
        f.write(dump_frontmatter(fm, body=f"# {name}\n"))
    return filepath


def append_signal_records(evidence_dir, records):
    """Append canonical signal rows to signals.jsonl."""
    filepath = os.path.join(evidence_dir, 'signals.jsonl')
    with open(filepath, 'a', encoding='utf-8') as f:
        for record in records:
            f.write(json.dumps(record) + '\n')


@pytest.fixture
def workspace(tmp_path):
    cells_dir = tmp_path / ".aegis" / "rules"
    cells_dir.mkdir(parents=True)
    evidence_dir = tmp_path / ".aegis" / "evidence"
    evidence_dir.mkdir(parents=True)
    return tmp_path


class TestOracleCheckpointBasics:
    """Core checkpoint functionality."""

    def test_empty_workspace_returns_safe_report(self, workspace):
        from aegis_core.proposals import generate_checkpoint
        report = generate_checkpoint(str(workspace))
        assert isinstance(report, dict)
        assert report['total_cells'] == 0
        assert report['classifications'] == {}

    def test_cell_with_no_evidence_is_unobserved(self, workspace):
        from aegis_core.proposals import generate_checkpoint
        cells_dir = str(workspace / ".aegis" / "rules")
        make_cell(cells_dir, "new-cell")
        report = generate_checkpoint(str(workspace))
        assert report['total_cells'] == 1
        assert 'unobserved' in report['classifications']
        assert 'new-cell' in [c['cell_id'] for c in report['classifications']['unobserved']]

    def test_cell_with_triggers_is_healthy(self, workspace):
        from aegis_core.proposals import generate_checkpoint
        cells_dir = str(workspace / ".aegis" / "rules")
        make_cell(cells_dir, "good-cell")
        evidence_dir = str(workspace / ".aegis" / "evidence")
        append_signal_records(evidence_dir, [
            {'cell': 'good-cell', 'signal': 'trigger', 'timestamp': '2026-09-30T10:00:00Z'},
            {'cell': 'good-cell', 'signal': 'trigger', 'timestamp': '2026-09-30T10:01:00Z'},
            {'cell': 'good-cell', 'signal': 'trigger', 'timestamp': '2026-09-30T10:02:00Z'},
        ])
        report = generate_checkpoint(str(workspace))
        assert 'healthy' in report['classifications']
        assert 'good-cell' in [c['cell_id'] for c in report['classifications']['healthy']]


class TestOracleCheckpointClassifications:
    """Verify specific cell health classifications."""

    def test_noisy_cell_flagged(self, workspace):
        from aegis_core.proposals import generate_checkpoint
        cells_dir = str(workspace / ".aegis" / "rules")
        make_cell(cells_dir, "noisy-cell")
        evidence_dir = str(workspace / ".aegis" / "evidence")
        append_signal_records(evidence_dir, [
            {'cell': 'noisy-cell', 'signal': 'trigger', 'timestamp': '2026-09-30T10:00:00Z'},
            {'cell': 'noisy-cell', 'signal': 'trigger', 'timestamp': '2026-09-30T10:01:00Z'},
            {'cell': 'noisy-cell', 'signal': 'trigger', 'timestamp': '2026-09-30T10:02:00Z'},
            {'cell': 'noisy-cell', 'signal': 'trigger', 'timestamp': '2026-09-30T10:03:00Z'},
        ])
        append_signal_records(evidence_dir, [
            {'cell': 'noisy-cell', 'signal': 'fp', 'timestamp': '2026-09-30T11:00:00Z'},
            {'cell': 'noisy-cell', 'signal': 'fp', 'timestamp': '2026-09-30T11:01:00Z',
             'metadata': {'credit_weight': 2}},
            {'cell': 'noisy-cell', 'signal': 'tp', 'timestamp': '2026-09-30T11:02:00Z'},
        ])
        # A contradictory legacy ledger must not override canonical signal evidence.
        legacy_path = os.path.join(evidence_dir, 'outcomes.jsonl')
        with open(legacy_path, 'w', encoding='utf-8') as f:
            f.write(json.dumps({'cell_id': 'noisy-cell', 'outcome': 'tp'}) + '\n')
        report = generate_checkpoint(str(workspace))
        assert 'noisy' in report['classifications']
        noisy = [c for c in report['classifications']['noisy'] if c['cell_id'] == 'noisy-cell']
        assert len(noisy) == 1

    def test_expired_cell_flagged(self, workspace):
        from aegis_core.proposals import generate_checkpoint
        cells_dir = str(workspace / ".aegis" / "rules")
        make_cell(cells_dir, "old-cell", created_days_ago=100, expiry_days=30)
        report = generate_checkpoint(str(workspace))
        assert 'expired' in report['classifications']
        assert 'old-cell' in [c['cell_id'] for c in report['classifications']['expired']]


class TestOracleCheckpointRecommendations:
    """Verify actionable recommendations are produced."""

    def test_report_includes_recommendations(self, workspace):
        from aegis_core.proposals import generate_checkpoint
        cells_dir = str(workspace / ".aegis" / "rules")
        make_cell(cells_dir, "stale-cell", created_days_ago=100, expiry_days=30)
        make_cell(cells_dir, "fresh-cell", created_days_ago=1, expiry_days=60)
        report = generate_checkpoint(str(workspace))
        assert 'recommendations' in report
        assert len(report['recommendations']) > 0

    def test_healthy_workspace_has_no_critical_recommendations(self, workspace):
        from aegis_core.proposals import generate_checkpoint
        cells_dir = str(workspace / ".aegis" / "rules")
        make_cell(cells_dir, "good-cell", created_days_ago=1, expiry_days=60)
        evidence_dir = str(workspace / ".aegis" / "evidence")
        append_signal_records(evidence_dir, [
            {'cell': 'good-cell', 'signal': 'trigger', 'timestamp': '2026-09-30T10:00:00Z'},
        ])
        report = generate_checkpoint(str(workspace))
        critical = [r for r in report.get('recommendations', []) if r.get('severity') == 'critical']
        assert len(critical) == 0

    def test_checkpoint_returns_required_keys(self, workspace):
        from aegis_core.proposals import generate_checkpoint
        report = generate_checkpoint(str(workspace))
        assert "workspace" in report
        assert "healthy_count" in report
        assert "warning_count" in report
        assert "expired_count" in report
        assert "dormant_count" in report

    def test_cli_checkpoint_terminal_mode(self, workspace, capsys):
        from aegis_core.proposals import cli_checkpoint
        rc = cli_checkpoint([str(workspace)])
        assert rc == 0
        captured = capsys.readouterr()
        assert "Soma Oracle Checkpoint" in captured.out
        assert f"Workspace: {workspace}" in captured.out
        assert "Cells:" in captured.out

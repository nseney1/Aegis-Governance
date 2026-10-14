from pathlib import Path
"""Tests for soma sync — canonical signals → cell frontmatter reconciliation.

Covers:
- aggregate_evidence reads signals.jsonl correctly
- sync_frontmatter updates cell YAML frontmatter from aggregated counts
- Idempotency: running sync twice produces no additional changes
- Dry-run mode: reports changes without writing
- CLI entrypoint: soma sync works end-to-end
"""
import argparse
import json
import os
import sys

import pytest
from aegis_core.yaml import dump_frontmatter, parse_frontmatter

REPO_ROOT = str(next(p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").exists()))
sys.path.insert(0, REPO_ROOT)

from aegis_cli.sync import aggregate_evidence, sync_frontmatter, run_sync


CELL_TEMPLATE = """\
---
id: {cell_id}
domain: testing
type: vacuole
enforcement: advisory
fitness:
  score: null
  impact_weight: 1.0
  triggers: 0
  true_positives: 0
  false_positives: 0
---
# {cell_id}

Test cell for sync tests.
"""


def _setup_workspace(tmp_path, cells, fitness_records, outcome_records=None):
    """Create a minimal .soma workspace with cells and evidence."""
    cells_dir = tmp_path / ".aegis" / "rules" / "vacuoles"
    cells_dir.mkdir(parents=True)
    evidence_dir = tmp_path / ".aegis" / "evidence"
    evidence_dir.mkdir(parents=True)

    for cell_id in cells:
        (cells_dir / f"{cell_id}.md").write_text(
            CELL_TEMPLATE.format(cell_id=cell_id), encoding="utf-8"
        )

    with open(evidence_dir / "signals.jsonl", "w", encoding="utf-8") as f:
        for record in fitness_records:
            rec = {
                "cell": record.get("cell_id"),
                "signal": "trigger",
                "timestamp": record.get("triggered_at")
            }
            f.write(json.dumps(rec) + "\n")

        if outcome_records:
            for record in outcome_records:
                rec = {
                    "cell": record.get("cell_id"),
                    "signal": record.get("outcome"),
                }
                f.write(json.dumps(rec) + "\n")

    return str(evidence_dir), str(cells_dir)


class TestAggregateEvidence:
    """Tests for aggregate_evidence()."""

    def test_counts_triggers(self, tmp_path):
        """Trigger events are counted per cell_id."""
        evidence_dir, _ = _setup_workspace(tmp_path, ["cell-a"], [
            {"cell_id": "cell-a", "triggered_at": "2026-01-01T00:00:00Z"},
            {"cell_id": "cell-a", "triggered_at": "2026-01-01T01:00:00Z"},
            {"cell_id": "cell-a", "triggered_at": "2026-01-01T02:00:00Z"},
        ])
        counts = aggregate_evidence(evidence_dir)
        assert counts["cell-a"]["triggers"] == 3

    def test_counts_outcomes(self, tmp_path):
        """TP and FP outcomes are counted from canonical signal rows."""
        evidence_dir, _ = _setup_workspace(
            tmp_path, ["cell-a"],
            fitness_records=[
                {"cell_id": "cell-a", "triggered_at": "2026-01-01T00:00:00Z"},
            ],
            outcome_records=[
                {"cell_id": "cell-a", "outcome": "tp"},
                {"cell_id": "cell-a", "outcome": "tp"},
                {"cell_id": "cell-a", "outcome": "fp"},
            ],
        )
        counts = aggregate_evidence(evidence_dir)
        assert counts["cell-a"]["tp"] == 2
        assert counts["cell-a"]["fp"] == 1

    def test_tracks_last_trigger(self, tmp_path):
        """Last trigger timestamp is tracked."""
        evidence_dir, _ = _setup_workspace(tmp_path, ["cell-a"], [
            {"cell_id": "cell-a", "triggered_at": "2026-01-01T00:00:00Z"},
            {"cell_id": "cell-a", "triggered_at": "2026-01-03T00:00:00Z"},
            {"cell_id": "cell-a", "triggered_at": "2026-01-02T00:00:00Z"},
        ])
        counts = aggregate_evidence(evidence_dir)
        assert counts["cell-a"]["last_trigger"] == "2026-01-03T00:00:00Z"

    def test_empty_evidence(self, tmp_path):
        """Empty evidence directory returns empty dict."""
        evidence_dir = str(tmp_path / "empty")
        os.makedirs(evidence_dir, exist_ok=True)
        counts = aggregate_evidence(evidence_dir)
        assert counts == {}

    def test_multiple_cells(self, tmp_path):
        """Multiple cells are tracked independently."""
        evidence_dir, _ = _setup_workspace(tmp_path, ["cell-a", "cell-b"], [
            {"cell_id": "cell-a", "triggered_at": "2026-01-01T00:00:00Z"},
            {"cell_id": "cell-b", "triggered_at": "2026-01-01T00:00:00Z"},
            {"cell_id": "cell-b", "triggered_at": "2026-01-01T01:00:00Z"},
        ])
        counts = aggregate_evidence(evidence_dir)
        assert counts["cell-a"]["triggers"] == 1
        assert counts["cell-b"]["triggers"] == 2

    def test_malformed_lines_skipped(self, tmp_path):
        """Malformed JSONL lines are skipped without crashing."""
        evidence_dir = str(tmp_path / ".aegis" / "evidence")
        os.makedirs(evidence_dir, exist_ok=True)
        with open(os.path.join(evidence_dir, "signals.jsonl"), "w") as f:
            f.write("not valid json\n")
            f.write(json.dumps({"cell": "cell-a", "signal": "trigger", "timestamp": "2026-01-01T00:00:00Z"}) + "\n")
            f.write("\n")  # blank line
        counts = aggregate_evidence(evidence_dir)
        assert counts["cell-a"]["triggers"] == 1


class TestSyncFrontmatter:
    """Tests for sync_frontmatter()."""

    def test_updates_frontmatter(self, tmp_path):
        """Sync writes trigger/tp/fp/score into cell frontmatter."""
        evidence_dir, cells_dir = _setup_workspace(
            tmp_path, ["cell-a"],
            fitness_records=[
                {"cell_id": "cell-a", "triggered_at": "2026-01-01T00:00:00Z"},
            ],
            outcome_records=[
                {"cell_id": "cell-a", "outcome": "tp"},
            ],
        )
        counts = aggregate_evidence(evidence_dir)
        changes = sync_frontmatter(cells_dir, counts)

        assert len(changes) == 1
        assert changes[0]["cell_id"] == "cell-a"

        # Verify file was updated
        content = (tmp_path / ".aegis" / "rules" / "vacuoles" / "cell-a.md").read_text()
        fm = parse_frontmatter(content)
        assert fm["fitness"]["triggers"] == 1
        assert fm["fitness"]["true_positives"] == 1
        assert fm["fitness"]["false_positives"] == 0
        assert fm["fitness"]["score"] == 1.0

    def test_idempotent(self, tmp_path):
        """Running sync twice produces no changes the second time."""
        evidence_dir, cells_dir = _setup_workspace(
            tmp_path, ["cell-a"],
            fitness_records=[
                {"cell_id": "cell-a", "triggered_at": "2026-01-01T00:00:00Z"},
            ],
            outcome_records=[
                {"cell_id": "cell-a", "outcome": "tp"},
            ],
        )
        counts = aggregate_evidence(evidence_dir)
        sync_frontmatter(cells_dir, counts)
        # Second run
        changes = sync_frontmatter(cells_dir, counts)
        assert len(changes) == 0

    def test_dry_run_no_write(self, tmp_path):
        """Dry run reports changes but doesn't modify files."""
        evidence_dir, cells_dir = _setup_workspace(
            tmp_path, ["cell-a"],
            fitness_records=[
                {"cell_id": "cell-a", "triggered_at": "2026-01-01T00:00:00Z"},
            ],
        )
        counts = aggregate_evidence(evidence_dir)
        changes = sync_frontmatter(cells_dir, counts, dry_run=True)

        assert len(changes) == 1  # reports the change

        # File should NOT be modified
        content = (tmp_path / ".aegis" / "rules" / "vacuoles" / "cell-a.md").read_text()
        fm = parse_frontmatter(content)
        assert fm["fitness"]["triggers"] == 0  # unchanged

    def test_score_calculation(self, tmp_path):
        """Score is tp/triggers, rounded to 4 decimal places."""
        evidence_dir, cells_dir = _setup_workspace(
            tmp_path, ["cell-a"],
            fitness_records=[
                {"cell_id": "cell-a", "triggered_at": f"2026-01-01T0{i}:00:00Z"}
                for i in range(3)
            ],
            outcome_records=[
                {"cell_id": "cell-a", "outcome": "tp"},
                {"cell_id": "cell-a", "outcome": "fp"},
            ],
        )
        counts = aggregate_evidence(evidence_dir)
        changes = sync_frontmatter(cells_dir, counts)
        # score = 1 tp / 3 triggers = 0.3333
        assert changes[0]["score"] == round(1 / 3, 4)

    def test_unknown_cell_ignored(self, tmp_path):
        """Evidence for cells not on disk is silently skipped."""
        evidence_dir, cells_dir = _setup_workspace(
            tmp_path, ["cell-a"],
            fitness_records=[
                {"cell_id": "cell-a", "triggered_at": "2026-01-01T00:00:00Z"},
                {"cell_id": "ghost-cell", "triggered_at": "2026-01-01T00:00:00Z"},
            ],
        )
        counts = aggregate_evidence(evidence_dir)
        changes = sync_frontmatter(cells_dir, counts)
        assert len(changes) == 1
        assert changes[0]["cell_id"] == "cell-a"

    def test_sync_preserves_both_when_has_outcomes_is_false(self, tmp_path):
        """When ledger has only triggers (has_outcomes=False), tp and fp are preserved."""
        from aegis_sdk.rules import parse_cell_file
        cells_dir = tmp_path / ".aegis" / "rules" / "vacuoles"
        cells_dir.mkdir(parents=True)
        cell_file = cells_dir / "cell-a.md"
        cell_file.write_text(
            "---\n"
            "id: cell-a\n"
            "type: vacuole\n"
            "fitness:\n"
            "  triggers: 5\n"
            "  true_positives: 2\n"
            "  false_positives: 1\n"
            "  score: 0.4\n"
            "---\n# cell-a\n",
            encoding="utf-8",
        )
        counts = {
            "cell-a": {
                "triggers": 6,
                "has_triggers": True,
                "has_outcomes": False,
                "tp": 0,
                "fp": 0,
            }
        }
        changes = sync_frontmatter(str(cells_dir), counts)
        assert len(changes) == 1
        assert changes[0]["triggers"] == "5 → 6"

        fm, _ = parse_cell_file(str(cell_file))
        assert fm["fitness"]["triggers"] == 6
        assert fm["fitness"]["true_positives"] == 2
        assert fm["fitness"]["false_positives"] == 1


class TestRunSync:
    """Tests for the CLI entrypoint run_sync()."""

    def test_end_to_end(self, tmp_path, capsys):
        """Full sync via CLI entrypoint prints summary."""
        _setup_workspace(
            tmp_path, ["cell-a"],
            fitness_records=[
                {"cell_id": "cell-a", "triggered_at": "2026-01-01T00:00:00Z"},
            ],
            outcome_records=[
                {"cell_id": "cell-a", "outcome": "tp"},
            ],
        )
        args = argparse.Namespace(dry_run=False, json=False)
        # Monkey-patch resolve_root
        import aegis_cli.sync as sync_mod
        original = sync_mod.resolve_root
        sync_mod.resolve_root = lambda a: tmp_path
        try:
            rc = run_sync(args)
        finally:
            sync_mod.resolve_root = original

        assert rc == 0
        output = capsys.readouterr().out
        assert "cell-a" in output
        assert "1" in output  # trigger count shows up

    def test_no_evidence(self, tmp_path, capsys):
        """No evidence prints friendly message."""
        evidence_dir = tmp_path / ".aegis" / "evidence"
        evidence_dir.mkdir(parents=True)
        (tmp_path / ".aegis" / "rules").mkdir(parents=True)

        args = argparse.Namespace(dry_run=False, json=False)
        import aegis_cli.sync as sync_mod
        original = sync_mod.resolve_root
        sync_mod.resolve_root = lambda a: tmp_path
        try:
            rc = run_sync(args)
        finally:
            sync_mod.resolve_root = original

        assert rc == 0
        assert "No evidence" in capsys.readouterr().out

    def test_json_output(self, tmp_path, capsys):
        """--json flag produces valid JSON."""
        _setup_workspace(
            tmp_path, ["cell-a"],
            fitness_records=[
                {"cell_id": "cell-a", "triggered_at": "2026-01-01T00:00:00Z"},
            ],
        )
        args = argparse.Namespace(dry_run=False, json=True)
        import aegis_cli.sync as sync_mod
        original = sync_mod.resolve_root
        sync_mod.resolve_root = lambda a: tmp_path
        try:
            rc = run_sync(args)
        finally:
            sync_mod.resolve_root = original

        assert rc == 0
        output = json.loads(capsys.readouterr().out)
        assert "changes" in output
        assert isinstance(output["changes"], list)

# ── Regression tests for Bug 4: sync.py score clobber ──────────────────────────

def _make_cell_file(cells_dir, name, fitness=None):
    """Create a minimal cell .md file with optional fitness block."""
    cell_path = os.path.join(cells_dir, f'{name}.md')
    fm = {
        'id': name,
        'type': 'wall',
        'target_paths': ['tests/*'],
    }
    if fitness:
        fm['fitness'] = fitness
    content = dump_frontmatter(fm, body=f"# {name}\n")
    os.makedirs(os.path.dirname(cell_path), exist_ok=True)
    with open(cell_path, 'w', encoding='utf-8') as f:
        f.write(content)
    return cell_path

def _read_frontmatter(cell_path):
    """Read YAML frontmatter from a cell file."""
    with open(cell_path, 'r', encoding='utf-8') as f:
        content = f.read()
    return parse_frontmatter(content)

class TestBug4ScoreClobber:
    """sync.py must NOT clobber scores when no outcome data exists."""

    def test_score_preserved_when_no_outcomes(self, tmp_path):
        """Cell with triggers but zero tp/fp keeps existing score."""
        from aegis_cli.sync import sync_frontmatter

        cells_dir = str(tmp_path / 'cells')
        cell_path = _make_cell_file(
            cells_dir, 'trap-example',
            fitness={'triggers': 5, 'true_positives': 3, 'false_positives': 1,
                     'score': 0.6, 'last_trigger_date': '2026-10-01T00:00:00Z'},
        )

        # Evidence has triggers but NO outcomes (tp=0, fp=0)
        counts = {
            'trap-example': {
                'triggers': 6, 'tp': 0, 'fp': 0, 'last_trigger': '2026-10-01T01:00:00Z',
            },
        }

        sync_frontmatter(cells_dir, counts)

        fm = _read_frontmatter(cell_path)
        fitness = fm['fitness']
        # Triggers should update
        assert fitness['triggers'] == 6
        # But score should NOT be clobbered to 0.0
        assert fitness['score'] != 0.0, (
            'Bug 4: score clobbered to 0.0 when no outcome data exists'
        )

    def test_score_updated_when_outcomes_exist(self, tmp_path):
        """Cell with both triggers and tp/fp gets correct score."""
        from aegis_cli.sync import sync_frontmatter

        cells_dir = str(tmp_path / 'cells')
        cell_path = _make_cell_file(
            cells_dir, 'trap-example',
            fitness={'triggers': 0, 'true_positives': 0, 'false_positives': 0,
                     'score': None},
        )

        counts = {
            'trap-example': {
                'triggers': 10, 'tp': 7, 'fp': 2, 'last_trigger': '2026-10-01T01:00:00Z',
            },
        }

        sync_frontmatter(cells_dir, counts)

        fm = _read_frontmatter(cell_path)
        fitness = fm['fitness']
        assert fitness['triggers'] == 10
        assert fitness['true_positives'] == 7
        assert fitness['false_positives'] == 2
        assert fitness['score'] == 0.7  # 7/10

    def test_zero_triggers_score_is_none(self, tmp_path):
        """Cell with 0 triggers → score = None."""
        from aegis_cli.sync import sync_frontmatter

        cells_dir = str(tmp_path / 'cells')
        cell_path = _make_cell_file(
            cells_dir, 'trap-example',
            fitness={'triggers': 0, 'true_positives': 0, 'false_positives': 0,
                     'score': None},
        )

        counts = {
            'trap-example': {
                'triggers': 0, 'tp': 0, 'fp': 0, 'last_trigger': None,
            },
        }

        # Should not change anything (already in sync)
        changes = sync_frontmatter(cells_dir, counts)
        assert len(changes) == 0

class TestBug3SyncOutcomeMapping:
    """Bug 3: sync.py aggregate_evidence must map success→tp, failure→fp."""

    def test_success_mapped_to_tp(self, tmp_path):
        """outcome='success' is counted as tp."""
        from aegis_cli.sync import aggregate_evidence

        evidence_dir = str(tmp_path)
        signals_file = tmp_path / 'signals.jsonl'
        record = {'cell_id': 'trap-example', 'outcome': 'success',
                  'timestamp': '2026-10-01T00:00:00Z'}
        signals_file.write_text(json.dumps(record) + '\n', encoding='utf-8')

        counts = aggregate_evidence(evidence_dir)
        assert counts['trap-example']['tp'] == 1

    def test_failure_mapped_to_fp(self, tmp_path):
        """outcome='failure' is counted as fp."""
        from aegis_cli.sync import aggregate_evidence

        evidence_dir = str(tmp_path)
        signals_file = tmp_path / 'signals.jsonl'
        record = {'cell_id': 'trap-example', 'outcome': 'failure',
                  'timestamp': '2026-10-01T00:00:00Z'}
        signals_file.write_text(json.dumps(record) + '\n', encoding='utf-8')

        counts = aggregate_evidence(evidence_dir)
        assert counts['trap-example']['fp'] == 1

    def test_literal_tp_fp_still_work(self, tmp_path):
        """outcome='tp' and 'fp' still count correctly (backward compat)."""
        from aegis_cli.sync import aggregate_evidence

        evidence_dir = str(tmp_path)
        signals_file = tmp_path / 'signals.jsonl'
        lines = [
            json.dumps({'cell_id': 'cell-a', 'outcome': 'tp'}),
            json.dumps({'cell_id': 'cell-a', 'outcome': 'fp'}),
        ]
        signals_file.write_text('\n'.join(lines) + '\n', encoding='utf-8')

        counts = aggregate_evidence(evidence_dir)
        assert counts['cell-a']['tp'] == 1
        assert counts['cell-a']['fp'] == 1

    def test_partial_outcome_ignored(self, tmp_path):
        """outcome='partial' is neither tp nor fp."""
        from aegis_cli.sync import aggregate_evidence

        evidence_dir = str(tmp_path)
        signals_file = tmp_path / 'signals.jsonl'
        record = {'cell_id': 'trap-example', 'outcome': 'partial',
                  'timestamp': '2026-10-01T00:00:00Z'}
        signals_file.write_text(json.dumps(record) + '\n', encoding='utf-8')

        counts = aggregate_evidence(evidence_dir)
        assert counts['trap-example']['tp'] == 0
        assert counts['trap-example']['fp'] == 0

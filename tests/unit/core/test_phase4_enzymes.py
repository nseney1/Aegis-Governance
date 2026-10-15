"""Unit and behavioral tests for pure-Python migrated enzymes in Phase 4."""
from __future__ import annotations

import json
from pathlib import Path

from conftest import REPO_ROOT

ENZYMES_DIR = Path(REPO_ROOT) / "enzymes"


def test_cell_selection_evaluation(tmp_path):
    from aegis_core.lifecycle import run_cell_selection

    cells_dir = tmp_path / ".aegis" / "rules"
    walls_dir = cells_dir / "walls"
    archive_dir = cells_dir / ".archive"
    walls_dir.mkdir(parents=True)

    cell_content = """---
id: test-cell
type: wall
fitness:
  score: 0.1
  triggers: 10
  false_positives: 9
---
Test body
"""
    (walls_dir / "test-cell.md").write_text(cell_content, encoding="utf-8")

    # Run check mode (dry run)
    rc = run_cell_selection(workspace=tmp_path, execute=False)
    assert rc == 0
    assert (walls_dir / "test-cell.md").exists()

    # Run execute mode
    rc = run_cell_selection(workspace=tmp_path, execute=True)
    assert rc == 0
    assert not (walls_dir / "test-cell.md").exists()
    assert (archive_dir / "test-cell.md").exists()


def test_log_finding(tmp_path):
    from aegis_core.evidence import log_finding

    rc = log_finding(
        severity="warning",
        rule="providence.md",
        change="Refactored parser",
        source="test_runner",
        logs_dir=tmp_path,
    )
    assert rc == 0
    auto_log = tmp_path / "governance" / "auto_applied_log.jsonl"
    assert auto_log.exists()
    lines = [json.loads(l) for l in auto_log.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(lines) == 1
    assert lines[0]["rule"] == "providence.md"
    assert lines[0]["severity"] == "warning"
    assert lines[0]["change"] == "Refactored parser"



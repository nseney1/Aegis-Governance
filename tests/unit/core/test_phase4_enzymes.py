"""Unit and behavioral tests for pure-Python migrated enzymes in Phase 4."""
from __future__ import annotations

from pathlib import Path

from conftest import REPO_ROOT

ENZYMES_DIR = Path(REPO_ROOT) / "enzymes"


def test_cell_selection_evaluation(tmp_path):
    from aegis_core.lifecycle.selection import run_cell_selection

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



"""Tests for lifecycle engine hardening (Phase 1).

Verifies age gate fail-closed behavior, created_date attribute loading,
terminal promotion handling, and rollback on failed atomic moves.
"""
from datetime import datetime, timezone, timedelta
from pathlib import Path
import pytest

from aegis_sdk.cells import Cell, CellFitness, load_cell
from aegis_cli.rule import _force_promote, _force_demote, run_promote


def test_is_promotable_with_age_fails_closed_on_invalid_date():
    """Unparseable or invalid created_date MUST return False, not True."""
    c = Cell(name="test", type="vacuole", fitness=CellFitness(triggers=20, true_positives=19))
    
    # Unparseable string date
    c.created_date = "invalid-date-format"
    assert c.is_promotable_with_age(min_age_days=30) is False

    # None created_date
    c.created_date = None
    assert c.is_promotable_with_age(min_age_days=30) is False


def test_load_cell_populates_created_date(tmp_path):
    """load_cell must populate created_date on the loaded Cell instance."""
    cells_dir = tmp_path / ".aegis" / "rules" / "vacuoles"
    cells_dir.mkdir(parents=True)
    cell_file = cells_dir / "test-cell.md"
    cell_file.write_text(
        "---\nname: test-cell\ntype: vacuole\ncreated_date: '2026-01-01T00:00:00Z'\n---\nHypothesis\n",
        encoding="utf-8"
    )

    cell = load_cell("test-cell", cells_dir=str(tmp_path / ".aegis" / "rules"))
    assert hasattr(cell, "created_date")
    assert cell.created_date is not None
    assert isinstance(cell.created_date, (datetime, str))


def test_force_promote_handles_genome_cells(tmp_path, capsys):
    """Promoting a cell already in genome must report terminal status, not 'not found'."""
    genome_dir = tmp_path / "genome"
    genome_dir.mkdir()
    (tmp_path / "aegis_core").mkdir(parents=True)
    (tmp_path / "aegis_cli").mkdir(parents=True)
    (tmp_path / "pyproject.toml").write_text('name = "aegis-governance"\n', encoding="utf-8")
    cell_file = genome_dir / "rule-law.md"
    cell_file.write_text("---\nname: rule-law\ntype: genome\n---\nLaw body\n", encoding="utf-8")

    code = _force_promote(tmp_path, "rule-law", dry_run=False, use_json=False)
    out = capsys.readouterr().out
    assert "already" in out.lower() or "terminal" in out.lower() or "genome" in out.lower()
    assert "not found" not in out.lower()


def test_force_promote_rollback_on_unlink_failure(tmp_path, monkeypatch):
    """If cell_path.unlink() fails after target_path is written, target_path must be cleaned up."""
    cells_dir = tmp_path / ".aegis" / "rules"
    vac_dir = cells_dir / "vacuoles"
    vac_dir.mkdir(parents=True)
    wall_dir = cells_dir / "walls"
    wall_dir.mkdir(parents=True)

    cell_file = vac_dir / "test-cell.md"
    cell_file.write_text("---\nname: test-cell\ntype: vacuole\n---\nHypothesis\n", encoding="utf-8")

    def mock_unlink(self, *args, **kwargs):
        raise OSError("Permission denied / disk locked")

    monkeypatch.setattr(Path, "unlink", mock_unlink)

    with pytest.raises(OSError):
        _force_promote(tmp_path, "test-cell", dry_run=False, use_json=False)

    target_file = wall_dir / "test-cell.md"
    assert not target_file.exists(), "Target file must be rolled back on unlink failure"

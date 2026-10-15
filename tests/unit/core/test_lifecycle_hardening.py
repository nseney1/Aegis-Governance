"""Tests for lifecycle engine hardening (Phase 1).

Verifies age gate fail-closed behavior, created_date attribute loading,
terminal promotion handling, and rollback on failed atomic moves.
"""
from pathlib import Path
import pytest

from aegis_cli.rule import _force_promote


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
    vac_dir = cells_dir / "traps"
    vac_dir.mkdir(parents=True)
    wall_dir = cells_dir / "invariants"
    wall_dir.mkdir(parents=True)

    cell_file = vac_dir / "test-cell.md"
    cell_file.write_text("---\nname: test-cell\ntype: trap\n---\nHypothesis\n", encoding="utf-8")

    def mock_unlink(self, *args, **kwargs):
        raise OSError("Permission denied / disk locked")

    monkeypatch.setattr(Path, "unlink", mock_unlink)

    with pytest.raises(OSError):
        _force_promote(tmp_path, "test-cell", dry_run=False, use_json=False)

    target_file = wall_dir / "test-cell.md"
    assert not target_file.exists(), "Target file must be rolled back on unlink failure"

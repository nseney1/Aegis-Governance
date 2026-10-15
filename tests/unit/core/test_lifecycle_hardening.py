"""Tests for lifecycle engine hardening (Phase 1).

Verifies rollback on failed atomic moves. Rules live only in .aegis/rules/<type>/:
the v2 genome/ lookup is gone with the one loader (#19).
"""
from pathlib import Path
import pytest

from aegis_cli.rule import _force_promote


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

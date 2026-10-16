"""aegis_core.workspace.confinement.validate_workspace_path: what a caller may name as a workspace."""
from __future__ import annotations

from pathlib import Path

import pytest

from aegis_core.errors import WorkspaceError
from aegis_core.workspace.confinement import validate_workspace_path


def test_a_v4_workspace_validates_to_its_root(tmp_path: Path):
    (tmp_path / ".aegis" / "rules").mkdir(parents=True)
    assert validate_workspace_path(str(tmp_path)).samefile(tmp_path)


def test_v3_rule_files_left_beside_a_v4_workspace_are_refused_with_the_upgrade_path(tmp_path: Path):
    # They would silently not be served: the caller is told to migrate them instead.
    (tmp_path / ".aegis" / "rules").mkdir(parents=True)
    cells = tmp_path / ".soma" / "cells"
    cells.mkdir(parents=True)
    (cells / "old-trap.md").write_text("---\nid: old-trap\n---\n", encoding="utf-8")

    with pytest.raises(WorkspaceError, match=r"^Legacy \.soma/ workspace detected at .*aegis migrate"):
        validate_workspace_path(str(tmp_path))

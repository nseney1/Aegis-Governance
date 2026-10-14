"""Unit tests for aegis_core.workspace (Layer 0 Core)."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from aegis_core.workspace import (
    Workspace,
    confine_path,
    confine_workspace,
    resolve_workspace,
    resolve_workspace_path,
    validate_cell_names,
)


class TestWorkspaceCore:
    def test_resolve_workspace_with_env(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        ws = tmp_path / "my_project"
        cells = ws / ".soma" / "cells"
        cells.mkdir(parents=True)

        monkeypatch.setenv("SOMA_WORKSPACE", str(ws))
        resolved = resolve_workspace()
        assert resolved == str(ws.resolve())

        # Test strict_env behavior
        monkeypatch.setenv("SOMA_WORKSPACE", str(tmp_path / "nonexistent"))
        with pytest.raises(ValueError, match="no .soma/cells found"):
            resolve_workspace(strict_env=True)

    def test_resolve_workspace_walkup(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("SOMA_WORKSPACE", raising=False)
        monkeypatch.delenv("SOMA_ROOT", raising=False)

        ws = tmp_path / "root"
        (ws / ".soma" / "cells").mkdir(parents=True)
        sub = ws / "subdir" / "deep"
        sub.mkdir(parents=True)

        resolved = resolve_workspace(start=sub)
        assert resolved == str(ws.resolve())

        resolved_p = resolve_workspace_path(start=sub)
        assert resolved_p == ws.resolve()
        assert isinstance(resolved_p, Path)

    def test_directory_helpers(self, tmp_path: Path):
        ws = Workspace(root=tmp_path / "repo")
        assert ws.cells_dir == tmp_path / "repo" / ".soma" / "cells"
        assert ws.metrics_dir == tmp_path / "repo" / ".soma" / "metrics"
        assert ws.signals_file == tmp_path / "repo" / ".soma" / "evidence" / "signals.jsonl"

    def test_confine_workspace(self, tmp_path: Path):
        ws = tmp_path / "valid"
        (ws / ".soma" / "cells").mkdir(parents=True)
        assert confine_workspace(str(ws)) == str(ws.resolve())

        with pytest.raises(ValueError, match="missing .soma/cells"):
            confine_workspace(str(tmp_path))

    def test_confine_path(self, tmp_path: Path):
        ws = tmp_path / "sandbox"
        (ws / ".soma" / "cells").mkdir(parents=True)
        target = ws / "sub" / "file.txt"
        target.parent.mkdir(parents=True)
        target.write_text("ok")

        abs_p, rel_p = confine_path("sub/file.txt", ws)
        assert abs_p == str(target.resolve())
        assert rel_p == os.path.join("sub", "file.txt")

        # Path traversal rejection
        with pytest.raises(ValueError, match="path traversal blocked"):
            confine_path("../outside.txt", ws)

    def test_validate_cell_names(self, tmp_path: Path):
        ws = tmp_path / "cells_ws"
        cells_dir = ws / ".soma" / "cells" / "walls"
        cells_dir.mkdir(parents=True)
        (cells_dir / "wall-alpha.md").write_text("# Wall")
        (cells_dir / "wall-beta.md").write_text("# Wall")

        invalid = validate_cell_names(["wall-alpha", "wall-beta"], ws)
        assert invalid == []

        invalid = validate_cell_names(["wall-alpha", "wall-gamma"], ws)
        assert invalid == ["wall-gamma"]

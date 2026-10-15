"""Unit tests for aegis_core.workspace (Layer 0 Core)."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from aegis_core.errors import WorkspaceError
from aegis_core.workspace.base import Workspace
from aegis_core.workspace import (
    confine_path,
    resolve_workspace,
    validate_rule_names,
)


class TestWorkspaceCore:
    def test_resolve_workspace_with_env(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        ws = tmp_path / "my_project"
        rules = ws / ".aegis" / "rules"
        rules.mkdir(parents=True)

        monkeypatch.setenv("AEGIS_WORKSPACE", str(ws))
        resolved = resolve_workspace()
        assert resolved == str(ws.resolve())

        # Test strict_env behavior
        monkeypatch.setenv("AEGIS_WORKSPACE", str(tmp_path / "nonexistent"))
        with pytest.raises(ValueError, match="no .aegis/rules found"):
            resolve_workspace(strict_env=True)

    def test_resolve_workspace_walkup(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("AEGIS_WORKSPACE", raising=False)
        monkeypatch.delenv("AEGIS_ROOT", raising=False)

        ws = tmp_path / "root"
        (ws / ".aegis" / "rules").mkdir(parents=True)
        sub = ws / "subdir" / "deep"
        sub.mkdir(parents=True)

        resolved = resolve_workspace(start=sub)
        assert resolved == str(ws.resolve())

        resolved_p = Workspace.resolve(start=sub).root
        assert resolved_p == ws.resolve()
        assert isinstance(resolved_p, Path)

    def test_directory_helpers(self, tmp_path: Path):
        ws = Workspace(root=tmp_path / "repo")
        assert ws.aegis_dir == tmp_path / "repo" / ".aegis"
        assert ws.rules_dir == tmp_path / "repo" / ".aegis" / "rules"
        assert ws.metrics_dir == tmp_path / "repo" / ".aegis" / "metrics"
        assert ws.signals_file == tmp_path / "repo" / ".aegis" / "evidence" / "signals.jsonl"

    def test_confine_workspace(self, tmp_path: Path):
        ws = tmp_path / "valid"
        (ws / ".aegis" / "rules").mkdir(parents=True)
        assert str(Workspace.confine(str(ws)).root) == str(ws.resolve())

        with pytest.raises(ValueError, match="missing .aegis/rules"):
            str(Workspace.confine(str(tmp_path)).root)

    def test_legacy_soma_workspace_raises_upgrade_sentinel(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("AEGIS_WORKSPACE", raising=False)
        monkeypatch.delenv("AEGIS_ROOT", raising=False)
        legacy_ws = tmp_path / "legacy_project"
        (legacy_ws / ".soma" / "cells").mkdir(parents=True)

        with pytest.raises(WorkspaceError, match="aegis migrate"):
            str(Workspace.confine(str(legacy_ws)).root)

        with pytest.raises(WorkspaceError, match="aegis migrate"):
            resolve_workspace(start=legacy_ws)

    def test_confine_path(self, tmp_path: Path):
        ws = tmp_path / "sandbox"
        (ws / ".aegis" / "rules").mkdir(parents=True)
        target = ws / "sub" / "file.txt"
        target.parent.mkdir(parents=True)
        target.write_text("ok")

        abs_p, rel_p = confine_path("sub/file.txt", ws)
        assert abs_p == str(target.resolve())
        assert rel_p == os.path.join("sub", "file.txt")

        # Path traversal rejection
        with pytest.raises(ValueError, match="path traversal blocked"):
            confine_path("../outside.txt", ws)

    def test_validate_rule_names(self, tmp_path: Path):
        ws = tmp_path / "rules_ws"
        rules_dir = ws / ".aegis" / "rules" / "invariants"
        rules_dir.mkdir(parents=True)
        (rules_dir / "invariant-alpha.md").write_text("# Rule")
        (rules_dir / "invariant-beta.md").write_text("# Rule")

        invalid = validate_rule_names(["invariant-alpha", "invariant-beta"], ws)
        assert invalid == []

        invalid = validate_rule_names(["invariant-alpha", "invariant-gamma"], ws)
        assert invalid == ["invariant-gamma"]

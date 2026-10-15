"""Tests for uninitialized workspace bootstrapping and scaffolding (Phase 18)."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from conftest import symlink_or_skip
from aegis_core.errors import WorkspaceBareRepoError, WorkspaceError
from aegis_core.workspace.base import Workspace
from aegis_core.workspace.hooks import resolve_git_hooks_dir


class TestWorkspaceForInit:
    def test_for_init_uninitialized_directory(self, tmp_path: Path):
        """Workspace.for_init creates an immutable Workspace object on an uninitialized dir."""
        blank_dir = tmp_path / "blank_project"
        blank_dir.mkdir()

        ws = Workspace.for_init(blank_dir)
        assert isinstance(ws, Workspace)
        assert ws.root == blank_dir.resolve()
        assert not ws.rules_dir.exists()
        assert ws.rules_dir == blank_dir.resolve() / ".aegis" / "rules"

    def test_for_init_rejects_symlink(self, tmp_path: Path):
        """Workspace.for_init rejects symlink paths to prevent directory traversal escapes."""
        real_dir = tmp_path / "real_dir"
        real_dir.mkdir()
        sym_dir = tmp_path / "sym_dir"
        symlink_or_skip(real_dir, sym_dir, target_is_directory=True)

        with pytest.raises(WorkspaceError, match="symlink"):
            Workspace.for_init(sym_dir)

    def test_for_init_rejects_file(self, tmp_path: Path):
        """Workspace.for_init rejects non-directory file targets."""
        some_file = tmp_path / "some_file.txt"
        some_file.write_text("hello", encoding="utf-8")

        with pytest.raises(WorkspaceError, match="must be a directory"):
            Workspace.for_init(some_file)

    def test_for_init_string_path(self, tmp_path: Path):
        """Workspace.for_init accepts str paths."""
        blank_dir = tmp_path / "str_project"
        blank_dir.mkdir()
        ws = Workspace.for_init(str(blank_dir))
        assert ws.root == blank_dir.resolve()


class TestWorkspaceScaffold:
    def test_scaffold_default(self, tmp_path: Path):
        """ws.scaffold creates standard rule tiers and evidence/metrics dirs."""
        blank_dir = tmp_path / "new_project"
        blank_dir.mkdir()
        ws = Workspace.for_init(blank_dir)

        created = ws.scaffold(minimal=False, dry_run=False)
        assert (ws.root / ".aegis" / "rules" / "traps").is_dir()
        assert (ws.root / ".aegis" / "rules" / "invariants").is_dir()
        assert (ws.root / ".aegis" / "rules" / "gates").is_dir()
        assert (ws.root / ".aegis" / "evidence").is_dir()
        assert (ws.root / ".aegis" / "metrics").is_dir()
        assert len(created) >= 4

    def test_scaffold_minimal(self, tmp_path: Path):
        """ws.scaffold with minimal=True creates minimal directory set."""
        blank_dir = tmp_path / "min_project"
        blank_dir.mkdir()
        ws = Workspace.for_init(blank_dir)

        created = ws.scaffold(minimal=True, dry_run=False)
        assert (ws.root / ".aegis" / "rules" / "invariants").is_dir()
        assert (ws.root / ".aegis" / "evidence").is_dir()
        assert not (ws.root / ".aegis" / "rules" / "traps").exists()

    def test_scaffold_dry_run(self, tmp_path: Path):
        """ws.scaffold with dry_run=True returns paths without mutating filesystem."""
        blank_dir = tmp_path / "dry_project"
        blank_dir.mkdir()
        ws = Workspace.for_init(blank_dir)

        created = ws.scaffold(minimal=False, dry_run=True)
        assert len(created) >= 4
        assert not (ws.root / ".aegis").exists()

    def test_scaffold_bare_git_repo_rejected(self, tmp_path: Path):
        """ws.scaffold rejects bare git repositories with WorkspaceBareRepoError."""
        bare_repo = tmp_path / "bare_repo.git"
        bare_repo.mkdir()
        (bare_repo / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
        (bare_repo / "config").write_text("[core]\nbare = true\n", encoding="utf-8")
        (bare_repo / "objects").mkdir()

        ws = Workspace.for_init(bare_repo)
        with pytest.raises(WorkspaceBareRepoError, match="bare git repository"):
            ws.scaffold()


class TestWorkspaceMonorepoHookIsolation:
    def test_subfolder_does_not_attach_parent_git_hooks(self, tmp_path: Path):
        """In a nested subfolder workspace, git_hooks_dir is None if .git is only in parent."""
        parent_repo = tmp_path / "parent_repo"
        parent_repo.mkdir()
        (parent_repo / ".git" / "hooks").mkdir(parents=True)

        sub_project = parent_repo / "packages" / "sub_pkg"
        sub_project.mkdir(parents=True)

        ws = Workspace.for_init(sub_project)
        # Because sub_project does not have its own .git directory or worktree file,
        # resolve_git_hooks_dir attached to ws must be None (no silent parent hijacking)
        assert ws.git_hooks_dir is None

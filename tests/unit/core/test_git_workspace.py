"""Behavioral tests for GitWorkspace(Workspace) and polymorphic Workspace.resolve().

Tests zero-subprocess fast paths, worktree awareness, packed-refs resolution,
and seamless Liskov Substitution Principle compliance.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from aegis_core.workspace import GitWorkspace, Workspace, as_workspace


class TestGitWorkspaceHierarchy:
    """Verifies class hierarchy and Liskov Substitution Principle compliance."""

    def test_subclass_relationship(self):
        assert issubclass(GitWorkspace, Workspace)

    def test_isinstance_polymorphism(self, tmp_path):
        ws = GitWorkspace(root=tmp_path)
        assert isinstance(ws, Workspace)
        assert isinstance(ws, GitWorkspace)
        assert isinstance(ws, os.PathLike)

    def test_repr(self, tmp_path):
        ws = GitWorkspace(root=tmp_path)
        r = repr(ws)
        assert "GitWorkspace(" in r
        assert repr(ws.root) in r or str(tmp_path).replace("\\", "/") in r.replace("\\", "/")


class TestPolymorphicResolution:
    """Verifies that Workspace.resolve() dynamically selects GitWorkspace vs Workspace."""

    def test_resolve_plain_directory_returns_base_workspace(self, tmp_path):
        plain_dir = tmp_path / "plain_project"
        plain_dir.mkdir()
        ws = Workspace.resolve(start=plain_dir)
        assert isinstance(ws, Workspace)
        assert not isinstance(ws, GitWorkspace)
        assert not ws.is_git

    def test_resolve_git_repo_returns_git_workspace(self, tmp_path):
        git_dir = tmp_path / "git_project"
        git_dir.mkdir()
        subprocess.run(["git", "init"], cwd=str(git_dir), check=True, capture_output=True)

        ws = Workspace.resolve(start=git_dir)
        assert isinstance(ws, GitWorkspace)
        assert isinstance(ws, Workspace)
        assert ws.is_git
        assert ws.git_dir == git_dir / ".git"
        assert ws.git_common_dir == git_dir / ".git"

    def test_resolve_subdirectory_in_git_repo_returns_git_workspace(self, tmp_path):
        git_dir = tmp_path / "git_project"
        git_dir.mkdir()
        subprocess.run(["git", "init"], cwd=str(git_dir), check=True, capture_output=True)

        sub_dir = git_dir / "subdir" / "deep"
        sub_dir.mkdir(parents=True)

        ws = Workspace.resolve(start=sub_dir)
        assert isinstance(ws, GitWorkspace)
        assert ws.is_git
        assert ws.git_dir == git_dir / ".git"

    def test_as_workspace_coercion(self, tmp_path):
        git_dir = tmp_path / "git_project"
        git_dir.mkdir()
        subprocess.run(["git", "init"], cwd=str(git_dir), check=True, capture_output=True)

        ws = as_workspace(git_dir)
        assert isinstance(ws, GitWorkspace)

        # Idempotence when already a Workspace
        ws2 = as_workspace(ws)
        assert ws2 is ws


class TestZeroSubprocessFastPaths:
    """Verifies zero-subprocess fast paths for HEAD, branch name, and packed-refs."""

    def test_head_commit_and_branch_loose_ref(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-b", "main"], cwd=str(repo), check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=str(repo), check=True)
        subprocess.run(["git", "config", "user.name", "Tester"], cwd=str(repo), check=True)

        test_file = repo / "hello.txt"
        test_file.write_text("hello", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=str(repo), check=True)
        subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=str(repo), check=True, capture_output=True)

        proc = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(repo), capture_output=True, text=True, check=True)
        expected_sha = proc.stdout.strip()

        ws = GitWorkspace(root=repo)
        assert ws.branch_name == "main"
        assert ws.head_commit == expected_sha

    def test_head_commit_packed_refs(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-b", "main"], cwd=str(repo), check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=str(repo), check=True)
        subprocess.run(["git", "config", "user.name", "Tester"], cwd=str(repo), check=True)

        (repo / "file.txt").write_text("content", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=str(repo), check=True)
        subprocess.run(["git", "commit", "-m", "Commit 1"], cwd=str(repo), check=True, capture_output=True)

        # Pack refs (moves refs/heads/main into .git/packed-refs and deletes loose ref)
        subprocess.run(["git", "pack-refs", "--all"], cwd=str(repo), check=True, capture_output=True)

        loose_ref = repo / ".git" / "refs" / "heads" / "main"
        assert not loose_ref.exists()
        assert (repo / ".git" / "packed-refs").is_file()

        ws = GitWorkspace(root=repo)
        proc = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(repo), capture_output=True, text=True, check=True)
        expected_sha = proc.stdout.strip()

        assert ws.head_commit == expected_sha
        assert ws.branch_name == "main"

    def test_detached_head_commit(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-b", "main"], cwd=str(repo), check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=str(repo), check=True)
        subprocess.run(["git", "config", "user.name", "Tester"], cwd=str(repo), check=True)

        (repo / "file.txt").write_text("v1", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=str(repo), check=True)
        subprocess.run(["git", "commit", "-m", "Commit 1"], cwd=str(repo), check=True, capture_output=True)

        proc = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(repo), capture_output=True, text=True, check=True)
        sha = proc.stdout.strip()

        # Detach HEAD
        subprocess.run(["git", "checkout", sha], cwd=str(repo), check=True, capture_output=True)

        ws = GitWorkspace(root=repo)
        assert ws.head_commit == sha
        assert ws.branch_name is None


class TestGitWorkspaceOperations:
    """Verifies diff, changed files, untracked files, and worktree operations."""

    def test_diff_and_changed_files(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-b", "main"], cwd=str(repo), check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=str(repo), check=True)
        subprocess.run(["git", "config", "user.name", "Tester"], cwd=str(repo), check=True)

        (repo / "tracked.txt").write_text("initial\n", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=str(repo), check=True)
        subprocess.run(["git", "commit", "-m", "Init"], cwd=str(repo), check=True, capture_output=True)

        ws = GitWorkspace(root=repo)
        assert ws.get_diff() == ""
        assert ws.get_changed_files() == []

        # Modify tracked file
        (repo / "tracked.txt").write_text("modified\n", encoding="utf-8")
        assert "modified" in ws.get_diff()
        assert ws.get_changed_files() == ["tracked.txt"]

        # Stage modification
        subprocess.run(["git", "add", "tracked.txt"], cwd=str(repo), check=True)
        assert ws.get_diff(staged=False) == ""
        assert "modified" in ws.get_diff(staged=True)
        assert ws.get_changed_files(staged=True) == ["tracked.txt"]

    def test_untracked_files_with_gitignore(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "init"], cwd=str(repo), check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=str(repo), check=True)
        subprocess.run(["git", "config", "user.name", "Tester"], cwd=str(repo), check=True)
        (repo / ".gitignore").write_text("*.ignored\n", encoding="utf-8")
        subprocess.run(["git", "add", ".gitignore"], cwd=str(repo), check=True)
        subprocess.run(["git", "commit", "-m", "Ignore"], cwd=str(repo), check=True, capture_output=True)

        (repo / "new_file.py").write_text("print(1)", encoding="utf-8")
        (repo / "skip.ignored").write_text("skip", encoding="utf-8")

        ws = GitWorkspace(root=repo)
        untracked = ws.get_untracked_files()
        assert "new_file.py" in untracked
        assert "skip.ignored" not in untracked

    def test_list_worktrees(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-b", "main"], cwd=str(repo), check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=str(repo), check=True)
        subprocess.run(["git", "config", "user.name", "Tester"], cwd=str(repo), check=True)
        (repo / "file.txt").write_text("v1", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=str(repo), check=True)
        subprocess.run(["git", "commit", "-m", "Init"], cwd=str(repo), check=True, capture_output=True)

        wt_dir = tmp_path / "wt_branch"
        subprocess.run(
            ["git", "worktree", "add", "-b", "feature", str(wt_dir)],
            cwd=str(repo),
            check=True,
            capture_output=True,
        )

        ws = GitWorkspace(root=repo)
        wts = ws.list_worktrees()
        assert len(wts) == 2
        paths = [w["path"].resolve() for w in wts]
        assert repo.resolve() in paths
        assert wt_dir.resolve() in paths

        # Verify the worktree workspace resolves properly as GitWorkspace
        wt_ws = Workspace.resolve(start=wt_dir)
        assert isinstance(wt_ws, GitWorkspace)
        assert wt_ws.is_worktree
        assert wt_ws.branch_name == "feature"
        assert wt_ws.git_common_dir == repo.resolve() / ".git"


class TestNonGitFallback:
    """Verifies that GitWorkspace behaves gracefully when pointing to a non-git directory."""

    def test_empty_git_dir_behavior(self, tmp_path):
        ws = GitWorkspace(root=tmp_path)
        assert ws.head_commit is None
        assert ws.branch_name is None
        assert ws.get_diff() == ""
        assert ws.get_changed_files() == []
        assert ws.get_untracked_files() == []
        assert not ws.is_git


def _inside_real_repo(path: Path) -> bool:
    res = subprocess.run(["git", "-C", str(path), "rev-parse", "--git-dir"], capture_output=True, text=True)
    return res.returncode == 0


class TestAncestorDiscoveryMatchesGit:
    """An ancestor `.git` only counts when git itself would accept it as a repository.

    A stray empty `/tmp/.git` (seen on shared CI and dev machines) used to turn every
    tmp directory into a GitWorkspace whose `is_git` was True.
    """

    @pytest.fixture
    def outer(self, tmp_path):
        if _inside_real_repo(tmp_path):
            pytest.skip("tmp_path is inside a real git repository")
        outer = tmp_path / "outer"
        (outer / "proj").mkdir(parents=True)
        return outer

    def test_empty_ancestor_git_dir_is_not_adopted(self, outer):
        (outer / ".git").mkdir()
        proj = outer / "proj"
        assert not _inside_real_repo(proj)  # git agrees: not a repository

        ws = Workspace.resolve(start=proj)
        assert not isinstance(ws, GitWorkspace)
        assert not ws.is_git

        git_ws = GitWorkspace(root=proj)
        assert git_ws.git_dir is None
        assert not git_ws.is_git
        assert git_ws.head_commit is None
        assert git_ws.branch_name is None

    def test_ancestor_git_dir_without_objects_is_not_adopted(self, outer):
        fake = outer / ".git"
        (fake / "refs").mkdir(parents=True)
        (fake / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")

        assert not isinstance(Workspace.for_init(outer / "proj"), GitWorkspace)
        assert not GitWorkspace(root=outer / "proj").is_git

    def test_ancestor_gitfile_to_missing_gitdir_is_not_adopted(self, outer):
        (outer / ".git").write_text(f"gitdir: {outer / 'gone' / '.git'}\n", encoding="utf-8")

        assert not isinstance(Workspace.resolve(start=outer / "proj"), GitWorkspace)
        assert GitWorkspace(root=outer / "proj").git_dir is None

    def test_subdirectory_of_linked_worktree_is_adopted(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-b", "main"], cwd=str(repo), check=True, capture_output=True)
        subprocess.run(["git", "-c", "user.email=t@example.com", "-c", "user.name=T",
                        "commit", "--allow-empty", "-m", "init"], cwd=str(repo), check=True, capture_output=True)
        wt = tmp_path / "wt"
        subprocess.run(["git", "worktree", "add", "-b", "feature", str(wt)], cwd=str(repo), check=True, capture_output=True)
        deep = wt / "pkg" / "deep"
        deep.mkdir(parents=True)

        ws = Workspace.resolve(start=deep)
        assert isinstance(ws, GitWorkspace)
        assert ws.is_git
        assert ws.branch_name == "feature"
        assert ws.git_common_dir == (repo / ".git").resolve()

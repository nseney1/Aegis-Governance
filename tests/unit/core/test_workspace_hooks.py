"""aegis_core.workspace.hooks.resolve_git_hooks_dir: where git runs this repository's hooks."""
from __future__ import annotations

from pathlib import Path
import shutil
import subprocess

import pytest

from aegis_core.workspace.hooks import resolve_git_hooks_dir

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


@pytest.fixture(autouse=True)
def no_user_git_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # A core.hooksPath in the user's own git config must not decide these tests.
    home = tmp_path / "home"
    home.mkdir()
    for name in ("HOME", "USERPROFILE", "XDG_CONFIG_HOME"):
        monkeypatch.setenv(name, str(home))
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(home / ".gitconfig"))


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def test_a_configured_core_hooks_path_is_where_hooks_live(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "core.hooksPath", ".githooks")
    (repo / ".githooks").mkdir()

    assert resolve_git_hooks_dir(repo).resolve() == (repo / ".githooks").resolve()


def test_without_core_hooks_path_hooks_live_in_the_git_dir(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")

    assert resolve_git_hooks_dir(repo).resolve() == (repo / ".git" / "hooks").resolve()


def test_outside_a_repository_there_is_no_hooks_dir(tmp_path: Path):
    assert resolve_git_hooks_dir(tmp_path) is None

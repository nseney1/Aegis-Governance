"""Workspace discovery never makes $HOME a workspace (ADR 0005 AD-4, C-fix T6).

In v4 ``~/.aegis/rules`` is the personal read-only rule layer (H8) and ``~/.aegis`` the
user plane, so neither makes the home directory a governed workspace: not as a marker
the walk-up accepts, not as an operator pin, and not as the root an uninitialized
repository under it falls back to.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from aegis_core.errors import WorkspaceNotFoundError
from aegis_core.workspace.base import Workspace
from aegis_core.workspace.discovery import _is_workspace_dir, resolve_workspace_root


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "home"
    (home / ".aegis" / "rules" / "traps").mkdir(parents=True)
    (home / ".aegis" / "rules" / "traps" / "user-plane.md").write_text(
        "---\nid: user-plane\ntype: trap\n---\nUser rule.\n", encoding="utf-8")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.delenv("AEGIS_WORKSPACE", raising=False)
    return home.resolve()


def _repo(path: Path, initialized: bool = False) -> Path:
    (path / ".git").mkdir(parents=True)
    if initialized:
        (path / ".aegis" / "rules").mkdir(parents=True)
    return path.resolve()


def test_the_user_rule_layer_never_marks_home_as_a_workspace(home):
    assert not _is_workspace_dir(str(home))
    # Spelled another way (a trailing separator, unresolved): still the home directory.
    assert not _is_workspace_dir(str(home) + "/")


def test_a_real_workspace_is_still_one(home, tmp_path):
    assert _is_workspace_dir(str(_repo(tmp_path / "proj", initialized=True)))
    assert not _is_workspace_dir(str(_repo(tmp_path / "bare")))


@pytest.mark.parametrize("how", ["cwd", "start", "caller_file"])
def test_an_uninitialized_repository_under_home_never_resolves_to_home(home, monkeypatch, how):
    repo = _repo(home / "code" / "repo")
    src = repo / "src"
    src.mkdir()
    monkeypatch.chdir(src if how == "cwd" else home.parent)
    kwargs = {"start": src} if how == "start" else ({"caller_file": src / "app.py"} if how == "caller_file" else {})
    root = resolve_workspace_root(**kwargs)
    assert root != home
    # Nothing governs it: the start point (or the cwd, for a caller file) names itself.
    assert root == (home.parent if how == "caller_file" else src)


@pytest.mark.parametrize("strict", [False, True])
def test_a_pin_naming_home_is_refused_not_bound(home, monkeypatch, tmp_path, strict):
    monkeypatch.setenv("AEGIS_WORKSPACE", str(home))
    monkeypatch.chdir(tmp_path)
    with pytest.raises(WorkspaceNotFoundError, match="home directory"):
        resolve_workspace_root(strict_env=strict)
    with pytest.raises(WorkspaceNotFoundError, match="home directory"):
        Workspace.resolve()


def test_a_pin_naming_a_real_workspace_still_binds(home, monkeypatch, tmp_path):
    proj = _repo(tmp_path / "proj", initialized=True)
    monkeypatch.setenv("AEGIS_WORKSPACE", str(proj))
    monkeypatch.chdir(tmp_path)
    assert resolve_workspace_root() == proj

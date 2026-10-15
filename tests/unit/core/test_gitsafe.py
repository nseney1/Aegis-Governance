"""aegis_core.gitsafe: every git subprocess Aegis runs (D20, host-matrix §3.7, v4.3 §10.1)."""
from __future__ import annotations

import ast
import os
from pathlib import Path
import shutil
import stat
import subprocess
import time

import pytest

from aegis_core import gitsafe

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="needs git")

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").exists())


def _git(repo: Path, *args: str) -> str:
    env = dict(os.environ, GIT_CONFIG_NOSYSTEM="1")
    return subprocess.run(
        ["git", "-c", "user.email=t@example.com", "-c", "user.name=T", *args],
        cwd=str(repo), check=True, capture_output=True, text=True, env=env,
    ).stdout


def _repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "-q", "-b", "main")
    return path


def _commit(repo: Path, message: str = "c") -> None:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = _repo(tmp_path / "repo")
    (root / "a.py").write_text("a = 1\n", encoding="utf-8")
    (root / "b.py").write_text("b = 1\n", encoding="utf-8")
    (root / "gone.py").write_text("gone = 1\n", encoding="utf-8")
    (root / ".gitignore").write_text("ignored.txt\n", encoding="utf-8")
    _commit(root, "init")
    return root


# ── Hardening ────────────────────────────────────────────────────────────────

def test_every_call_is_hardened(monkeypatch, tmp_path: Path):
    seen = {}

    def fake_run(argv, **kwargs):
        seen["argv"], seen["kwargs"] = argv, kwargs
        return subprocess.CompletedProcess(argv, 0, b"", b"")

    monkeypatch.setattr(gitsafe.subprocess, "run", fake_run)
    gitsafe.run(["rev-parse", "HEAD"], tmp_path)

    argv, kwargs = seen["argv"], seen["kwargs"]
    assert Path(argv[0]).name.startswith("git")
    assert argv[1:11] == [
        "-c", f"core.hooksPath={os.devnull}",
        "-c", "core.fsmonitor=false",
        "-c", "protocol.allow=never",
        "-c", "core.sshCommand=false",
        "-c", "credential.helper=",
    ]
    assert argv[11:] == ["rev-parse", "HEAD"]
    assert "shell" not in kwargs and kwargs["timeout"] == gitsafe.GIT_TIMEOUT_SECONDS
    env = kwargs["env"]
    assert {k: env[k] for k in ("GIT_CONFIG_NOSYSTEM", "GIT_TERMINAL_PROMPT", "GIT_OPTIONAL_LOCKS",
                                "GIT_NO_REPLACE_OBJECTS", "LC_ALL")} == {
        "GIT_CONFIG_NOSYSTEM": "1", "GIT_TERMINAL_PROMPT": "0", "GIT_OPTIONAL_LOCKS": "0",
        "GIT_NO_REPLACE_OBJECTS": "1", "LC_ALL": "C",
    }


def test_timeout_and_missing_git_raise_git_error(monkeypatch, tmp_path: Path):
    def slow(argv, **kwargs):
        raise subprocess.TimeoutExpired(argv, kwargs["timeout"])

    monkeypatch.setattr(gitsafe.subprocess, "run", slow)
    with pytest.raises(gitsafe.GitError, match="timed out after 0.5s"):
        gitsafe.run(["status"], tmp_path, timeout=0.5)
    assert gitsafe.changed_files(tmp_path) is None  # helpers degrade to "unknown"

    monkeypatch.setattr(gitsafe.shutil, "which", lambda name: None)
    with pytest.raises(gitsafe.GitError, match="git is not installed"):
        gitsafe.run(["status"], tmp_path)


# ── The fsmonitor regression (red team blocker) ──────────────────────────────

def _plant_fsmonitor(repo: Path, marker: Path) -> None:
    hook = repo.parent / "fsmonitor-hook"
    hook.write_text(f'#!/bin/sh\necho ran >> "{marker}"\nexit 1\n', encoding="utf-8")
    hook.chmod(hook.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    _git(repo, "config", "core.fsmonitor", str(hook))


@pytest.fixture
def fsmonitor_repo(repo: Path, tmp_path: Path):
    """A repo whose .git/config runs a marker-writing fsmonitor, with changes in every mode."""
    if os.name == "nt":
        pytest.skip("the marker hook is a POSIX shell script")
    _git(repo, "checkout", "-q", "-b", "feature")
    (repo / "a.py").write_text("a = 2\n", encoding="utf-8")
    _commit(repo, "feature")
    (repo / "b.py").write_text("b = 2\n", encoding="utf-8")
    (repo / "staged.py").write_text("s = 1\n", encoding="utf-8")
    _git(repo, "add", "staged.py")
    (repo / "new.py").write_text("n = 1\n", encoding="utf-8")
    marker = tmp_path / "FSMONITOR_RAN"
    _plant_fsmonitor(repo, marker)
    # Positive control: plain porcelain runs the hook, so the setup is effective.
    subprocess.run(["git", "status", "--porcelain"], cwd=str(repo), capture_output=True)
    if not marker.exists():
        pytest.skip("this git does not run core.fsmonitor hooks from git status")
    marker.unlink()
    return repo, marker


def test_no_gitsafe_call_runs_a_repo_fsmonitor(fsmonitor_repo):
    repo, marker = fsmonitor_repo

    assert sorted(gitsafe.changed_files(repo, "working")) == ["b.py", "staged.py"]
    assert sorted(gitsafe.changed_files(repo, "working", untracked=True)) == ["b.py", "new.py", "staged.py"]
    assert gitsafe.changed_files(repo, "staged") == ["staged.py"]
    assert gitsafe.changed_files(repo, "head") == ["a.py"]
    assert gitsafe.changed_files(repo, "range", base="main") == ["a.py"]
    assert "new.py" in gitsafe.list_files(repo)
    assert gitsafe.read_blob(repo, "HEAD", "a.py") == b"a = 2\n"
    assert gitsafe.toplevel(repo) == repo.resolve()
    assert gitsafe.git_path(repo, "hooks") is not None
    assert gitsafe.head_commit(repo) and gitsafe.merge_base(repo, "main")
    assert gitsafe.resolve_base_ref(repo, environ={}) == "main"

    assert not marker.exists(), "a gitsafe call ran the repository's core.fsmonitor"


def test_aegis_commands_never_run_a_repo_fsmonitor(fsmonitor_repo, monkeypatch, capsys):
    from aegis_cli.cli import main

    repo, marker = fsmonitor_repo
    (repo / ".aegis" / "rules" / "traps").mkdir(parents=True)
    (repo / ".aegis" / "rules" / "traps" / "trap-x.md").write_text(
        "---\nid: trap-x\ntype: trap\nhypothesis: h\ntarget_paths:\n  - '*.py'\n---\nbody\n", encoding="utf-8"
    )
    monkeypatch.chdir(repo)
    monkeypatch.delenv("AEGIS_WORKSPACE", raising=False)

    for argv in (["check"], ["check", "--hook"], ["scan", "--json"], ["status"]):
        try:
            main(argv)
        except SystemExit:
            pass
    capsys.readouterr()

    assert not marker.exists(), "an aegis command ran the repository's core.fsmonitor"


# ── changed_files semantics ──────────────────────────────────────────────────

def test_working_mode_is_head_against_worktree_and_index(repo: Path):
    (repo / "a.py").write_text("a = 2\n", encoding="utf-8")         # modified, unstaged
    (repo / "staged.py").write_text("s\n", encoding="utf-8")         # added, staged
    _git(repo, "add", "staged.py")
    (repo / "untracked.py").write_text("u\n", encoding="utf-8")      # untracked
    (repo / "ignored.txt").write_text("i\n", encoding="utf-8")       # ignored
    (repo / "gone.py").unlink()                                      # deleted: not listed
    past = time.time() + 5
    os.utime(repo / "b.py", (past, past))                            # stat-only change: not listed

    assert sorted(gitsafe.changed_files(repo, "working")) == ["a.py", "staged.py"]
    assert sorted(gitsafe.changed_files(repo, "working", untracked=True)) == ["a.py", "staged.py", "untracked.py"]
    assert gitsafe.changed_files(repo, "staged") == ["staged.py"]


def test_staged_then_reverted_file_is_still_a_working_change(repo: Path):
    (repo / "a.py").write_text("a = 2\n", encoding="utf-8")
    _git(repo, "add", "a.py")
    (repo / "a.py").write_text("a = 1\n", encoding="utf-8")  # the worktree matches HEAD again

    assert gitsafe.changed_files(repo, "working") == ["a.py"]


def test_head_and_range_modes(repo: Path):
    _git(repo, "checkout", "-q", "-b", "topic")
    (repo / "a.py").write_text("a = 3\n", encoding="utf-8")
    _commit(repo, "one")
    (repo / "c.py").write_text("c\n", encoding="utf-8")
    _commit(repo, "two")

    assert gitsafe.changed_files(repo, "head") == ["c.py"]
    assert sorted(gitsafe.changed_files(repo, "range", base="main")) == ["a.py", "c.py"]
    assert gitsafe.changed_files(repo, "range", base="no-such-branch") is None


def test_root_commit_and_unborn_head(tmp_path: Path):
    unborn = _repo(tmp_path / "unborn")
    (unborn / "first.py").write_text("x\n", encoding="utf-8")
    _git(unborn, "add", "first.py")
    assert gitsafe.changed_files(unborn, "staged") == ["first.py"]
    assert gitsafe.changed_files(unborn, "working") == ["first.py"]
    assert gitsafe.changed_files(unborn, "head") is None

    _commit(unborn, "root")
    assert gitsafe.changed_files(unborn, "head") == ["first.py"]


def test_outside_a_repository_nothing_is_known(tmp_path: Path):
    plain = tmp_path / "plain"
    plain.mkdir()
    if gitsafe.toplevel(plain) is not None:
        pytest.skip("tmp_path is inside a git repository")
    assert gitsafe.changed_files(plain) is None
    assert gitsafe.list_files(plain) is None
    assert gitsafe.git_path(plain, "hooks") is None
    assert gitsafe.read_blob(plain, "HEAD", "a.py") is None


def test_invalid_modes_are_rejected(repo: Path):
    with pytest.raises(ValueError, match="mode must be one of"):
        gitsafe.changed_files(repo, "everything")
    with pytest.raises(ValueError, match="needs a base"):
        gitsafe.changed_files(repo, "range")
    assert gitsafe.resolve_commit(repo, "--output=/tmp/x") is None


def test_list_files_under_a_directory(repo: Path):
    (repo / "pkg").mkdir()
    (repo / "pkg" / "m.py").write_text("m\n", encoding="utf-8")
    _commit(repo)
    (repo / "pkg" / "n.py").write_text("n\n", encoding="utf-8")
    (repo / "pkg" / "ignored.txt").write_text("i\n", encoding="utf-8")

    assert sorted(gitsafe.list_files(repo, ["pkg"])) == ["pkg/m.py", "pkg/n.py"]
    assert gitsafe.list_files(repo, ["pkg"], untracked=False) == ["pkg/m.py"]


# ── read_blob ────────────────────────────────────────────────────────────────

def test_read_blob_returns_committed_bytes(repo: Path):
    (repo / "a.py").write_text("a = 9\n", encoding="utf-8")  # the worktree is not what is read
    assert gitsafe.read_blob(repo, "HEAD", "a.py") == b"a = 1\n"
    assert gitsafe.read_blob(repo, "HEAD", "missing.py") is None
    assert gitsafe.read_blob(repo, "no-such-rev", "a.py") is None


def test_read_blob_rejects_content_that_does_not_match_the_object_id(repo: Path, monkeypatch):
    real_run = gitsafe.run

    def tampering_run(args, cwd, **kwargs):
        res = real_run(args, cwd, **kwargs)
        if args and args[0] == "cat-file":
            header, _, body = res.stdout.partition(b"\n")
            forged = b"a = 666\n"
            res = subprocess.CompletedProcess(res.args, 0, header.rsplit(b" ", 1)[0] + b" %d\n" % len(forged) + forged + b"\n", b"")
        return res

    monkeypatch.setattr(gitsafe, "run", tampering_run)
    with pytest.raises(gitsafe.GitError, match="does not match object"):
        gitsafe.read_blob(repo, "HEAD", "a.py")


# ── Other queries ────────────────────────────────────────────────────────────

def test_git_path_honours_the_repository_hooks_path(repo: Path, tmp_path: Path):
    custom = tmp_path / "custom-hooks"
    _git(repo, "config", "core.hooksPath", str(custom))
    assert gitsafe.git_path(repo, "hooks") == custom


def test_resolve_base_ref_prefers_the_pull_request_base(repo: Path):
    _git(repo, "branch", "develop")
    _git(repo, "branch", "release")
    assert gitsafe.resolve_base_ref(repo, environ={"GITHUB_BASE_REF": "release"}) == "release"
    assert gitsafe.resolve_base_ref(repo, environ={}) == "main"
    _git(repo, "branch", "-m", "main", "trunk")
    assert gitsafe.resolve_base_ref(repo, environ={}) == "develop"


# ── Ratchet: no git subprocess outside gitsafe ───────────────────────────────

_SPAWNERS = {
    ("subprocess", "run"), ("subprocess", "check_output"), ("subprocess", "check_call"),
    ("subprocess", "call"), ("subprocess", "Popen"), ("os", "system"), ("os", "popen"),
}


def _is_git_program(node: ast.AST) -> bool:
    """argv[0] of a git call: "git" (a list's first element)."""
    return isinstance(node, ast.Constant) and node.value == "git"


def _is_git_command_line(node: ast.AST) -> bool:
    """A shell command line that runs git ("git status ...")."""
    return isinstance(node, ast.Constant) and isinstance(node.value, str) and (
        node.value == "git" or node.value.startswith("git ")
    )


def test_no_git_subprocess_outside_gitsafe():
    offenders = []
    for pkg in ("aegis_core", "aegis_cli", "aegis_mcp", "aegis_sdk"):
        for path in sorted((ROOT / pkg).rglob("*.py")):
            rel = path.relative_to(ROOT).as_posix()
            if rel == "aegis_core/gitsafe.py":
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            # `binary in ("git", "gh")` names git without running it
            membership = {
                id(comparator)
                for node in ast.walk(tree) if isinstance(node, ast.Compare)
                for op, comparator in zip(node.ops, node.comparators) if isinstance(op, (ast.In, ast.NotIn))
            }
            for node in ast.walk(tree):
                # an argv list or tuple whose program is git
                if isinstance(node, (ast.List, ast.Tuple)) and node.elts and _is_git_program(node.elts[0]) \
                        and id(node) not in membership:
                    offenders.append(f"{rel}:{node.lineno} builds a git argv")
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                        and isinstance(node.func.value, ast.Name) \
                        and (node.func.value.id, node.func.attr) in _SPAWNERS \
                        and node.args and _is_git_command_line(node.args[0]):
                    offenders.append(f"{rel}:{node.lineno} runs git through {node.func.value.id}.{node.func.attr}")
    assert offenders == []

"""aegis_core.gitsafe plumbing reads for the v4.1 team gate and metrics (§1).

``read_object`` (blobs only, size-capped), ``diff_entries`` (every change, deletions,
type changes and gitlinks included), ``merge_tree_conflicted`` (git >= 2.38, never
running a repository's merge driver or filter), ``common_dir`` and ``git_version``.
Every test runs real git in a temp repository unless it fakes git's answer.
"""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
from typing import Optional

import pytest

from aegis_core import gitsafe

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="needs git")


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "user.email=t@example.com", "-c", "user.name=T", *args],
        cwd=str(repo), check=True, capture_output=True, text=True,
    ).stdout


def _init(path: Path, object_format: Optional[str] = None) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    extra = [f"--object-format={object_format}"] if object_format else []
    proc = subprocess.run(["git", "init", "-q", "-b", "main", *extra], cwd=str(path), capture_output=True, text=True)
    if proc.returncode != 0:
        if object_format:
            pytest.skip(f"this git cannot create a {object_format} repository: {proc.stderr.strip()}")
        raise AssertionError(proc.stderr)
    return path


def _write(repo: Path, rel: str, text: str) -> None:
    target = repo / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(text.encode("utf-8"))


def _commit(repo: Path, message: str) -> str:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message)
    return _git(repo, "rev-parse", "HEAD").strip()


@pytest.fixture(params=["sha1", "sha256"])
def repo(request, tmp_path: Path) -> Path:
    root = _init(tmp_path / "repo", None if request.param == "sha1" else "sha256")
    _write(root, "a.txt", "a\n")
    _commit(root, "init")
    return root


@pytest.fixture
def sha1_repo(tmp_path: Path) -> Path:
    root = _init(tmp_path / "repo")
    _write(root, "a.txt", "a\n")
    _commit(root, "init")
    return root


def _needs_merge_tree() -> None:
    version = gitsafe.git_version(Path.cwd())
    if version is None or version < (2, 38):
        pytest.skip(f"git merge-tree --write-tree needs git 2.38, this git is {version}")


# ── git_version ──────────────────────────────────────────────────────────────

def test_git_version_reads_the_running_git(tmp_path: Path):
    version = gitsafe.git_version(tmp_path)
    assert version is not None and len(version) == 3 and version >= (1, 0, 0)


@pytest.mark.parametrize(
    "stdout, expected",
    [
        (b"git version 2.43.0\n", (2, 43, 0)),
        (b"git version 2.39.3 (Apple Git-145)\n", (2, 39, 3)),
        (b"git version 2.45.1.windows.1\n", (2, 45, 1)),
        (b"git version 2.38\n", (2, 38, 0)),
        (b"not git\n", None),
        (b"", None),
    ],
)
def test_git_version_parses_vendor_spellings(tmp_path: Path, monkeypatch, stdout: bytes, expected):
    monkeypatch.setattr(gitsafe, "run", lambda args, cwd, **kw: subprocess.CompletedProcess(args, 0, stdout, b""))
    assert gitsafe.git_version(tmp_path) == expected


# ── read_object ──────────────────────────────────────────────────────────────

def test_read_object_returns_a_blob(repo: Path):
    data = b'{"v":1}\n\x00\xff'
    oid = gitsafe.write_blob(repo, data)
    assert gitsafe.read_object(repo, oid, max_bytes=len(data)) == data


def test_read_object_refuses_anything_but_a_blob(repo: Path):
    commit = _git(repo, "rev-parse", "HEAD").strip()
    tree = _git(repo, "rev-parse", "HEAD^{tree}").strip()
    with pytest.raises(gitsafe.GitError, match=f"object {commit} is a commit, not a blob"):
        gitsafe.read_object(repo, commit, max_bytes=1 << 20)
    with pytest.raises(gitsafe.GitError, match=f"object {tree} is a tree, not a blob"):
        gitsafe.read_object(repo, tree, max_bytes=1 << 20)


def test_read_object_caps_the_size_before_reading(sha1_repo: Path, monkeypatch):
    oid = gitsafe.write_blob(sha1_repo, b"x" * 100)
    real_run = gitsafe.run
    calls = []

    def run(args, cwd, **kwargs):
        calls.append(list(args))
        return real_run(args, cwd, **kwargs)

    monkeypatch.setattr(gitsafe, "run", run)
    with pytest.raises(gitsafe.GitError, match=f"object {oid} is 100 bytes, over the 99-byte cap"):
        gitsafe.read_object(sha1_repo, oid, max_bytes=99)
    assert ["cat-file", "--batch"] not in calls  # the content was never read
    assert gitsafe.read_object(sha1_repo, oid, max_bytes=100) == b"x" * 100


def test_read_object_of_a_missing_object_raises(sha1_repo: Path):
    with pytest.raises(gitsafe.GitError, match=f"object {'1' * 40} is missing"):
        gitsafe.read_object(sha1_repo, "1" * 40, max_bytes=10)


@pytest.mark.parametrize("oid", ["HEAD", "HEAD:a.txt", "abc1234", "A" * 40, "0" * 41, "", "-" * 40, "1" * 39 + "\n"])
def test_read_object_takes_only_a_full_object_id(sha1_repo: Path, oid: str):
    with pytest.raises(ValueError, match="full object id"):
        gitsafe.read_object(sha1_repo, oid, max_bytes=10)


def test_read_object_rejects_content_that_does_not_match_the_object_id(sha1_repo: Path, monkeypatch):
    oid = gitsafe.write_blob(sha1_repo, b"real")
    real_run = gitsafe.run

    def run(args, cwd, **kwargs):
        res = real_run(args, cwd, **kwargs)
        if list(args) == ["cat-file", "--batch"]:
            res = subprocess.CompletedProcess(res.args, 0, res.stdout.replace(b"real", b"fake"), b"")
        return res

    monkeypatch.setattr(gitsafe, "run", run)
    with pytest.raises(gitsafe.GitError, match="does not match"):
        gitsafe.read_object(sha1_repo, oid, max_bytes=10)


def test_read_object_with_a_negative_cap_is_refused(sha1_repo: Path):
    oid = gitsafe.write_blob(sha1_repo, b"")
    with pytest.raises(ValueError, match="max_bytes"):
        gitsafe.read_object(sha1_repo, oid, max_bytes=-1)
    assert gitsafe.read_object(sha1_repo, oid, max_bytes=0) == b""


# ── diff_entries ─────────────────────────────────────────────────────────────

def test_diff_entries_lists_every_change_with_modes(repo: Path):
    for rel in ("a.py", "b.py", "gone.py", "m.sh", "old/name.py"):
        _write(repo, rel, f"# {rel}\n")
    base = _commit(repo, "base")
    _write(repo, "a.py", "# changed\n")
    _write(repo, "new.py", "# new\n")
    _write(repo, "dir/ü.py", "# unicode\n")
    _git(repo, "rm", "-q", "gone.py")
    (repo / "new").mkdir()
    _git(repo, "mv", "old/name.py", "new/name.py")  # a move is a deletion and an addition
    _git(repo, "add", "-A")
    _git(repo, "update-index", "--chmod=+x", "m.sh")
    link_blob = gitsafe.write_blob(repo, b"a.py")
    _git(repo, "rm", "-q", "--cached", "b.py")
    _git(repo, "update-index", "--add", "--cacheinfo", f"120000,{link_blob},b.py")  # file -> symlink
    _git(repo, "update-index", "--add", "--cacheinfo", f"160000,{base},sub")  # a gitlink
    _git(repo, "commit", "-q", "-m", "head")
    head = _git(repo, "rev-parse", "HEAD").strip()

    entries = gitsafe.diff_entries(repo, base, head)
    assert sorted(entries, key=lambda e: e[3]) == [
        ("M", "100644", "100644", "a.py"),
        ("T", "100644", "120000", "b.py"),
        ("A", "000000", "100644", "dir/ü.py"),
        ("D", "100644", "000000", "gone.py"),
        ("M", "100644", "100755", "m.sh"),
        ("A", "000000", "100644", "new.py"),
        ("A", "000000", "100644", "new/name.py"),
        ("D", "100644", "000000", "old/name.py"),
        ("A", "000000", "160000", "sub"),
    ]
    assert gitsafe.diff_entries(repo, head, head) == []
    reverse = {e[3]: e[0] for e in gitsafe.diff_entries(repo, head, base)}
    assert reverse["gone.py"] == "A" and reverse["sub"] == "D" and reverse["b.py"] == "T"


def test_diff_entries_accepts_branch_names_and_trees(sha1_repo: Path):
    base = _git(sha1_repo, "rev-parse", "HEAD").strip()
    _git(sha1_repo, "checkout", "-q", "-b", "side")
    _write(sha1_repo, "b.txt", "b\n")
    _commit(sha1_repo, "side")
    expected = [("A", "000000", "100644", "b.txt")]
    assert gitsafe.diff_entries(sha1_repo, "main", "side") == expected
    assert gitsafe.diff_entries(sha1_repo, f"{base}^{{tree}}", "side^{tree}") == expected


def test_diff_entries_ignores_rename_and_submodule_config(sha1_repo: Path):
    _write(sha1_repo, "old.py", "x = 1\n" * 20)
    base = _commit(sha1_repo, "base")
    _git(sha1_repo, "mv", "old.py", "new.py")
    head = _commit(sha1_repo, "move")
    _git(sha1_repo, "config", "diff.renames", "copies")
    _git(sha1_repo, "config", "diff.ignoreSubmodules", "all")
    assert sorted(gitsafe.diff_entries(sha1_repo, base, head)) == [
        ("A", "000000", "100644", "new.py"),
        ("D", "100644", "000000", "old.py"),
    ]


def test_diff_entries_never_passes_a_revision_as_an_option(sha1_repo: Path, tmp_path: Path):
    planted = tmp_path / "planted.txt"
    for bad in (f"--output={planted}", "-R", "no-such-branch", ""):
        with pytest.raises(gitsafe.GitError, match="cannot resolve"):
            gitsafe.diff_entries(sha1_repo, bad, "HEAD")
        with pytest.raises(gitsafe.GitError, match="cannot resolve"):
            gitsafe.diff_entries(sha1_repo, "HEAD", bad)
    assert not planted.exists()


# ── merge_tree_conflicted ────────────────────────────────────────────────────

@pytest.fixture
def forked(sha1_repo: Path) -> Path:
    """main and two branches off one base: ``conflict`` edits f.txt as main does,
    ``clean`` edits only g.txt."""
    _write(sha1_repo, "f.txt", "base\n")
    _write(sha1_repo, "g.txt", "base\n")
    _commit(sha1_repo, "base")
    _git(sha1_repo, "branch", "conflict")
    _git(sha1_repo, "branch", "clean")
    _write(sha1_repo, "f.txt", "main\n")
    _commit(sha1_repo, "main")
    _git(sha1_repo, "checkout", "-q", "conflict")
    _write(sha1_repo, "f.txt", "conflict\n")
    _commit(sha1_repo, "conflict")
    _git(sha1_repo, "checkout", "-q", "clean")
    _write(sha1_repo, "g.txt", "clean\n")
    _commit(sha1_repo, "clean")
    _git(sha1_repo, "checkout", "-q", "main")
    return sha1_repo


def test_merge_tree_reports_textual_conflicts(forked: Path):
    _needs_merge_tree()
    assert gitsafe.merge_tree_conflicted(forked, "main", "conflict") is True
    assert gitsafe.merge_tree_conflicted(forked, "main", "clean") is False
    assert gitsafe.merge_tree_conflicted(forked, "clean", "conflict") is False


def test_merge_tree_needs_git_2_38(forked: Path, monkeypatch):
    monkeypatch.setattr(gitsafe, "git_version", lambda cwd: (2, 37, 9))
    with pytest.raises(gitsafe.MergeTreeUnavailable) as info:
        gitsafe.merge_tree_conflicted(forked, "main", "conflict")
    assert str(info.value) == "git merge-tree --write-tree needs git 2.38 or later; this git is 2.37.9"
    monkeypatch.setattr(gitsafe, "git_version", lambda cwd: None)
    with pytest.raises(gitsafe.MergeTreeUnavailable, match="cannot tell which git version runs"):
        gitsafe.merge_tree_conflicted(forked, "main", "conflict")


def test_merge_tree_of_unknown_commits_raises(forked: Path):
    _needs_merge_tree()
    for p1, p2 in (("main", "nope"), ("nope", "main"), ("-h", "main"), ("main", "--help")):
        with pytest.raises(gitsafe.GitError, match="cannot resolve"):
            gitsafe.merge_tree_conflicted(forked, p1, p2)


def _shell_command_writing(sentinel: Path) -> str:
    return f"echo ran > '{sentinel.as_posix()}'; exit 1"


def test_merge_tree_never_runs_a_merge_driver_the_repository_config_defines(forked: Path, tmp_path: Path):
    _needs_merge_tree()
    sentinel = tmp_path / "driver-ran"
    _write(forked, ".gitattributes", "* merge=evil\n")
    _commit(forked, "attributes")
    _git(forked, "config", "merge.evil.driver", _shell_command_writing(sentinel))
    with pytest.raises(gitsafe.MergeTreeUnavailable) as info:
        gitsafe.merge_tree_conflicted(forked, "main", "conflict")
    assert str(info.value) == (
        "the repository config defines merge driver evil, which git merge-tree would run; "
        "the merge metric is unavailable here"
    )
    assert not sentinel.exists()
    if os.name == "posix":  # the driver is live: plain git runs it
        subprocess.run(["git", "merge-tree", "--write-tree", "main", "conflict"], cwd=str(forked), capture_output=True)
        assert sentinel.exists()


def test_merge_tree_never_runs_a_filter_the_repository_config_defines(forked: Path, tmp_path: Path):
    _needs_merge_tree()
    sentinel = tmp_path / "filter-ran"
    _write(forked, ".gitattributes", "* filter=evil\n")
    _commit(forked, "attributes")
    _git(forked, "config", "merge.renormalize", "true")
    _git(forked, "config", "filter.evil.clean", f"echo ran > '{sentinel.as_posix()}'; cat")
    _git(forked, "config", "filter.evil.smudge", f"echo ran > '{sentinel.as_posix()}'; cat")
    assert gitsafe.merge_tree_conflicted(forked, "main", "conflict") is True
    assert gitsafe.merge_tree_conflicted(forked, "main", "clean") is False
    assert not sentinel.exists()


def test_merge_tree_failure_is_an_error_not_an_answer(forked: Path, monkeypatch):
    _needs_merge_tree()
    real_run = gitsafe.run

    def run(args, cwd, **kwargs):
        if "merge-tree" in args:
            return subprocess.CompletedProcess(list(args), 128, b"", b"fatal: boom\n")
        return real_run(args, cwd, **kwargs)

    monkeypatch.setattr(gitsafe, "run", run)
    with pytest.raises(gitsafe.GitError, match="git merge-tree failed"):
        gitsafe.merge_tree_conflicted(forked, "main", "conflict")


# ── common_dir ───────────────────────────────────────────────────────────────

def test_common_dir_is_the_shared_git_dir_from_every_worktree(sha1_repo: Path, tmp_path: Path):
    expected = os.path.realpath(sha1_repo / ".git")
    (sha1_repo / "sub" / "deeper").mkdir(parents=True)
    other = tmp_path / "linked"
    _git(sha1_repo, "worktree", "add", "-q", "-b", "lane/x", str(other))
    for where in (sha1_repo, sha1_repo / "sub" / "deeper", other):
        found = gitsafe.common_dir(where)
        assert found is not None and found.is_absolute(), where
        assert os.path.realpath(found) == expected, where
    # --git-path would answer .git/worktrees/linked/... from the linked worktree.
    assert "worktrees" not in Path(os.path.realpath(gitsafe.common_dir(other))).parts


def test_common_dir_outside_a_repository_is_none(tmp_path: Path):
    assert gitsafe.common_dir(tmp_path) is None


def test_read_object_outside_a_repository_raises(tmp_path: Path):
    with pytest.raises(gitsafe.GitError, match=f"git cannot describe object {'1' * 40}"):
        gitsafe.read_object(tmp_path, "1" * 40, max_bytes=10)

"""aegis_core.gitsafe write primitives: blobs and compare-and-swap refs (v4.1 §1).

``write_blob``/``blob_oid`` store and name blobs; ``update_ref`` writes a ref with
``update-ref --stdin`` (create, update or delete, so it is hash-format agnostic) and
classifies a failure by re-reading the ref, never by git's stderr; ``read_ref`` and
``list_refs`` read refs by exact name. Every test runs real git in a temp repository.
"""
from __future__ import annotations

import multiprocessing
import os
from pathlib import Path
import queue
import shutil
import subprocess
from typing import List, Optional

import pytest

from aegis_core import gitsafe
from tests import helpers_gitrace

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="needs git")

LANE = "refs/aegis/lanes/docs"


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
    (path / "a.txt").write_text("a\n", encoding="utf-8")
    _git(path, "add", "-A")
    _git(path, "commit", "-q", "-m", "init")
    return path


@pytest.fixture(params=["sha1", "sha256"])
def repo(request, tmp_path: Path) -> Path:
    return _init(tmp_path / "repo", None if request.param == "sha1" else "sha256")


@pytest.fixture
def sha1_repo(tmp_path: Path) -> Path:
    return _init(tmp_path / "repo")


def _ref_value(repo: Path, ref: str) -> Optional[str]:
    proc = subprocess.run(["git", "show-ref", "--verify", "--hash", ref], cwd=str(repo), capture_output=True, text=True)
    return proc.stdout.strip() if proc.returncode == 0 else None


def _oid_length(repo: Path) -> int:
    return len(_git(repo, "rev-parse", "HEAD").strip())


# ── Blobs ────────────────────────────────────────────────────────────────────

def test_write_blob_stores_the_object_named_by_blob_oid(repo: Path):
    data = b'{"v":1,"lane":"docs"}\n'
    expected = gitsafe.blob_oid(repo, data)
    assert len(expected) == _oid_length(repo)  # the repository's own hash format
    assert subprocess.run(["git", "cat-file", "-e", expected], cwd=str(repo)).returncode != 0  # not written yet
    assert gitsafe.write_blob(repo, data) == expected
    assert _git(repo, "cat-file", "-t", expected).strip() == "blob"
    assert subprocess.run(["git", "cat-file", "blob", expected], cwd=str(repo), capture_output=True).stdout == data


def test_write_blob_stores_bytes_as_given_without_filters(sha1_repo: Path):
    # A repository's attributes never convert a blob written from memory.
    (sha1_repo / ".gitattributes").write_text("* text eol=crlf\n", encoding="utf-8")
    data = b"line one\r\nline two\n\x00binary"
    oid = gitsafe.write_blob(sha1_repo, data)
    assert subprocess.run(["git", "cat-file", "blob", oid], cwd=str(sha1_repo), capture_output=True).stdout == data


def test_write_blob_outside_a_repository_raises(tmp_path: Path):
    with pytest.raises(gitsafe.GitError, match="hash-object"):
        gitsafe.write_blob(tmp_path, b"x")


# ── update_ref: create, update and delete under compare-and-swap ────────────

def test_create_only_claims_once(repo: Path):
    first = gitsafe.write_blob(repo, b"first")
    second = gitsafe.write_blob(repo, b"second")
    gitsafe.update_ref(repo, LANE, first, None)
    assert gitsafe.read_ref(repo, LANE) == first
    with pytest.raises(gitsafe.RefConflict) as info:
        gitsafe.update_ref(repo, LANE, second, None)
    assert (info.value.ref, info.value.expected, info.value.current) == (LANE, None, first)
    assert _ref_value(repo, LANE) == first


def test_update_swaps_only_from_the_expected_value(repo: Path):
    one, two, three = (gitsafe.write_blob(repo, data) for data in (b"1", b"2", b"3"))
    gitsafe.update_ref(repo, LANE, one, None)
    gitsafe.update_ref(repo, LANE, two, one)
    assert _ref_value(repo, LANE) == two
    with pytest.raises(gitsafe.RefConflict) as info:  # stale expectation
        gitsafe.update_ref(repo, LANE, three, one)
    assert (info.value.expected, info.value.current) == (one, two)
    assert _ref_value(repo, LANE) == two


def test_update_of_an_absent_ref_is_a_lost_swap(repo: Path):
    one, two = gitsafe.write_blob(repo, b"1"), gitsafe.write_blob(repo, b"2")
    with pytest.raises(gitsafe.RefConflict) as info:
        gitsafe.update_ref(repo, LANE, two, one)
    assert (info.value.expected, info.value.current) == (one, None)
    assert _ref_value(repo, LANE) is None


def test_delete_needs_the_expected_value(repo: Path):
    one, two = gitsafe.write_blob(repo, b"1"), gitsafe.write_blob(repo, b"2")
    gitsafe.update_ref(repo, LANE, one, None)
    with pytest.raises(gitsafe.RefConflict) as info:
        gitsafe.update_ref(repo, LANE, None, two)
    assert (info.value.expected, info.value.current) == (two, one)
    assert _ref_value(repo, LANE) == one
    gitsafe.update_ref(repo, LANE, None, one)
    assert _ref_value(repo, LANE) is None and gitsafe.read_ref(repo, LANE) is None
    with pytest.raises(gitsafe.RefConflict) as gone:  # already deleted
        gitsafe.update_ref(repo, LANE, None, one)
    assert gone.value.current is None


def test_an_unconditional_write_is_refused_before_git_runs(sha1_repo: Path, monkeypatch):
    monkeypatch.setattr(gitsafe, "run", lambda *a, **k: pytest.fail("git ran"))
    with pytest.raises(ValueError, match="needs a new value, an expected old value, or both"):
        gitsafe.update_ref(sha1_repo, LANE, None, None)


@pytest.mark.parametrize("oid", ["", "HEAD", "abc123", "g" * 40, "A" * 40, "0" * 39, "-" + "0" * 40])
def test_values_must_be_full_object_ids(sha1_repo: Path, oid: str):
    with pytest.raises(ValueError, match="full object id"):
        gitsafe.update_ref(sha1_repo, LANE, oid, None)
    with pytest.raises(ValueError, match="full object id"):
        gitsafe.update_ref(sha1_repo, LANE, None, oid)


@pytest.mark.parametrize(
    "ref",
    [
        "HEAD", "main", "refs", "refs/", "refs/aegis/lanes/", "-refs/aegis/x", "refs/aegis/lanes/a..b",
        "refs/aegis/lanes/a b", "refs/aegis/lanes/a\nb", "refs/aegis/lanes/a\0b", "refs/aegis/lanes/x.lock",
        "refs/aegis/lanes/a*", "refs/aegis/lanes/a?", "refs/aegis/lanes/[a]", "refs/aegis//x", "refs/aegis/x~1",
        "refs/aegis/x^", "refs/aegis/x:y", "refs/aegis/x\\y", "refs/aegis/@{x}", "refs/aegis/.x",
    ],
)
def test_an_invalid_ref_name_is_refused_and_nothing_is_written(sha1_repo: Path, ref: str):
    oid = gitsafe.write_blob(sha1_repo, b"x")
    with pytest.raises(gitsafe.RefNameError, match="invalid ref name"):
        gitsafe.update_ref(sha1_repo, ref, oid, None)
    with pytest.raises(gitsafe.RefNameError):
        gitsafe.read_ref(sha1_repo, ref)
    assert gitsafe.list_refs(sha1_repo, "refs/aegis") == []


def test_a_new_value_that_is_not_in_the_repository_is_not_a_conflict(sha1_repo: Path, monkeypatch):
    sleeps: List[float] = []
    monkeypatch.setattr(gitsafe.time, "sleep", sleeps.append)
    with pytest.raises(gitsafe.GitError, match=f"failed {gitsafe.UPDATE_REF_ATTEMPTS} times") as info:
        gitsafe.update_ref(sha1_repo, LANE, "1" * 40, None)
    assert not isinstance(info.value, gitsafe.RefConflict)
    assert len(sleeps) == gitsafe.UPDATE_REF_ATTEMPTS - 1
    assert _ref_value(sha1_repo, LANE) is None


# ── Failure classification: by the ref's state, never by stderr ─────────────

def _lock_file(repo: Path, ref: str) -> Path:
    if (repo / ".git" / "reftable").exists():
        pytest.skip("the reftable backend has no per-ref lock file")
    lock = repo / ".git" / (ref + ".lock")
    lock.parent.mkdir(parents=True, exist_ok=True)
    return lock


def _misleading_stderr(monkeypatch, text: bytes) -> None:
    """Every update-ref answer keeps its exit code but carries ``text`` as stderr."""
    real_run = gitsafe.run

    def run(args, cwd, **kwargs):
        res = real_run(args, cwd, **kwargs)
        if "update-ref" in args:
            res = subprocess.CompletedProcess(res.args, res.returncode, res.stdout, text)
        return res

    monkeypatch.setattr(gitsafe, "run", run)


def test_a_held_ref_lock_is_transient_and_retried_with_backoff(sha1_repo: Path, monkeypatch):
    lock = _lock_file(sha1_repo, LANE)
    lock.write_bytes(b"")
    oid = gitsafe.write_blob(sha1_repo, b"claim")
    _misleading_stderr(monkeypatch, b"fatal: reference already exists\n")  # a lie: the ref is absent
    sleeps: List[float] = []

    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        if len(sleeps) == 2:
            lock.unlink()  # the other writer finishes

    monkeypatch.setattr(gitsafe.time, "sleep", sleep)
    gitsafe.update_ref(sha1_repo, LANE, oid, None)
    assert _ref_value(sha1_repo, LANE) == oid
    assert sleeps == [gitsafe.UPDATE_REF_BACKOFF_SECONDS, gitsafe.UPDATE_REF_BACKOFF_SECONDS * 2]


def test_a_transient_failure_gives_up_after_bounded_attempts(sha1_repo: Path, monkeypatch):
    lock = _lock_file(sha1_repo, LANE)
    lock.write_bytes(b"")
    oid = gitsafe.write_blob(sha1_repo, b"claim")
    sleeps: List[float] = []
    monkeypatch.setattr(gitsafe.time, "sleep", sleeps.append)
    with pytest.raises(gitsafe.GitError) as info:
        gitsafe.update_ref(sha1_repo, LANE, oid, None)
    assert not isinstance(info.value, gitsafe.RefConflict)
    assert str(info.value).startswith(
        f"git update-ref {LANE} failed {gitsafe.UPDATE_REF_ATTEMPTS} times while the ref still held the expected value"
    )
    assert len(sleeps) == gitsafe.UPDATE_REF_ATTEMPTS - 1
    assert sleeps == sorted(sleeps) and sleeps[-1] == sleeps[0] * 2 ** (len(sleeps) - 1)
    assert _ref_value(sha1_repo, LANE) is None
    assert lock.exists()  # someone else's lock is never removed


def test_a_lost_swap_is_a_conflict_whatever_git_says(sha1_repo: Path, monkeypatch):
    one, two, three = (gitsafe.write_blob(sha1_repo, data) for data in (b"1", b"2", b"3"))
    gitsafe.update_ref(sha1_repo, LANE, one, None)
    gitsafe.update_ref(sha1_repo, LANE, two, one)
    _misleading_stderr(monkeypatch, b"error: cannot lock ref: Unable to create lock: File exists\n")
    monkeypatch.setattr(gitsafe.time, "sleep", lambda s: pytest.fail("a lost swap is never retried"))
    with pytest.raises(gitsafe.RefConflict) as info:
        gitsafe.update_ref(sha1_repo, LANE, three, one)
    assert info.value.current == two


def test_a_lost_acknowledgement_is_detectable_by_the_oid_computed_before_writing(sha1_repo: Path, monkeypatch):
    payload = b'{"v":1,"lane":"docs","claim_id":"9f2c"}'
    oid = gitsafe.blob_oid(sha1_repo, payload)  # known before anything is written
    assert gitsafe.write_blob(sha1_repo, payload) == oid
    real_run = gitsafe.run

    def run(args, cwd, **kwargs):  # the update lands, then git's answer is lost
        res = real_run(args, cwd, **kwargs)
        if "update-ref" in args:
            return subprocess.CompletedProcess(res.args, 128, b"", b"fatal: the remote end hung up\n")
        return res

    monkeypatch.setattr(gitsafe, "run", run)
    with pytest.raises(gitsafe.RefConflict) as info:
        gitsafe.update_ref(sha1_repo, LANE, oid, None)
    assert info.value.current == oid  # the caller's own value: the claim succeeded


def test_a_timeout_whose_write_landed_is_reported_by_state(sha1_repo: Path, monkeypatch):
    oid = gitsafe.write_blob(sha1_repo, b"claim")
    real_run = gitsafe.run

    def run(args, cwd, **kwargs):
        res = real_run(args, cwd, **kwargs)
        if "update-ref" in args:
            raise gitsafe.GitError("git update-ref timed out after 10s")
        return res

    monkeypatch.setattr(gitsafe, "run", run)
    with pytest.raises(gitsafe.RefConflict) as info:
        gitsafe.update_ref(sha1_repo, LANE, oid, None)
    assert info.value.current == oid


def test_a_ref_git_cannot_read_after_a_failure_is_an_error_not_a_guess(sha1_repo: Path, monkeypatch):
    oid = gitsafe.write_blob(sha1_repo, b"claim")
    real_run = gitsafe.run

    def run(args, cwd, **kwargs):
        if "update-ref" in args or "for-each-ref" in args:
            return subprocess.CompletedProcess(list(args), 128, b"", b"")
        return real_run(args, cwd, **kwargs)

    monkeypatch.setattr(gitsafe, "run", run)
    with pytest.raises(gitsafe.GitError, match=f"cannot read {LANE}") as info:
        gitsafe.update_ref(sha1_repo, LANE, oid, None)
    assert not isinstance(info.value, gitsafe.RefConflict)


def test_conflicts_survive_pickling(sha1_repo: Path):
    import pickle

    exc = gitsafe.RefConflict("lost", ref=LANE, expected=None, current="a" * 40)
    copy = pickle.loads(pickle.dumps(exc))
    assert (str(copy), copy.ref, copy.expected, copy.current) == ("lost", LANE, None, "a" * 40)


# ── Racing claims from two worktrees ─────────────────────────────────────────

def test_racing_create_only_claims_from_two_worktrees_have_exactly_one_winner(sha1_repo: Path, tmp_path: Path):
    other = tmp_path / "other"
    _git(sha1_repo, "worktree", "add", "-q", "-b", "lane/other", str(other))
    ctx = multiprocessing.get_context("spawn")
    racers = 6
    for round_no in range(2):
        ref = f"refs/aegis/lanes/race-{round_no}"
        barrier = ctx.Barrier(racers)
        results = ctx.Queue()
        procs = [
            ctx.Process(
                target=helpers_gitrace.claim,
                args=(str(sha1_repo if i % 2 else other), ref, f"racer {round_no}.{i}".encode(), barrier, results),
            )
            for i in range(racers)
        ]
        for proc in procs:
            proc.start()
        try:
            outcomes = [results.get(timeout=120) for _ in procs]
        except queue.Empty:
            pytest.fail("a racer never reported")
        finally:
            for proc in procs:
                proc.join(timeout=60)
                if proc.is_alive():
                    proc.terminate()
        errors = [o for o in outcomes if o[1] == "error"]
        assert errors == []
        winners = [o for o in outcomes if o[1] == "won"]
        assert len(winners) == 1, outcomes
        winner_oid = winners[0][2]
        assert all(o[3] == winner_oid for o in outcomes if o[1] == "lost"), outcomes
        assert _ref_value(sha1_repo, ref) == winner_oid
        assert gitsafe.read_ref(other, ref) == winner_oid  # one ref store for every worktree


# ── Reading refs by exact name ───────────────────────────────────────────────

def test_read_ref_never_guesses_another_ref(sha1_repo: Path):
    head = _git(sha1_repo, "rev-parse", "HEAD").strip()
    # rev-parse would read "refs/aegis/lanes/docs" as refs/heads/refs/aegis/lanes/docs.
    _git(sha1_repo, "update-ref", f"refs/heads/{LANE}", head)
    _git(sha1_repo, "update-ref", f"{LANE}-old", head)
    assert gitsafe.read_ref(sha1_repo, LANE) is None
    oid = gitsafe.write_blob(sha1_repo, b"claim")
    gitsafe.update_ref(sha1_repo, LANE, oid, None)
    assert gitsafe.read_ref(sha1_repo, LANE) == oid
    assert _ref_value(sha1_repo, f"refs/heads/{LANE}") == head


def test_a_symbolic_ref_is_refused_and_never_written_through(sha1_repo: Path):
    head = _git(sha1_repo, "rev-parse", "HEAD").strip()
    _git(sha1_repo, "symbolic-ref", "refs/aegis/lanes/sym", "refs/heads/main")
    with pytest.raises(gitsafe.GitError, match="symbolic ref"):
        gitsafe.read_ref(sha1_repo, "refs/aegis/lanes/sym")
    with pytest.raises(gitsafe.GitError, match="symbolic ref"):
        gitsafe.list_refs(sha1_repo, "refs/aegis/lanes")
    oid = gitsafe.write_blob(sha1_repo, b"claim")
    try:
        gitsafe.update_ref(sha1_repo, "refs/aegis/lanes/sym", oid, head)
    except gitsafe.GitError:
        pass
    assert _ref_value(sha1_repo, "refs/heads/main") == head  # the branch it named is untouched


def test_list_refs_lists_one_hierarchy(repo: Path):
    oids = {name: gitsafe.write_blob(repo, name.encode()) for name in ("docs", "core", "x")}
    gitsafe.update_ref(repo, "refs/aegis/lanes/docs", oids["docs"], None)
    gitsafe.update_ref(repo, "refs/aegis/lanes/core", oids["core"], None)
    gitsafe.update_ref(repo, "refs/aegis/lanesx/x", oids["x"], None)  # shares a string prefix only
    expected = [("refs/aegis/lanes/core", oids["core"]), ("refs/aegis/lanes/docs", oids["docs"])]
    assert gitsafe.list_refs(repo, "refs/aegis/lanes") == expected
    assert gitsafe.list_refs(repo, "refs/aegis/lanes/") == expected
    assert gitsafe.list_refs(repo, "refs/aegis/none") == []
    assert gitsafe.list_refs(repo, "refs/aegis/lanes/docs") == [expected[1]]


@pytest.mark.parametrize("prefix", ["", "HEAD", "refs/aegis/*", "-refs", "refs/a b", "refs/a\nb", "refs/../x", "heads/x"])
def test_list_refs_refuses_a_prefix_that_is_not_a_ref_hierarchy(sha1_repo: Path, prefix: str):
    with pytest.raises(gitsafe.RefNameError, match="invalid ref"):
        gitsafe.list_refs(sha1_repo, prefix)


def test_reading_refs_outside_a_repository_raises(tmp_path: Path):
    with pytest.raises(gitsafe.GitError, match="cannot list"):
        gitsafe.list_refs(tmp_path, "refs/aegis")
    with pytest.raises(gitsafe.GitError, match=f"cannot read {LANE}"):
        gitsafe.read_ref(tmp_path, LANE)


def test_ref_writes_never_run_a_repository_hook(sha1_repo: Path, tmp_path: Path):
    sentinel = tmp_path / "hook-ran"
    hooks = sha1_repo / ".git" / "hooks"
    hooks.mkdir(exist_ok=True)
    hook = hooks / "reference-transaction"
    hook.write_text(f"#!/bin/sh\necho ran > '{sentinel.as_posix()}'\n", encoding="utf-8")
    hook.chmod(0o755)
    oid = gitsafe.write_blob(sha1_repo, b"claim")
    gitsafe.update_ref(sha1_repo, LANE, oid, None)
    gitsafe.update_ref(sha1_repo, LANE, None, oid)
    assert not sentinel.exists()
    if os.name == "posix":  # the hook itself is live: plain git runs it
        _git(sha1_repo, "update-ref", "refs/aegis/probe", oid)
        assert sentinel.exists()

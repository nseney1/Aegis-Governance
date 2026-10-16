"""aegis_core.events: the events log behind the v4.1/v4.2 prune metrics (v4.1 §1).

``<shared_state_dir>/events.jsonl`` under its own ``events.lock``; one row per event::

    {"v": 1, "ts": "<UTC ISO-8601>", "event": <kind>, "worktree": <toplevel>,
     "host": <optional>, "result": <str>, "detail": <object>}

Unknown kinds are refused at append. Readers accept versions N and N-1 (AD-5) and
tolerate, and count, torn lines, unknown versions and malformed rows. Fitness and
compliance never read it, and it never touches ledger.jsonl or activity.jsonl.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import textwrap

import pytest

from aegis_core import events
from aegis_core.errors import PathTraversalError
from aegis_core.storage import LockOrderError, locked, shared_locked

needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="needs git")

REPO_ROOT = str(next(p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").exists()))
TS = re.compile(r"\A\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z\Z")

KINDS = (
    "lease_claimed", "lease_denied", "lane_check", "scan_gate", "guard_match",
    "skills_sync", "partition_check", "pack_import", "init_host", "benchmark",
)


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "user.email=t@example.com", "-c", "user.name=T", *args],
        cwd=str(repo), check=True, capture_output=True, text=True,
    ).stdout


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    (root / "a.txt").write_text("a\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "init")
    return root


def _shared(repo: Path) -> Path:
    return Path(os.path.realpath(repo / ".git")) / "aegis"


def _lines(path: Path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


# ── append ───────────────────────────────────────────────────────────────────

def test_the_kinds_are_the_spec_list():
    assert events.KINDS == KINDS
    assert events.EVENTS_VERSION == 1


@needs_git
def test_append_writes_one_row_to_the_shared_log(repo: Path):
    row = events.append(repo, "lease_claimed", "ok", {"lane": "docs", "paths": ["docs/**"]}, host="claude-code")
    assert set(row) == {"v", "ts", "event", "worktree", "host", "result", "detail"}
    assert TS.match(row["ts"])
    assert {k: v for k, v in row.items() if k != "ts"} == {
        "v": 1, "event": "lease_claimed", "worktree": Path(os.path.realpath(repo)).as_posix(),
        "host": "claude-code", "result": "ok", "detail": {"lane": "docs", "paths": ["docs/**"]},
    }
    assert _lines(_shared(repo) / "events.jsonl") == [row]
    assert (_shared(repo) / "events.lock").is_file()


@needs_git
def test_host_is_omitted_when_not_given(repo: Path):
    row = events.append(repo, "benchmark", "done", {})
    assert "host" not in row
    assert _lines(_shared(repo) / "events.jsonl") == [row]


@needs_git
def test_every_worktree_appends_to_one_log_under_its_own_name(repo: Path, tmp_path: Path):
    linked = tmp_path / "linked"
    _git(repo, "worktree", "add", "-q", "-b", "lane/x", str(linked))
    (repo / "pkg").mkdir()
    first = events.append(repo / "pkg", "lane_check", "pass", {"label": "self-attested"})
    second = events.append(linked, "lease_denied", "refused", {"reason": "overlap"})
    assert first["worktree"] == Path(os.path.realpath(repo)).as_posix()  # the toplevel, not the subdirectory
    assert second["worktree"] == Path(os.path.realpath(linked)).as_posix()
    assert _lines(_shared(repo) / "events.jsonl") == [first, second]
    assert events.read(linked).rows == [first, second]


def test_outside_git_the_log_is_in_the_workspace_state_and_spares_the_other_logs(tmp_path: Path):
    ws = tmp_path / "plain"
    state = ws / ".aegis" / "state"
    state.mkdir(parents=True)
    ledger = state / "ledger.jsonl"
    ledger.write_bytes(b'{"v":2,"seq":1}\n')
    row = events.append(ws, "init_host", "ok", {"host": "codex-cli"}, host="codex-cli")
    assert row["worktree"] == ws.resolve().as_posix()
    assert _lines(state / "events.jsonl") == [row]
    assert ledger.read_bytes() == b'{"v":2,"seq":1}\n'
    assert not (state / "activity.jsonl").exists()


@needs_git
def test_every_spec_kind_is_accepted(repo: Path):
    for kind in KINDS:
        events.append(repo, kind, "ok", {})
    assert [r["event"] for r in events.read(repo).rows] == list(KINDS)


@needs_git
@pytest.mark.parametrize("kind", ["lease", "LEASE_CLAIMED", "", None, "lease_claimed "])
def test_an_unknown_kind_is_refused_and_nothing_is_written(repo: Path, kind):
    with pytest.raises(ValueError) as info:
        events.append(repo, kind, "ok", {})
    assert str(info.value) == f"event kind must be one of {list(KINDS)}, got {kind!r}"
    assert not (_shared(repo) / "events.jsonl").exists()


@needs_git
@pytest.mark.parametrize(
    "result, detail, host, message",
    [
        ("", {}, None, "result must be a non-empty string"),
        (None, {}, None, "result must be a non-empty string"),
        ("ok", None, None, "detail must be a JSON object (a dict)"),
        ("ok", ["x"], None, "detail must be a JSON object (a dict)"),
        ("ok", {}, "", "host must be a non-empty string when given"),
        ("ok", {}, 3, "host must be a non-empty string when given"),
    ],
)
def test_malformed_fields_are_refused_and_nothing_is_written(repo: Path, result, detail, host, message):
    with pytest.raises(ValueError) as info:
        events.append(repo, "scan_gate", result, detail, host=host)
    assert str(info.value) == message
    assert not (_shared(repo) / "events.jsonl").exists()


@needs_git
def test_a_detail_that_is_not_json_writes_nothing(repo: Path):
    with pytest.raises((TypeError, ValueError)):
        events.append(repo, "scan_gate", "ok", {"when": object()})
    with pytest.raises(ValueError):
        events.append(repo, "scan_gate", "ok", {"ratio": float("nan")})
    assert events.read(repo).rows == []


def test_append_inside_the_workspace_lock_keeps_the_lock_order(tmp_path: Path):
    with locked(tmp_path):
        events.append(tmp_path, "benchmark", "ok", {})
    with shared_locked(tmp_path, "other.lock"):
        with pytest.raises(LockOrderError):
            events.append(tmp_path, "benchmark", "ok", {})
    assert len(events.read(tmp_path).rows) == 1


_APPENDER = textwrap.dedent("""
    import sys
    from aegis_core import events
    for i in range(int(sys.argv[2])):
        events.append(sys.argv[1], "guard_match", "blocked", {"writer": sys.argv[3], "i": i, "pad": "x" * 2000})
""")


@needs_git
def test_concurrent_appends_from_two_worktrees_lose_nothing(repo: Path, tmp_path: Path):
    linked = tmp_path / "linked"
    _git(repo, "worktree", "add", "-q", "-b", "lane/x", str(linked))
    env = dict(os.environ)
    env["PYTHONPATH"] = REPO_ROOT + os.pathsep + env.get("PYTHONPATH", "")
    procs = [
        subprocess.Popen(
            [sys.executable, "-c", _APPENDER, str(where), "25", name],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env, cwd=REPO_ROOT,
        )
        for where, name in ((repo, "a"), (linked, "b"), (repo, "c"))
    ]
    for proc in procs:
        _, err = proc.communicate(timeout=120)
        assert proc.returncode == 0, err
    read = events.read(repo)
    assert (read.skipped, read.torn_tail, read.unknown_version, read.malformed) == (0, False, 0, 0)
    assert sorted((r["detail"]["writer"], r["detail"]["i"]) for r in read.rows) == sorted(
        (w, i) for w in "abc" for i in range(25)
    )


# ── read ─────────────────────────────────────────────────────────────────────

def _raw(path: Path, *lines: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "ab") as fh:
        fh.write(b"".join(lines))


def _row(**over) -> bytes:
    row = {"v": 1, "ts": "2026-10-16T12:00:00Z", "event": "scan_gate", "worktree": "/w", "result": "ok", "detail": {}}
    row.update(over)
    return (json.dumps({k: v for k, v in row.items() if v is not _DROP}) + "\n").encode()


_DROP = object()


def test_read_filters_by_kind(tmp_path: Path):
    events.append(tmp_path, "lease_claimed", "ok", {"n": 1})
    events.append(tmp_path, "lease_denied", "refused", {"reason": "overlap"})
    events.append(tmp_path, "lease_claimed", "ok", {"n": 2})
    assert [r["detail"] for r in events.read(tmp_path, kinds=["lease_claimed"]).rows] == [{"n": 1}, {"n": 2}]
    assert [r["event"] for r in events.read(tmp_path, kinds="lease_denied").rows] == ["lease_denied"]
    assert len(events.read(tmp_path, kinds=("lease_denied", "lease_claimed")).rows) == 3
    assert events.read(tmp_path, kinds=[]).rows == []


def test_read_refuses_an_unknown_kind_filter(tmp_path: Path):
    with pytest.raises(ValueError) as info:
        events.read(tmp_path, kinds=["lease_claimed", "lease"])
    assert str(info.value) == f"event kind must be one of {list(KINDS)}, got 'lease'"


def test_read_tolerates_and_counts_bad_lines(tmp_path: Path):
    log = tmp_path / ".aegis" / "state" / "events.jsonl"
    _raw(
        log,
        _row(result="first"),
        b'{"v":1,"ts":"2026-10-16T12:00:0',  # a row torn by a crash ...
        b"\n",  # ... and terminated by the next append
        b"not json\n",
        _row(v=2), _row(v=0), _row(v="1"), _row(v=True), _row(v=_DROP),  # unknown versions
        _row(event="nope"), _row(event=_DROP), _row(result=3), _row(result=_DROP), _row(result=""), _row(detail=[]),
        _row(detail=_DROP), _row(ts="yesterday"), _row(ts=_DROP), _row(worktree=7), _row(host=""),
        _row(host="codex-cli", result="last"),
        b'{"v":1,"ts":"2026',  # torn tail
    )
    read = events.read(tmp_path)
    assert [r["result"] for r in read.rows] == ["first", "last"]
    assert read.skipped == 2
    assert read.torn_tail is True
    assert read.unknown_version == 5
    assert read.malformed == 11
    assert read.error is None


def test_readers_accept_the_current_and_the_previous_version(tmp_path: Path, monkeypatch):
    log = tmp_path / ".aegis" / "state" / "events.jsonl"
    _raw(log, _row(v=1, result="v1"), _row(v=2, result="v2"), _row(v=3, result="v3"))
    assert [r["result"] for r in events.read(tmp_path).rows] == ["v1"]
    monkeypatch.setattr(events, "EVENTS_VERSION", 2)
    read = events.read(tmp_path)
    assert [r["result"] for r in read.rows] == ["v1", "v2"]
    assert read.unknown_version == 1
    assert events.append(tmp_path, "benchmark", "ok", {})["v"] == 2


@needs_git
def test_read_creates_nothing(repo: Path, tmp_path: Path):
    read = events.read(repo)
    assert (read.rows, read.skipped, read.torn_tail, read.error) == ([], 0, False, None)
    assert not _shared(repo).exists()
    plain = tmp_path / "plain"
    plain.mkdir()
    assert events.read(plain).rows == []
    assert not (plain / ".aegis").exists()


@needs_git
def test_read_reports_a_confinement_refusal_without_raising(repo: Path, tmp_path: Path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "events.jsonl").write_bytes(_row())
    try:
        _shared(repo).symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable")
    read = events.read(repo)
    assert read.rows == []
    assert read.error is not None and "it is a symlink" in read.error
    with pytest.raises(PathTraversalError, match="it is a symlink"):
        events.append(repo, "benchmark", "ok", {})
    assert (outside / "events.jsonl").read_bytes() == _row()


@needs_git
@pytest.mark.skipif(
    os.name != "posix" or os.geteuid() == 0, reason="needs POSIX permissions and a user they bind"
)
def test_read_reports_an_unreadable_shared_dir_without_raising(repo: Path):
    events.append(repo, "benchmark", "ok", {})
    _shared(repo).chmod(0)
    try:
        read = events.read(repo)
    finally:
        _shared(repo).chmod(0o700)
    assert read.rows == []
    assert read.error is not None and read.error.startswith("cannot read ") and "Permission denied" in read.error
    assert len(events.read(repo).rows) == 1  # readable again: nothing was lost


def test_fitness_and_compliance_never_read_the_events_log():
    root = Path(REPO_ROOT) / "aegis_core"
    readers = [root / "fitness.py", root / "scan_compliance.py", *sorted((root / "telemetry_engine").glob("*.py"))]
    for path in readers:
        text = path.read_text(encoding="utf-8")
        for needle in ("aegis_core.events", "import events", "events.jsonl", "shared_state_dir"):
            assert needle not in text, f"{path.name} mentions {needle}"

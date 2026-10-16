"""Merging per-worktree ledgers into the shared one (v4.2 #7): ledger.plan_merge / merge_rows.

Rows already in the shared ledger win. A keyed row is the same row as another with its
``(key, rule)``; a keyless row is the same as another with the same canonical row (every
field but ``seq``, which the merge renumbers). Nothing is lost: identical keyless rows
that one source holds several times are separate events and all stay; only copies across
sources, or of what the shared ledger has, are dropped. What is added is numbered
``seq`` in ``(ts, worktree, seq)`` order after the rows already there.
"""
from __future__ import annotations

import json
import multiprocessing
from pathlib import Path
import queue
import shutil
import subprocess
from typing import Dict, List

import pytest

from aegis_core.telemetry_engine import ledger
from tests import helpers_ledgerrace

needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="needs git")


def _row(rule="trap-x", outcome="tp", ts="2026-10-01T00:00:00Z", worktree="/wt/a", seq=1, **extra) -> Dict:
    row = {"v": 2, "seq": seq, "ts": ts, "worktree": worktree, "rule": rule, "outcome": outcome, "source": "ci"}
    row.update(extra)
    return row


def _plan(existing, *sources):
    return ledger.plan_merge(existing, list(sources))


# ── what counts as the same row ──────────────────────────────────────────────

def test_a_keyed_row_is_the_same_row_whatever_else_differs():
    existing = [_row(key="k", seq=7, worktree="/wt/a", host="claude-code", ts="2026-10-01T00:00:00Z")]
    incoming = [_row(key="k", seq=1, worktree="/wt/b", host="codex-cli", ts="2026-10-02T00:00:00Z", outcome="fp")]
    added, duplicates = _plan(existing, incoming)
    assert (added, duplicates) == ([], 1)


def test_the_key_and_the_rule_together_are_the_identity():
    existing = [_row(key="k", rule="trap-x")]
    incoming = [_row(key="k", rule="trap-y"), _row(key="other", rule="trap-x"), _row(key="k", rule="trap-x")]
    added, duplicates = _plan(existing, incoming)
    assert [(r["key"], r["rule"]) for r in added] == [("k", "trap-y"), ("other", "trap-x")]
    assert duplicates == 1


def test_of_a_key_seen_twice_in_the_sources_the_earliest_row_is_kept():
    a = [_row(key="k", ts="2026-10-03T00:00:00Z", worktree="/wt/a", host="late")]
    b = [_row(key="k", ts="2026-10-02T00:00:00Z", worktree="/wt/b", host="early")]
    added, duplicates = _plan([], a, b)
    assert [r["host"] for r in added] == ["early"] and duplicates == 1


def test_an_empty_or_missing_key_is_keyless():
    a = [_row(key="", seq=1), _row(key=None, seq=2), _row(seq=3)]
    added, duplicates = _plan([], a, [_row(seq=4)])
    assert (len(added), duplicates) == (3, 1)  # one source's three events stay; the other source's copy goes


def test_keyless_rows_are_the_same_when_they_differ_only_in_seq():
    existing = [_row(seq=9)]
    assert _plan(existing, [_row(seq=1)]) == ([], 1)
    for field, value in (("ts", "2026-10-09T00:00:00Z"), ("worktree", "/wt/b"), ("rule", "trap-y"),
                         ("outcome", "fp"), ("host", "h"), ("meta", {"n": 1}), ("weight", 0.5)):
        added, duplicates = _plan(existing, [_row(seq=1, **{field: value})])
        assert len(added) == 1 and duplicates == 0, field
    for absent in ({"host": None}, {"session": ""}, {"key": None}, {"key": ""}):
        assert _plan(existing, [_row(seq=1, **absent)]) == ([], 1), absent  # no value is no field


def test_keyless_rows_a_source_holds_twice_are_two_events_and_stay_two():
    twice = [_row(seq=1), _row(seq=2)]
    added, duplicates = _plan([], twice)
    assert len(added) == 2 and duplicates == 0


def test_copies_of_keyless_rows_across_sources_and_of_the_shared_ledger_are_dropped():
    one, two = [_row(seq=1)], [_row(seq=1), _row(seq=2)]
    assert len(_plan([], one, two)[0]) == 2          # the most any one source holds
    assert len(_plan([], two, one)[0]) == 2          # whatever the order
    assert _plan([_row(seq=5)], one, two)[1] == 2    # the shared ledger has one: one more is added
    added, _ = _plan([_row(seq=5)], one, two)
    assert len(added) == 1
    assert _plan([_row(seq=5), _row(seq=6)], one, two) == ([], 3)  # it already has both


def test_planning_again_with_what_was_added_adds_nothing():
    sources = [[_row(key="k1", seq=1), _row(seq=2), _row(seq=3)], [_row(key="k1", seq=1, worktree="/wt/b")]]
    added, duplicates = _plan([], *sources)
    assert (len(added), duplicates) == (3, 1)
    stored = [{**row, "seq": n} for n, row in enumerate(added, 1)]
    assert _plan(stored, *sources) == ([], 4)


# ── order and numbering ──────────────────────────────────────────────────────

def test_what_is_added_is_ordered_by_ts_then_worktree_then_seq():
    rows = [
        _row(key="d", ts="2026-10-02T00:00:00Z", worktree="/wt/a", seq=1),
        _row(key="c", ts="2026-10-01T00:00:00Z", worktree="/wt/b", seq=1),
        _row(key="b", ts="2026-10-01T00:00:00Z", worktree="/wt/a", seq=9),
        _row(key="a", ts="2026-10-01T00:00:00Z", worktree="/wt/a", seq=2),
    ]
    added, _ = _plan([], rows[:2], rows[2:])
    assert [r["key"] for r in added] == ["a", "b", "c", "d"]


def test_rows_without_a_ts_worktree_or_a_usable_seq_sort_first_and_never_fail():
    rows = [
        _row(key="late", ts="2026-10-01T00:00:00Z"),
        {"v": 2, "rule": "r", "outcome": "tp", "source": "ci", "key": "bare"},
        _row(key="bad-seq", ts="2026-10-01T00:00:00Z", worktree="/wt/a", seq="x"),
        _row(key="none-ts", ts=None, worktree=None, seq=True),
    ]
    added, _ = _plan([], rows)
    assert {r["key"] for r in added} == {"late", "bare", "bad-seq", "none-ts"}
    assert [r["key"] for r in added][-1] == "late"


def test_equal_rows_of_the_sort_key_keep_their_source_order():
    a = [_row(key="a1", seq=1), _row(key="a2", seq=1)]
    b = [_row(key="b1", seq=1)]
    added, _ = _plan([], a, b)
    assert [r["key"] for r in added] == ["a1", "a2", "b1"]


# ── merge_rows writes under the one lock, after what is there ────────────────

def test_merge_rows_appends_after_the_existing_rows_and_renumbers(tmp_path: Path):
    ledger.append(tmp_path, [{"rule": "trap-x", "outcome": "tp", "source": "mcp", "key": "have"}])
    sources = [[_row(key="have", seq=40), _row(key="new1", ts="2026-10-02T00:00:00Z", seq=41),
                _row(key="new0", ts="2026-10-01T00:00:00Z", seq=42)]]
    written, duplicates = ledger.merge_rows(tmp_path, sources)
    assert (duplicates, [r["key"] for r in written], [r["seq"] for r in written]) == (1, ["new0", "new1"], [2, 3])
    on_disk = [json.loads(line) for line in ledger.ledger_path(tmp_path).read_text(encoding="utf-8").splitlines()]
    assert [r["seq"] for r in on_disk] == [1, 2, 3]
    assert ledger.merge_rows(tmp_path, sources) == ([], 3)  # a re-run adds nothing
    assert len(ledger.ledger_path(tmp_path).read_text(encoding="utf-8").splitlines()) == 3


def test_merge_rows_keeps_the_worktree_of_each_row(tmp_path: Path):
    written, _ = ledger.merge_rows(tmp_path, [[_row(key="a", worktree="/wt/x")]])
    assert written[0]["worktree"] == "/wt/x"


def test_merge_rows_of_nothing_writes_nothing_and_creates_no_file(tmp_path: Path):
    assert ledger.merge_rows(tmp_path, []) == ([], 0)
    assert ledger.merge_rows(tmp_path, [[]]) == ([], 0)
    assert not ledger.ledger_path(tmp_path).exists()


def test_the_existing_rows_are_read_with_the_lock_held(tmp_path: Path, monkeypatch):
    """A row appended after the caller last looked is still seen: the shared ledger is
    read inside merge_rows, under the lock, not passed in."""
    sources = [[_row(key="k", seq=1)]]
    ledger.append(tmp_path, [{"rule": "trap-x", "outcome": "tp", "source": "mcp", "key": "k"}])
    assert ledger.merge_rows(tmp_path, sources) == ([], 1)


# ── two merges at once ───────────────────────────────────────────────────────

def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "user.email=t@example.com", "-c", "user.name=T", *args],
        cwd=str(repo), check=True, capture_output=True, text=True,
    ).stdout


@needs_git
def test_two_merges_at_once_add_each_row_once(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    (repo / "a.txt").write_text("a\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "init")
    other = tmp_path / "other"
    _git(repo, "worktree", "add", "-q", "-b", "lane/other", str(other))
    sources = [[_row(key=f"k{i}", seq=i, ts=f"2026-10-01T00:00:{i:02d}Z") for i in range(1, 30)]
               + [_row(seq=40 + i) for i in range(3)]]
    ctx = multiprocessing.get_context("spawn")
    barrier, results = ctx.Barrier(2), ctx.Queue()
    procs = [ctx.Process(target=helpers_ledgerrace.merge, args=(str(cwd), sources, barrier, results))
             for cwd in (repo, other)]
    for proc in procs:
        proc.start()
    try:
        outcomes = [results.get(timeout=120) for _ in procs]
    except queue.Empty:
        pytest.fail("a merge never reported")
    finally:
        for proc in procs:
            proc.join(timeout=60)
            if proc.is_alive():
                proc.terminate()
    assert sorted(o[0] for o in outcomes) == [0, 32], outcomes
    rows: List[Dict] = [json.loads(line) for line in ledger.ledger_path(repo).read_text(encoding="utf-8").splitlines()]
    assert [r["seq"] for r in rows] == list(range(1, 33))

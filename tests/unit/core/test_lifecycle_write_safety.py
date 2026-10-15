"""M1 and timestamp regressions for rule-file writes in the lifecycle engine.

Invariants under test (docs/adr/0005-evidence-review.md M1):
- every rule-file mutation waits for ``workspace_lock(RULES)``, the lock that
  promote/demote already hold;
- every rule-file write is atomic: when the filesystem refuses the final
  write, the rules directory is byte-identical to before (no truncated rule,
  no stray temp file, no half-finished move);
- once a demotion has moved the rule out of the gate tier, the old tier's
  enforcement artifacts are removed even if the write step reports an error
  afterwards;
- persisted lifecycle timestamps are one valid UTC ISO-8601 form;
- the existence checks that promote/demote/metamorphose run before taking the
  lock are repeated under it, so a rival create or move that lands in between
  is never overwritten and never crashes the second mover;
- the tier pass and the selection pass change only the rules that need it
  and hold the rules lock per rule, not for the whole pass; selection re-reads
  each rule under the lock, never revisits the queues it moves rules into and
  never overwrites a rule already archived or queued under the same name.
"""
from __future__ import annotations

import builtins
import errno
import hashlib
import io
import json
import os
import re
import subprocess
import sys
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import pytest

from conftest import REPO_ROOT

import aegis_core.lifecycle.promotion as promotion
import aegis_core.lifecycle.selection as selection
from aegis_core.lifecycle import (
    adapt_cell,
    create_cell,
    demote_cell,
    evaluate_cell_tiers,
    metamorphose_cell,
    promote_cell,
    run_cell_selection,
    transfer_cell,
)
from aegis_core.yaml import parse_frontmatter

_UTC_TS = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


def _rule(path: Path, rule_id: str, rule_type: str, triggers: int = 0, tp: int = 0, fp: int = 0) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"---\nid: {rule_id}\ntype: {rule_type}\nenforcement: advisory\nimpact_weight: 1.0\n"
        f"fitness:\n  triggers: {triggers}\n  true_positives: {tp}\n  false_positives: {fp}\n"
        f"---\n# {rule_id}\nBody text.\n",
        encoding="utf-8",
    )
    return path


def _snapshot(directory: Path) -> list[tuple[str, str]]:
    out = []
    for dirpath, _dirs, files in os.walk(directory):
        for name in files:
            full = Path(dirpath) / name
            out.append((full.relative_to(directory).as_posix(), hashlib.sha256(full.read_bytes()).hexdigest()))
    return sorted(out)


# ── Scenarios: (locked workspace, operation) ────────────────────────────

def _ws(tmp_path: Path, name: str = "ws") -> Path:
    ws = tmp_path / name
    (ws / ".aegis" / "rules").mkdir(parents=True)
    return ws


def _scenario_create(tmp_path: Path):
    ws = _ws(tmp_path)
    return ws, lambda: create_cell("trap", "Locked create", id_override="locked-create", workspace=ws)


def _scenario_transfer(tmp_path: Path):
    src = _ws(tmp_path, "src")
    _rule(src / ".aegis" / "rules" / "traps" / "moving.md", "moving", "trap")
    dest = _ws(tmp_path, "dest")
    return dest, lambda: transfer_cell("moving", str(dest), source_workspace=src)


def _scenario_selection(tmp_path: Path):
    ws = _ws(tmp_path)
    _rule(ws / ".aegis" / "rules" / "traps" / "quiet.md", "quiet", "trap")
    return ws, lambda: run_cell_selection(ws, execute=True)


def _scenario_tiers(tmp_path: Path):
    ws = _ws(tmp_path)
    _rule(ws / ".aegis" / "rules" / "traps" / "tiered.md", "tiered", "trap")
    return ws, lambda: evaluate_cell_tiers(ws, execute=True)


def _scenario_tier_escalation(tmp_path: Path):
    ws = _ws(tmp_path)
    # 30 -> 28 triggers after decay: still >= 20, so advisory escalates to mechanical.
    _rule(ws / ".aegis" / "rules" / "traps" / "proven.md", "proven", "trap", triggers=30, tp=30)
    return ws, lambda: evaluate_cell_tiers(ws, execute=True)


def _scenario_metamorphose(tmp_path: Path):
    ws = _ws(tmp_path)
    _rule(ws / ".aegis" / "rules" / "traps" / "mature.md", "mature", "trap", triggers=20, tp=20)
    return ws, lambda: metamorphose_cell(ws, "mature")


def _scenario_adapt(tmp_path: Path):
    ws = _ws(tmp_path)
    _rule(ws / ".aegis" / "rules" / "traps" / "middling.md", "middling", "trap", triggers=10, tp=5, fp=5)
    return ws, lambda: adapt_cell(ws, generate=True)


_SCENARIOS = {
    "create": _scenario_create,
    "transfer": _scenario_transfer,
    "selection": _scenario_selection,
    "tiers": _scenario_tiers,
    "tier_escalation": _scenario_tier_escalation,
    "metamorphose": _scenario_metamorphose,
    "adapt": _scenario_adapt,
}

_LOCK_HOLDER = r"""
import hashlib, os, sys, time
from pathlib import Path
from aegis_core.locking import workspace_lock
from aegis_core.workspace.layout import LockResource

def snap(root):
    out = []
    for dirpath, _d, files in os.walk(root):
        for name in files:
            p = os.path.join(dirpath, name)
            with open(p, "rb") as fh:
                out.append((os.path.relpath(p, root), hashlib.sha256(fh.read()).hexdigest()))
    return sorted(out)

ws, rules, hold = Path(sys.argv[1]), sys.argv[2], float(sys.argv[3])
with workspace_lock(ws, LockResource.RULES):
    before = snap(rules)
    print("locked", flush=True)
    time.sleep(hold)
    print("same" if snap(rules) == before else "changed", flush=True)
"""


@pytest.mark.parametrize("scenario", sorted(_SCENARIOS))
def test_rule_writes_wait_for_the_rules_lock(tmp_path: Path, scenario: str) -> None:
    locked_ws, operation = _SCENARIOS[scenario](tmp_path)
    rules_dir = locked_ws / ".aegis" / "rules"
    before = _snapshot(rules_dir)
    env = dict(os.environ, PYTHONPATH=REPO_ROOT, HOME=str(tmp_path / "home"), USERPROFILE=str(tmp_path / "home"))
    proc = subprocess.Popen(
        [sys.executable, "-c", _LOCK_HOLDER, str(locked_ws), str(rules_dir), "1.0"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env,
    )
    try:
        # The holder exits (EOF) on its own 5 s lock timeout, so this cannot hang.
        first = proc.stdout.readline().strip()
        assert first == "locked", proc.stderr.read()
        operation()
        out, err = proc.communicate(timeout=15)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
    assert out.strip() == "same", f"{scenario} wrote rules while another process held the rules lock"
    assert _snapshot(rules_dir) != before, f"{scenario} did not change the rules directory"


@pytest.mark.parametrize("scenario", sorted(_SCENARIOS))
def test_failed_final_write_leaves_rules_untouched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, scenario: str
) -> None:
    locked_ws, operation = _SCENARIOS[scenario](tmp_path)
    rules_dir = locked_ws / ".aegis" / "rules"
    before = _snapshot(rules_dir)

    def refuse(src, dst):
        raise OSError(errno.EIO, "simulated I/O error on final rename")

    monkeypatch.setattr(os, "replace", refuse)
    with pytest.raises(OSError, match="simulated I/O error"):
        operation()
    monkeypatch.undo()

    assert _snapshot(rules_dir) == before


@pytest.mark.parametrize("scenario", sorted(_SCENARIOS))
def test_rule_files_are_never_rewritten_in_place(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, scenario: str
) -> None:
    """A plain open(..., "w") on a rule truncates it first; a crash then leaves a broken rule."""
    locked_ws, operation = _SCENARIOS[scenario](tmp_path)
    rules_dir = (locked_ws / ".aegis" / "rules").resolve()
    in_place: list[tuple[str, str]] = []
    real_open = builtins.open

    def spy(file, mode="r", *args, **kwargs):
        if isinstance(file, (str, os.PathLike)) and any(flag in mode for flag in "wax+"):
            target = Path(os.fspath(file)).resolve()
            if rules_dir in target.parents:
                in_place.append((target.relative_to(rules_dir).as_posix(), mode))
        return real_open(file, mode, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", spy)
    monkeypatch.setattr(io, "open", spy)
    operation()
    monkeypatch.undo()

    assert in_place == []


def test_tier_escalation_records_its_enforcement_artifact(tmp_path: Path) -> None:
    ws, operation = _scenario_tier_escalation(tmp_path)

    res = operation()

    assert [(c["cell"], c["old_tier"], c["new_tier"]) for c in res["changes"]] == [("proven.md", "advisory", "mechanical")]
    meta = parse_frontmatter((ws / ".aegis" / "rules" / "traps" / "proven.md").read_text(encoding="utf-8")) or {}
    assert meta["enforcement"] == "mechanical"
    assert meta["enforcement_artifact"] == ".aegis/enforcement/check-proven.sh"
    artifact = ws / ".aegis" / "enforcement" / "check-proven.sh"
    assert artifact.is_file() and os.access(artifact, os.X_OK)


# ── Demotion artifact cleanup across a post-move failure ────────────────

def _invariant_with_artifacts(ws: Path) -> tuple[Path, list[Path]]:
    source = _rule(ws / ".aegis" / "rules" / "invariants" / "guarded.md", "guarded", "invariant")
    enf = ws / ".aegis" / "enforcement"
    enf.mkdir(parents=True)
    artifacts = [enf / "gate-guarded.py", enf / "check-guarded.sh"]
    for art in artifacts:
        art.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    return source, artifacts


def test_demote_cleans_artifacts_when_writer_fails_after_the_move(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ws = _ws(tmp_path)
    source, artifacts = _invariant_with_artifacts(ws)
    real_writer = promotion._atomic_write_and_unlink

    def move_then_fail(src, dst, content):
        real_writer(src, dst, content)
        raise RuntimeError("post-move failure")

    monkeypatch.setattr(promotion, "_atomic_write_and_unlink", move_then_fail)
    with pytest.raises(RuntimeError, match="post-move failure"):
        demote_cell(ws, "guarded")

    assert not source.exists()
    assert (ws / ".aegis" / "rules" / "traps" / "guarded.md").is_file()
    assert [a.name for a in artifacts if a.exists()] == []


def test_demote_keeps_artifacts_when_writer_fails_before_the_move(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ws = _ws(tmp_path)
    source, artifacts = _invariant_with_artifacts(ws)

    def fail_before_move(src, dst, content):
        raise RuntimeError("pre-move failure")

    monkeypatch.setattr(promotion, "_atomic_write_and_unlink", fail_before_move)
    with pytest.raises(RuntimeError, match="pre-move failure"):
        demote_cell(ws, "guarded")

    assert source.is_file()
    assert not (ws / ".aegis" / "rules" / "traps" / "guarded.md").exists()
    assert all(a.exists() for a in artifacts), "rule is still an invariant; its gate artifacts must stay"


# ── Timestamps ─────────────────────────────────────────────────────────

def _assert_utc(ts: object) -> None:
    assert isinstance(ts, str) and _UTC_TS.match(ts), f"malformed UTC timestamp: {ts!r}"
    datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ")


def test_selection_writes_valid_utc_timestamps(tmp_path: Path) -> None:
    ws = _ws(tmp_path)
    rule = _rule(ws / ".aegis" / "rules" / "traps" / "quiet.md", "quiet", "trap")

    assert run_cell_selection(ws, execute=True) == 0

    meta = parse_frontmatter(rule.read_text(encoding="utf-8")) or {}
    _assert_utc(meta.get("dormant_since"))
    log_lines = (ws / ".aegis" / "evidence" / "lifecycle.jsonl").read_text(encoding="utf-8").splitlines()
    entry = json.loads(log_lines[-1])
    assert entry["action"] == "marked_dormant"
    _assert_utc(entry["timestamp"])


def test_metamorphose_writes_valid_utc_timestamp(tmp_path: Path) -> None:
    ws = _ws(tmp_path)
    _rule(ws / ".aegis" / "rules" / "traps" / "mature.md", "mature", "trap", triggers=20, tp=20)

    res = metamorphose_cell(ws, "mature")

    assert res["status"] == "metamorphosed"
    moved = ws / ".aegis" / "rules" / "invariants" / "mature.md"
    meta = parse_frontmatter(moved.read_text(encoding="utf-8")) or {}
    _assert_utc(meta.get("metamorphosis_date"))


# ── Interleavings: a rival lands between the unlocked checks and the lock ──

def _rival_on_first_lock(monkeypatch: pytest.MonkeyPatch, rival, module=promotion) -> None:
    """Run ``rival`` just before the lifecycle engine's first rules-lock acquisition.

    This is the window a concurrent process gets between promote/demote's
    unlocked existence checks and their locked move.
    """
    real_lock = module.workspace_lock
    pending = [rival]

    @contextmanager
    def lock_after_rival(*args, **kwargs):
        if pending:
            pending.pop()()
        with real_lock(*args, **kwargs) as held:
            yield held

    monkeypatch.setattr(module, "workspace_lock", lock_after_rival)


def _rival_rule(path: Path, marker: str) -> None:
    """A rule another writer (a second Aegis process, a git checkout) lands meanwhile.

    create_cell refuses an id that is already active in any tier, so the rival
    writes the file directly.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\nid: {path.stem}\ntype: rival\n---\n{marker}\n", encoding="utf-8")


def _rules(ws: Path) -> Path:
    return ws / ".aegis" / "rules"


def test_promote_never_overwrites_a_rule_created_in_the_target_tier_meanwhile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ws = _ws(tmp_path)
    source = _rule(_rules(ws) / "traps" / "shared-id.md", "shared-id", "trap")
    _rival_on_first_lock(monkeypatch, lambda: _rival_rule(_rules(ws) / "invariants" / "shared-id.md", "Rival invariant"))

    res = promote_cell(ws, "shared-id", force=True)

    assert res["status"] == "target_exists"
    assert "Rival invariant" in (_rules(ws) / "invariants" / "shared-id.md").read_text(encoding="utf-8")
    assert source.is_file()


def test_concurrent_promotes_of_one_rule_promote_it_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ws = _ws(tmp_path)
    _rule(_rules(ws) / "traps" / "once.md", "once", "trap")
    rival: list[dict] = []
    _rival_on_first_lock(monkeypatch, lambda: rival.append(promote_cell(ws, "once", force=True)))

    res = promote_cell(ws, "once", force=True)

    assert rival[0]["status"] == "promoted"
    assert res["status"] == "not_found"
    assert (_rules(ws) / "invariants" / "once.md").is_file()
    assert not (_rules(ws) / "gates" / "once.md").exists()


def test_demote_never_overwrites_a_trap_created_meanwhile(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ws = _ws(tmp_path)
    source, artifacts = _invariant_with_artifacts(ws)
    _rival_on_first_lock(monkeypatch, lambda: _rival_rule(_rules(ws) / "traps" / "guarded.md", "Rival trap"))

    res = demote_cell(ws, "guarded")

    assert res["status"] == "target_exists"
    assert "Rival trap" in (_rules(ws) / "traps" / "guarded.md").read_text(encoding="utf-8")
    assert source.is_file()
    assert all(a.exists() for a in artifacts), "the invariant did not move; its gate artifacts must stay"


def test_concurrent_demotes_of_one_rule_demote_it_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ws = _ws(tmp_path)
    _invariant_with_artifacts(ws)
    rival: list[dict] = []
    _rival_on_first_lock(monkeypatch, lambda: rival.append(demote_cell(ws, "guarded")))

    res = demote_cell(ws, "guarded")

    assert rival[0]["status"] == "demoted"
    assert res["status"] == "not_found"
    assert (_rules(ws) / "traps" / "guarded.md").is_file()


def test_metamorphose_never_overwrites_a_rule_created_in_the_target_tier_meanwhile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ws = _ws(tmp_path)
    source = _rule(_rules(ws) / "traps" / "mature.md", "mature", "trap", triggers=20, tp=20)
    _rival_on_first_lock(monkeypatch, lambda: _rival_rule(_rules(ws) / "invariants" / "mature.md", "Rival invariant"))

    res = metamorphose_cell(ws, "mature")

    assert res["status"] == "target_exists"
    assert "Rival invariant" in (_rules(ws) / "invariants" / "mature.md").read_text(encoding="utf-8")
    assert source.is_file()


def test_metamorphose_of_a_rule_moved_meanwhile_reports_not_found(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ws = _ws(tmp_path)
    _rule(_rules(ws) / "traps" / "mature.md", "mature", "trap", triggers=20, tp=20)
    _rival_on_first_lock(monkeypatch, lambda: promote_cell(ws, "mature", force=True))

    res = metamorphose_cell(ws, "mature")

    assert res["status"] == "not_found"
    assert (_rules(ws) / "invariants" / "mature.md").is_file()


# ── Tier pass: rewrite only what changes, lock only while rewriting ─────

_LOCK_HOLDER_UNTIL_EOF = r"""
import sys
from pathlib import Path
from aegis_core.locking import workspace_lock
from aegis_core.workspace.layout import LockResource

with workspace_lock(Path(sys.argv[1]), LockResource.RULES):
    print("locked", flush=True)
    sys.stdin.read()
"""


def test_tier_pass_does_not_rewrite_unchanged_rules(tmp_path: Path) -> None:
    ws = _ws(tmp_path)
    rules = [_rule(_rules(ws) / "traps" / f"steady-{i}.md", f"steady-{i}", "trap") for i in range(3)]
    evaluate_cell_tiers(ws, execute=True)
    stamps = [(p.stat().st_ino, p.stat().st_mtime_ns) for p in rules]

    res = evaluate_cell_tiers(ws, execute=True)

    assert res == {"evaluated": 3, "changes": []}
    assert [(p.stat().st_ino, p.stat().st_mtime_ns) for p in rules] == stamps


def test_tier_pass_with_nothing_to_change_does_not_wait_for_the_rules_lock(tmp_path: Path) -> None:
    ws = _ws(tmp_path)
    _rule(_rules(ws) / "traps" / "steady.md", "steady", "trap")
    evaluate_cell_tiers(ws, execute=True)
    before = _snapshot(_rules(ws))
    env = dict(os.environ, PYTHONPATH=REPO_ROOT, HOME=str(tmp_path / "home"), USERPROFILE=str(tmp_path / "home"))
    holder = subprocess.Popen(
        [sys.executable, "-c", _LOCK_HOLDER_UNTIL_EOF, str(ws)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env,
    )
    try:
        assert holder.stdout.readline().strip() == "locked", holder.stderr.read()
        # Needing the lock here would raise LockTimeoutError after 5 s.
        res = evaluate_cell_tiers(ws, execute=True)
    finally:
        holder.stdin.close()
        try:
            holder.wait(timeout=15)
        finally:
            if holder.poll() is None:
                holder.kill()
                holder.wait()

    assert res == {"evaluated": 1, "changes": []}
    assert _snapshot(_rules(ws)) == before


def test_tier_pass_keeps_a_concurrent_edit_to_the_rule_it_rewrites(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Rules are read before the lock; the rewrite must start from what is on disk under it."""
    ws = _ws(tmp_path)
    rule = _rule(_rules(ws) / "traps" / "edited.md", "edited", "trap")

    def edit() -> None:
        rule.write_text(rule.read_text(encoding="utf-8").replace("Body text.", "Edited concurrently."), encoding="utf-8")

    _rival_on_first_lock(monkeypatch, edit)

    evaluate_cell_tiers(ws, execute=True)

    text = rule.read_text(encoding="utf-8")
    assert "Edited concurrently." in text
    assert "last_decay_epoch" in ((parse_frontmatter(text) or {}).get("fitness") or {})


# ── Selection pass: per-rule lock, re-read under it, no revisits, no overwrites ──

def _dormant(path: Path, rule_id: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"---\nid: {rule_id}\ntype: trap\ndormant_since: '2026-01-01T00:00:00Z'\n---\n# {rule_id}\n",
        encoding="utf-8",
    )
    return path


def _log_actions(ws: Path) -> list[tuple[str, str]]:
    log = ws / ".aegis" / "evidence" / "lifecycle.jsonl"
    if not log.exists():
        return []
    return [(e["cell"], e["action"]) for e in map(json.loads, log.read_text(encoding="utf-8").splitlines())]


def test_selection_with_nothing_to_change_does_not_wait_for_the_rules_lock(tmp_path: Path) -> None:
    ws = _ws(tmp_path)
    _rule(_rules(ws) / "traps" / "strong.md", "strong", "trap", triggers=10, tp=10)
    _dormant(_rules(ws) / "traps" / "asleep.md", "asleep")
    before = _snapshot(_rules(ws))
    env = dict(os.environ, PYTHONPATH=REPO_ROOT, HOME=str(tmp_path / "home"), USERPROFILE=str(tmp_path / "home"))
    holder = subprocess.Popen(
        [sys.executable, "-c", _LOCK_HOLDER_UNTIL_EOF, str(ws)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env,
    )
    try:
        assert holder.stdout.readline().strip() == "locked", holder.stderr.read()
        # Needing the lock here would raise LockTimeoutError after 5 s.
        rc = run_cell_selection(ws, execute=True)
    finally:
        holder.stdin.close()
        try:
            holder.wait(timeout=15)
        finally:
            if holder.poll() is None:
                holder.kill()
                holder.wait()

    assert rc == 0
    assert _snapshot(_rules(ws)) == before
    assert _log_actions(ws) == []


def test_selection_takes_the_rules_lock_once_per_changed_rule(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A pass over hundreds of rules must not hold the lock across all of them (finding F5)."""
    ws = _ws(tmp_path)
    for name in ("quiet-a", "quiet-b", "quiet-c"):
        _rule(_rules(ws) / "traps" / f"{name}.md", name, "trap")
    _rule(_rules(ws) / "traps" / "strong.md", "strong", "trap", triggers=10, tp=10)
    real_lock = selection.workspace_lock
    depth: list[int] = []
    held = [0]

    @contextmanager
    def counting_lock(*args, **kwargs):
        held[0] += 1
        depth.append(held[0])
        try:
            with real_lock(*args, **kwargs) as h:
                yield h
        finally:
            held[0] -= 1

    monkeypatch.setattr(selection, "workspace_lock", counting_lock)

    assert run_cell_selection(ws, execute=True) == 0

    assert depth == [1, 1, 1]
    assert sorted(_log_actions(ws)) == [(f"quiet-{x}.md", "marked_dormant") for x in "abc"]


def test_selection_acts_on_the_rule_as_it_is_under_the_lock(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The rule is classified unlocked; an edit landing before the lock must win."""
    ws = _ws(tmp_path)
    rule = _rule(_rules(ws) / "traps" / "revived.md", "revived", "trap", triggers=10, tp=0)
    _rival_on_first_lock(
        monkeypatch, lambda: _rule(rule, "revived", "trap", triggers=10, tp=10), module=selection
    )

    assert run_cell_selection(ws, execute=True) == 0

    assert rule.is_file(), "a rule that became healthy before the lock must not be archived"
    assert not (_rules(ws) / ".archive" / "revived.md").exists()
    assert _log_actions(ws) == []


def test_selection_skips_a_rule_moved_away_meanwhile(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ws = _ws(tmp_path)
    rule = _rule(_rules(ws) / "traps" / "doomed.md", "doomed", "trap", triggers=10, tp=0)
    moved = _rules(ws) / "invariants" / "doomed.md"

    def move_away() -> None:
        moved.parent.mkdir(parents=True, exist_ok=True)
        rule.rename(moved)

    _rival_on_first_lock(monkeypatch, move_away, module=selection)

    assert run_cell_selection(ws, execute=True) == 0

    assert moved.is_file()
    assert not (_rules(ws) / ".archive" / "doomed.md").exists()
    assert _log_actions(ws) == []


def test_selection_never_revisits_the_last_gasp_queue(tmp_path: Path, capsys) -> None:
    ws = _ws(tmp_path)
    _rule(_rules(ws) / "traps" / "noisy.md", "noisy", "trap", triggers=10, tp=1, fp=5)
    queue = _rules(ws) / ".last_gasp_queue"
    waiting = _rule(queue / "waiting.md", "waiting", "trap", triggers=10, tp=0)

    run_cell_selection(ws, execute=True)
    queued = _snapshot(queue)
    run_cell_selection(ws, execute=True)

    out = capsys.readouterr().out
    assert _log_actions(ws) == [("noisy.md", "last_gasp_requested")]
    assert _snapshot(queue) == queued
    assert waiting.is_file(), "queued rules belong to the last-gasp sentinel, not to selection"
    assert out.count("noisy.md") == 1
    assert "waiting.md" not in out


@pytest.mark.parametrize(
    "fitness, queue, action",
    [((10, 0, 0), ".archive", "moved_to_archive"), ((10, 1, 5), ".last_gasp_queue", "last_gasp_requested")],
    ids=["archive", "last_gasp"],
)
def test_selection_never_overwrites_a_rule_already_parked_under_the_same_name(
    tmp_path: Path, fitness: tuple[int, int, int], queue: str, action: str
) -> None:
    ws = _ws(tmp_path)
    earlier = _rules(ws) / queue / "reused.md"
    earlier.parent.mkdir(parents=True)
    earlier.write_text("---\nid: reused\ntype: trap\n---\nThe earlier rule.\n", encoding="utf-8")
    triggers, tp, fp = fitness
    current = _rule(_rules(ws) / "traps" / "reused.md", "reused", "trap", triggers=triggers, tp=tp, fp=fp)
    current_text = current.read_text(encoding="utf-8")

    run_cell_selection(ws, execute=True)

    assert not current.exists()
    assert earlier.read_text(encoding="utf-8") == "---\nid: reused\ntype: trap\n---\nThe earlier rule.\n"
    assert (_rules(ws) / queue / "reused.1.md").read_text(encoding="utf-8") == current_text
    assert _log_actions(ws) == [("reused.md", action)]


def test_selection_runs_in_a_workspace_whose_path_contains_archive(tmp_path: Path) -> None:
    ws = _ws(tmp_path / "old.archive", "ws")
    rule = _rule(_rules(ws) / "traps" / "quiet.md", "quiet", "trap")

    run_cell_selection(ws, execute=True)

    assert "dormant_since" in (parse_frontmatter(rule.read_text(encoding="utf-8")) or {})
    assert _log_actions(ws) == [("quiet.md", "marked_dormant")]

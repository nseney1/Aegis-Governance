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
- persisted lifecycle timestamps are one valid UTC ISO-8601 form.
"""
from __future__ import annotations

import errno
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pytest

from conftest import REPO_ROOT

import aegis_core.lifecycle.promotion as promotion
from aegis_core.lifecycle import (
    adapt_cell,
    create_cell,
    demote_cell,
    evaluate_cell_tiers,
    metamorphose_cell,
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

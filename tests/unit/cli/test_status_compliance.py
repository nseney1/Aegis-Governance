"""``aegis status --compliance``: the per-host scan-before-edit rate (ADR 0005 AD-9).

Read from the MCP activity log (``.aegis/state/activity.jsonl``: scan events, report
``files`` edit events) plus commits that fall in exactly one session's window. The
output is machine-readable with explicit host and session scope, never a PASS, and
reports missing coverage as unknown. Reading it writes nothing.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from aegis_cli.cli import main


def _tree(root: Path) -> list:
    out = []
    for dirpath, dirs, files in os.walk(root):
        for name in dirs:
            out.append((Path(dirpath, name).relative_to(root).as_posix() + "/", ""))
        for name in files:
            full = Path(dirpath, name)
            out.append((full.relative_to(root).as_posix(), hashlib.sha256(full.read_bytes()).hexdigest()))
    return sorted(out)


@pytest.fixture
def ws(tmp_path, monkeypatch) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    root = tmp_path / "ws"
    (root / ".aegis" / "rules" / "traps").mkdir(parents=True)
    monkeypatch.chdir(root)
    return root.resolve()


def _event(event, session, host, files, ts, **extra):
    return {"v": 1, "ts": ts, "event": event, "host": host, "session": session, "files": files,
            "client": {"name": host, "version": "1"}, **extra}


def _write(ws: Path, rows) -> None:
    state = ws / ".aegis" / "state"
    state.mkdir(parents=True, exist_ok=True)
    with open(state / "activity.jsonl", "w", encoding="utf-8") as fh:
        for row in rows:
            fh.write((row if isinstance(row, str) else json.dumps(row)) + "\n")


def _keys(value):
    if isinstance(value, dict):
        for key, inner in value.items():
            yield key
            yield from _keys(inner)
    elif isinstance(value, list):
        for inner in value:
            yield from _keys(inner)


def _report(capsys, *extra):
    rc = main(["status", "--compliance", "--json", *extra])
    assert rc == 0
    return json.loads(capsys.readouterr().out)


def test_rates_are_per_session_and_aggregated_per_host(ws, capsys):
    _write(ws, [
        _event("scan", "s1", "claude-code", ["src/a.py", "src/b.py"], "2026-10-15T10:00:00Z"),
        _event("edit", "s1", "claude-code", ["src/a.py", "src/c.py"], "2026-10-15T10:05:00Z"),
        _event("scan", "s2", "claude-code", ["src/d.py"], "2026-10-15T11:00:00Z"),
        _event("edit", "s2", "claude-code", ["src/d.py"], "2026-10-15T11:01:00Z"),
        _event("edit", "s3", "codex-cli", ["src/e.py"], "2026-10-15T12:00:00Z"),
        _event("scan", "s3", "codex-cli", ["src/e.py"], "2026-10-15T12:10:00Z"),  # scanned after the edit
    ])

    report = _report(capsys)

    sessions = {s["session"]: s for s in report["sessions"]}
    assert (sessions["s1"]["edits_observed"], sessions["s1"]["scanned_before_edit"], sessions["s1"]["rate"]) == (2, 1, 0.5)
    assert (sessions["s2"]["rate"], sessions["s3"]["rate"]) == (1.0, 0.0)
    assert {s["scope"] for s in report["sessions"]} == {"session"}
    hosts = {h["host"]: h for h in report["hosts"]}
    assert hosts["claude-code"] == {
        "scope": "host_aggregate", "host": "claude-code", "sessions": 2, "sessions_measured": 2,
        "edits_observed": 3, "scanned_before_edit": 2, "rate": round(2 / 3, 4), "rate_status": "measured",
    }
    assert (hosts["codex-cli"]["rate"], hosts["codex-cli"]["rate_status"]) == (0.0, "measured")


def test_no_observed_edits_is_unknown_never_zero(ws, capsys):
    _write(ws, [_event("scan", "s1", "antigravity", ["a.py"], "2026-10-15T10:00:00Z")])

    report = _report(capsys)

    (session,) = report["sessions"]
    assert (session["edits_observed"], session["rate"], session["rate_status"]) == (0, None, "unknown")
    assert session["unknown_reason"] == "no edits observed in this session"
    (host,) = report["hosts"]
    assert (host["rate"], host["rate_status"], host["sessions_measured"]) == (None, "unknown", 0)


def test_the_output_is_scoped_versioned_and_never_a_pass(ws, capsys):
    _write(ws, [
        _event("scan", "s1", "claude-code", ["a.py"], "2026-10-15T10:00:00Z"),
        _event("edit", "s1", "claude-code", ["a.py"], "2026-10-15T10:01:00Z"),
    ])

    report = _report(capsys)

    assert report["schema"] == "aegis.compliance/v1"
    assert report["source"] == "aegis status --compliance"
    assert report["aegis_version"]
    assert report["checked_at"].endswith("Z") and len(report["checked_at"]) == 20
    assert report["scope"] == {"workspace": str(ws), "hosts": ["claude-code"], "sessions": ["s1"],
                               "since": "2026-10-15T10:00:00Z", "until": "2026-10-15T10:01:00Z"}
    assert report["stale"] is False
    assert report["metric"] == "scan_before_edit"
    assert not [k for k in _keys(report) if any(word in k.lower() for word in ("pass", "verdict", "ok"))]


def test_an_empty_workspace_reports_unknown_with_empty_scope(ws, capsys):
    report = _report(capsys)
    assert (report["hosts"], report["sessions"]) == ([], [])
    assert report["scope"]["hosts"] == [] and report["scope"]["since"] is None
    assert report["activity"] == {"path": ".aegis/state/activity.jsonl", "rows": 0, "skipped": 0}


def test_unusable_activity_rows_are_counted_not_used(ws, capsys):
    _write(ws, [
        "{torn",
        {"v": 9, "event": "scan"},
        _event("scan", "", "claude-code", ["a.py"], "2026-10-15T10:00:00Z"),
        _event("scan", "s1", "claude-code", "a.py", "2026-10-15T10:00:00Z"),
        _event("scan", "s1", "claude-code", ["a.py"], "yesterday"),
        _event("scan", "s1", "claude-code", ["a.py"], "2026-10-15T10:00:00Z"),
    ])
    report = _report(capsys)
    assert report["activity"] == {"path": ".aegis/state/activity.jsonl", "rows": 1, "skipped": 5}


def test_reading_compliance_writes_nothing(ws, capsys):
    _write(ws, [_event("scan", "s1", "claude-code", ["a.py"], "2026-10-15T10:00:00Z")])
    before = _tree(ws)
    _report(capsys)
    assert main(["status", "--compliance"]) == 0
    capsys.readouterr()
    assert _tree(ws) == before


def test_the_text_view_lists_hosts_and_explains_the_heuristic(ws, capsys):
    _write(ws, [
        _event("scan", "s1", "claude-code", ["a.py"], "2026-10-15T10:00:00Z"),
        _event("edit", "s1", "claude-code", ["a.py", "b.py"], "2026-10-15T10:01:00Z"),
        _event("scan", "s2", "codex-cli", ["a.py"], "2026-10-15T10:00:00Z"),
    ])
    assert main(["status", "--compliance"]) == 0
    out = capsys.readouterr().out
    assert "claude-code" in out and "50%" in out
    assert "codex-cli" in out and "unknown" in out
    assert "aggregate" in out.lower() and "not a per-attempt" in out


def test_the_flag_help_documents_the_heuristic_and_its_limits(capsys):
    with pytest.raises(SystemExit):
        main(["status", "--help"])
    out = " ".join(capsys.readouterr().out.split())
    for phrase in ("aegis_report_outcome", "commit", "upper bound", "unknown", "overlapping"):
        assert phrase in out, phrase


def test_compliance_outside_a_workspace_fails_cleanly(tmp_path, monkeypatch, capsys):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    plain = tmp_path / "plain"
    plain.mkdir()
    monkeypatch.chdir(plain)
    assert main(["status", "--compliance", "--json"]) == 1
    assert f"not an Aegis workspace (no .aegis/ in {plain.resolve()})" in capsys.readouterr().err


# ── commits in a session window ──────────────────────────────────────────────

def _git(repo: Path, *args, date=None):
    env = dict(os.environ)
    if date:
        env.update(GIT_AUTHOR_DATE=date, GIT_COMMITTER_DATE=date)
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "commit.gpgsign=false", *args],
                   cwd=repo, check=True, capture_output=True, env=env)


def _commit(repo: Path, name: str, date: str):
    path = repo / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{name} {date}\n", encoding="utf-8")
    _git(repo, "add", name)
    _git(repo, "commit", "-q", "-m", name, date=date)


@pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")
def test_commits_inside_one_session_window_count_as_edits(ws, capsys):
    _git(ws, "init", "-q")
    _commit(ws, "base.txt", "2026-10-15T09:00:00Z")
    _write(ws, [
        _event("scan", "s1", "claude-code", ["src/a.py"], "2026-10-15T10:00:00Z"),
        _event("scan", "s1", "claude-code", ["README.md"], "2026-10-15T10:20:00Z"),
        _event("scan", "s2", "codex-cli", ["x.py"], "2026-10-15T13:00:00Z"),
        _event("scan", "s3", "antigravity", ["y.py"], "2026-10-15T13:05:00Z"),
    ])
    _commit(ws, "src/a.py", "2026-10-15T10:10:00Z")     # s1 scanned it first
    _commit(ws, "src/b.py", "2026-10-15T10:30:00Z")     # inside s1's grace window, never scanned
    _commit(ws, "late.py", "2026-10-15T11:00:00Z")      # outside every window
    _commit(ws, "both.py", "2026-10-15T13:06:00Z")      # s2 and s3 overlap: ambiguous

    report = _report(capsys)

    sessions = {s["session"]: s for s in report["sessions"]}
    assert (sessions["s1"]["edits_observed"], sessions["s1"]["scanned_before_edit"]) == (2, 1)
    assert sessions["s1"]["edit_sources"] == {"report": 0, "git": 2}
    assert sessions["s2"]["rate_status"] == sessions["s3"]["rate_status"] == "unknown"
    assert report["git"] == {"status": "used", "ambiguous_edits": 1, "grace_seconds": 900}


def test_without_git_the_window_heuristic_is_unavailable_not_zero(ws, capsys, monkeypatch):
    from aegis_core import gitsafe

    monkeypatch.setattr(gitsafe, "toplevel", lambda cwd: None)
    _write(ws, [_event("scan", "s1", "claude-code", ["a.py"], "2026-10-15T10:00:00Z")])
    report = _report(capsys)
    assert report["git"]["status"] == "unavailable"
    assert report["sessions"][0]["rate_status"] == "unknown"

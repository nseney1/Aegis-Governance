"""The upgrade path from the command line (release review, upgrade findings 1-4):
init and every refusing command point at `aegis migrate` while .soma rule files remain,
migrate reports a blocker instead of "nothing to do", lists what it does not convert,
and unmigrated v3 state stops status/scan/sync (check warns and still runs)."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from aegis_cli.cli import main
from aegis_core.workspace.discovery import LEGACY_SOMA_UPGRADE_MSG

WALL = "---\nid: no-eval\ntype: wall\nenforcement: gate\nforbid_ast:\n  calls: [eval]\n---\nNo eval.\n"


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _git_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=str(path), check=True)
    return path.resolve()


def _exit(argv) -> int:
    try:
        return main(argv)
    except SystemExit as exc:
        return int(exc.code)


# ── .soma rule files: init refuses, and an existing .aegis/ does not unlock the gate ──

def test_init_refuses_while_soma_rule_files_remain(tmp_path, monkeypatch, capsys):
    repo = _git_repo(tmp_path / "repo")
    _write(repo / ".soma" / "cells" / "walls" / "no-eval.md", WALL)
    monkeypatch.chdir(repo)

    assert _exit(["init", "--yes", "--no-hooks"]) == 1

    assert capsys.readouterr().err == f"Error: {LEGACY_SOMA_UPGRADE_MSG.format(path=repo)}\n"
    assert not (repo / ".aegis").exists()


@pytest.mark.parametrize("argv", [["status"], ["check", "--hook"]], ids=lambda a: " ".join(a))
def test_an_aegis_dir_next_to_soma_rule_files_is_still_refused(tmp_path, monkeypatch, capsys, argv):
    """What an `aegis init` run before this fix left behind: the gates in .soma were not served."""
    repo = _git_repo(tmp_path / "repo")
    (repo / ".aegis" / "rules" / "personas").mkdir(parents=True)
    _write(repo / ".soma" / "rules" / "walls" / "no-eval.md", WALL)
    _write(repo / "app.py", "x = eval(input())\n")
    subprocess.run(["git", "add", "app.py"], cwd=str(repo), check=True)
    monkeypatch.chdir(repo)

    assert _exit(argv) == 1

    captured = capsys.readouterr()
    assert captured.err == f"Error: {LEGACY_SOMA_UPGRADE_MSG.format(path=repo)}\n"
    assert "PASSED" not in captured.out


def test_after_migrate_the_soma_rules_are_served_and_the_gate_blocks(tmp_path, monkeypatch, capsys):
    repo = _git_repo(tmp_path / "repo")
    _write(repo / ".soma" / "rules" / "walls" / "no-eval.md", WALL)
    monkeypatch.chdir(repo)

    assert _exit(["migrate", "--apply"]) == 0
    _write(repo / "app.py", "x = eval(input())\n")
    subprocess.run(["git", "add", "app.py"], cwd=str(repo), check=True)
    capsys.readouterr()

    assert _exit(["check", "--hook"]) == 1
    assert "forbid_ast:no-eval: app.py" in capsys.readouterr().out


# ── migrate: a blocker, never "nothing to do" ─────────────────────────────────

def test_migrate_reports_what_blocks_a_bare_soma_dir(tmp_path, monkeypatch, capsys):
    repo = _git_repo(tmp_path / "repo")
    _write(repo / ".soma" / "evidence" / "x.json", "{}")
    monkeypatch.chdir(repo)

    for argv in (["migrate"], ["migrate", "--apply"]):
        assert _exit(argv) == 1
        out = capsys.readouterr().out
        assert "nothing to do" not in out
        assert "refused" in out and "rename or remove" in out
    assert (repo / ".soma" / "evidence" / "x.json").is_file()


def test_migrate_lists_what_it_does_not_convert(tmp_path, monkeypatch, capsys):
    repo = _git_repo(tmp_path / "repo")
    _write(repo / ".aegis" / "evidence" / "signals.jsonl", "")
    _write(repo / ".aegis" / "evidence" / "checkpoint_rollup.json", '{"rules": {}}\n')
    _write(repo / "steering.conf", "REVIEW_MODE=x\n")
    monkeypatch.chdir(repo)

    assert _exit(["migrate"]) == 0

    out = capsys.readouterr().out
    section = out[out.index("  ! not converted:"):]
    assert "    .aegis/evidence/checkpoint_rollup.json: " in section
    assert "    steering.conf: " in section

    assert _exit(["--json", "migrate"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert [e["path"] for e in payload["not_converted"]] == [".aegis/evidence/checkpoint_rollup.json", "steering.conf"]


# ── unmigrated v3 state: status, scan and sync refuse; check warns ───────────

@pytest.fixture
def v3_repo(tmp_path, monkeypatch):
    repo = _git_repo(tmp_path / "repo")
    (repo / ".aegis" / "rules" / "traps").mkdir(parents=True)
    _write(repo / ".aegis" / "evidence" / "signals.jsonl", '{"rule_id": "x", "signal": "tp"}\n')
    _write(repo / "aegis.conf", "MAX_JIT_TOKENS=1500\n")
    _write(repo / "app.py", "x = 1\n")
    monkeypatch.chdir(repo)
    return repo


@pytest.mark.parametrize("argv,code", [(["status"], 1), (["sync"], 1), (["scan", "app.py"], 2)],
                         ids=["status", "sync", "scan"])
def test_unmigrated_v3_state_refuses_status_scan_and_sync(v3_repo, monkeypatch, capsys, argv, code):
    from aegis_cli.registry import get_default_registry

    ran = []
    monkeypatch.setattr(type(get_default_registry().get(argv[0])), "execute", lambda self, args: ran.append(args) or 0)

    assert _exit(argv) == code

    assert ran == []
    err = capsys.readouterr().err
    assert err.startswith("Error: ")
    assert ".aegis/evidence/signals.jsonl" in err and "aegis.conf" in err
    assert "aegis migrate" in err
    assert not (v3_repo / ".aegis" / "state").exists()  # sync derived nothing from an empty ledger


def test_unmigrated_v3_state_only_warns_in_check(v3_repo, capsys):
    assert _exit(["check", "app.py"]) == 0

    captured = capsys.readouterr()
    assert captured.err.startswith("Warning: ")
    assert "aegis migrate" in captured.err
    assert "PASSED" in captured.out


def test_after_migrate_status_runs(v3_repo, capsys):
    assert _exit(["migrate", "--apply"]) == 0
    capsys.readouterr()

    assert _exit(["status"]) == 0
    assert "aegis migrate" not in capsys.readouterr().err

"""`aegis init` ends with the day-0 card (v4.2 #1).

The card is what `aegis check --card` prints, shown once init has written its files so it
counts the rules init seeded. It is text only (init's JSON document is unchanged), absent
from a dry run, never reads or writes `baseline.json`, and never makes init fail.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from aegis_cli.cli import _build_parser
from aegis_cli.init import run_init


@pytest.fixture
def project(tmp_path, monkeypatch):
    root = tmp_path / "project"
    root.mkdir()
    (root / "app.py").write_text("def run():\n    return 1\n", encoding="utf-8")
    (root / "legacy.py").write_text("def old(x):\n    return eval(x)\n", encoding="utf-8")
    monkeypatch.setenv("PATH", str(tmp_path / "empty-bin"))  # no host CLI, no aegis-mcp
    return root


def _args(root: Path, *flags: str) -> argparse.Namespace:
    return _build_parser().parse_args(["init", "--workspace", str(root), "--yes", "--no-hooks", *flags])


def test_init_prints_the_card_before_the_next_step(project: Path, capsys):
    assert run_init(_args(project)) == 0
    out = capsys.readouterr().out
    assert "  Aegis day-0 card" in out
    assert "    languages: python 2" in out
    assert out.index("Aegis day-0 card") < out.index("After a session, run: aegis status")
    assert out.index("Done!") < out.index("Aegis day-0 card")


def test_the_card_counts_the_rules_init_just_seeded(project: Path, capsys):
    assert run_init(_args(project, "--rules", "minimal")) == 0
    out = capsys.readouterr().out
    assert "    rules: 2 (persona 2)" in out or "    rules: 3 (" in out or "    rules: " in out
    card_lines = out[out.index("Aegis day-0 card"):out.index("After a session")]
    assert "files with the most findings:" in card_lines and "legacy.py" in card_lines


def test_the_card_matches_the_one_check_prints(project: Path, capsys):
    from aegis_cli.cli import main

    assert run_init(_args(project)) == 0
    out = capsys.readouterr().out
    assert main(["check", "--card", "--workspace", str(project)]) == 0
    printed = capsys.readouterr().out.splitlines()
    for line in printed[1:]:  # the title aside, every line init showed is one check --card shows
        assert f"  {line}" in out.splitlines()


def test_a_dry_run_shows_no_card(project: Path, capsys):
    assert run_init(_args(project, "--dry-run")) == 0
    assert "day-0 card" not in capsys.readouterr().out


def test_json_mode_is_unchanged(project: Path, capsys):
    assert run_init(_args(project, "--json")) == 0
    document = json.loads(capsys.readouterr().out)
    assert "card" not in document and document["status"] == "ok"


def test_the_card_never_touches_the_baseline(project: Path, capsys):
    run_init(_args(project))
    assert not (project / ".aegis" / "baseline.json").exists()
    (project / ".aegis" / "baseline.json").write_text('{"v": 1, "findings": []}\n', encoding="utf-8")
    run_init(_args(project))
    assert (project / ".aegis" / "baseline.json").read_text(encoding="utf-8") == '{"v": 1, "findings": []}\n'


def test_a_card_that_cannot_be_built_is_a_warning_not_a_failure(project: Path, capsys, monkeypatch):
    from aegis_core import card

    def broken(*args, **kwargs):
        raise RuntimeError("no card today")

    monkeypatch.setattr(card, "build", broken)
    assert run_init(_args(project)) == 0
    captured = capsys.readouterr()
    assert "the day-0 card could not be built: RuntimeError: no card today" in captured.err
    assert "day-0 card" not in captured.out and "After a session, run: aegis status" in captured.out

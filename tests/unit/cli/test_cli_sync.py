"""`aegis sync [--apply] [--json]` (ADR 0005 D1): rebuild derived state, suggest, apply on request.

Exit codes: 0 when the view was rebuilt (and every requested move applied), 1 when a
rule file cannot be loaded or applying was refused or failed, 2 for a usage or
workspace error. With --json, stdout carries only the JSON document.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from aegis_cli.cli import main
from aegis_core.telemetry_engine import ledger


def _rule(ws: Path, directory: str, rule_type: str, rule_id: str) -> Path:
    path = ws / ".aegis" / "rules" / directory / f"{rule_id}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    enforcement = "gate" if rule_type == "invariant" else "advisory"
    path.write_text(
        f"---\nid: {rule_id}\ntype: {rule_type}\nenforcement: {enforcement}\nhypothesis: h\n"
        "created: '2026-01-01'\ntarget_paths: ['src/*.py']\n---\nBody.\n",
        encoding="utf-8",
    )
    return path


@pytest.fixture
def ws(tmp_path, monkeypatch):
    root = tmp_path / "project"
    _rule(root, "traps", "trap", "trap-good")
    _rule(root, "personas", "persona", "persona-quiet")
    ledger.append(root, [{"rule": "trap-good", "outcome": "tp", "source": "ci", "key": f"k{i}"} for i in range(25)])
    monkeypatch.chdir(root)
    return root


def _rule_files(ws: Path) -> dict:
    rules = ws / ".aegis" / "rules"
    return {p.relative_to(rules).as_posix(): p.read_bytes() for p in sorted(rules.rglob("*.md"))}


def test_sync_prints_a_table_of_suggestions_and_writes_derived_state(ws, capsys):
    before = _rule_files(ws)

    rc = main(["sync"])

    out = capsys.readouterr().out
    assert rc == 0
    for column in ("Rule", "Type", "Fitness", "Triggers", "TP", "FP", "Suggestion"):
        assert column in out
    assert "trap-good" in out and "promote" in out and "persona-quiet" in out
    assert "aegis sync --apply" in out
    assert (ws / ".aegis" / "state" / "derived.json").is_file()
    assert _rule_files(ws) == before


def test_sync_json_is_machine_readable(ws, capsys):
    rc = main(["sync", "--json"])

    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload["status"] == "synced"
    assert payload["path"] == ".aegis/state/derived.json"
    rows = {r["id"]: r for r in payload["rules"]}
    assert rows["trap-good"]["suggestion"] == "promote" and rows["trap-good"]["triggers"] == 25
    assert rows["persona-quiet"]["suggestion"] is None
    assert payload["applied"] == [] and payload["errors"] == [] and payload["ignored"] == []


def test_apply_moves_the_suggested_rules(ws, capsys):
    rc = main(["sync", "--apply", "--json"])

    payload = json.loads(capsys.readouterr().out)
    assert rc == 0 and payload["status"] == "applied"
    assert [(a["rule"], a["action"], a["status"]) for a in payload["applied"]] == [("trap-good", "promote", "promoted")]
    assert (ws / ".aegis" / "rules" / "invariants" / "trap-good.md").is_file()


def test_apply_text_mode_reports_each_move(ws, capsys):
    rc = main(["sync", "--apply"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "promote trap-good: promoted (trap -> invariant)" in out


def test_a_broken_rule_is_reported_and_exits_1(ws, capsys):
    (ws / ".aegis" / "rules" / "traps" / "broken.md").write_text("---\nid: [x\n---\n", encoding="utf-8")

    rc = main(["sync", "--json"])

    payload = json.loads(capsys.readouterr().out)
    assert rc == 1 and payload["status"] == "errors"
    assert payload["errors"] == [{"path": ".aegis/rules/traps/broken.md", "error": "malformed YAML frontmatter: unterminated flow sequence"}]


def test_apply_with_a_broken_rule_is_refused_and_moves_nothing(ws, capsys):
    (ws / ".aegis" / "rules" / "traps" / "broken.md").write_text("---\nid: [x\n---\n", encoding="utf-8")
    before = _rule_files(ws)

    rc = main(["sync", "--apply"])

    captured = capsys.readouterr()
    assert rc == 1
    assert "not applied" in captured.out + captured.err
    assert _rule_files(ws) == before


def test_outside_an_aegis_workspace_sync_exits_2(tmp_path, monkeypatch, capsys):
    plain = tmp_path / "plain"
    plain.mkdir()
    monkeypatch.chdir(plain)

    rc = main(["sync", "--workspace", str(plain)])

    assert rc == 2
    assert "not an Aegis workspace" in capsys.readouterr().err


def test_sync_text_never_prints_terminal_escapes_from_rule_files(ws, capsys):
    traps = ws / ".aegis" / "rules" / "traps"
    try:
        (traps / "evil\x1b]0;pwned\x07.md").write_text("---\ntype: trap\n---\n", encoding="utf-8")
    except (OSError, ValueError):
        pytest.skip("this filesystem refuses control characters in file names")
    (traps / "broken.md").write_text("---\nid: [x\n---\n", encoding="utf-8")

    assert main(["sync"]) == 1

    out = capsys.readouterr().out
    assert "\x1b]" not in out and "\x07" not in out
    assert "evil" in out and "broken.md" in out

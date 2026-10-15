"""`aegis scan FILE... [--json]`: which rules apply to these files (v4 replacement for `agent scan`).

Exit codes are part of the contract: 0 when the scan ran (with or without
matches), 2 for a usage or workspace error. Runs against real scratch
workspaces; nothing in the JIT engine is patched.
"""
from __future__ import annotations

import json
import shlex
from pathlib import Path

import pytest

from aegis_cli.cli import _build_parser, main


def _workspace(root: Path) -> Path:
    traps = root / ".aegis" / "rules" / "traps"
    traps.mkdir(parents=True)
    (traps / "trap-src-python.md").write_text(
        "---\n"
        "id: trap-src-python\n"
        "type: trap\n"
        "hypothesis: Source modules must not read the clock directly\n"
        "prediction: flaky tests\n"
        "target_paths: ['src/*.py']\n"
        "---\n"
        "# Use the injected clock\n",
        encoding="utf-8",
    )
    (root / "src").mkdir()
    return root


@pytest.fixture
def ws(tmp_path, monkeypatch):
    root = _workspace(tmp_path / "project")
    monkeypatch.chdir(root)
    return root


def test_json_mode_prints_only_json_naming_the_matching_rule(ws, capsys):
    rc = main(["scan", "src/app.py", "--json"])
    out = capsys.readouterr().out
    assert rc == 0
    payload = json.loads(out)
    assert [r["name"] for r in payload["relevant_rules"]] == ["trap-src-python"]
    assert payload["relevant_rules"][0]["matched_files"] == ["src/app.py"]


def test_text_mode_prints_the_rule_guidance(ws, capsys):
    rc = main(["scan", "src/app.py"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "trap-src-python" in out
    assert "Source modules must not read the clock directly" in out


def test_no_matching_rule_still_exits_zero(ws, capsys):
    rc = main(["scan", "docs/notes.md", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload["relevant_rules"] == []


def test_paths_are_taken_relative_to_the_working_directory(ws, monkeypatch, capsys):
    monkeypatch.chdir(ws / "src")
    rc = main(["scan", "app.py", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert [r["name"] for r in payload["relevant_rules"]] == ["trap-src-python"]
    assert payload["relevant_rules"][0]["matched_files"] == ["src/app.py"]


def test_outside_an_aegis_workspace_exits_2(tmp_path, monkeypatch, capsys):
    bare = tmp_path / "bare"
    bare.mkdir()
    monkeypatch.chdir(bare)
    rc = main(["scan", "app.py"])
    captured = capsys.readouterr()
    assert rc == 2
    assert captured.out == ""
    assert "not an Aegis workspace" in captured.err


def test_explicit_workspace_without_aegis_exits_2(tmp_path, capsys):
    bare = tmp_path / "bare"
    bare.mkdir()
    rc = main(["--workspace", str(bare), "scan", "app.py", "--json"])
    captured = capsys.readouterr()
    assert rc == 2
    assert captured.out == ""
    assert "not an Aegis workspace" in captured.err


def test_explicit_workspace_that_does_not_exist_is_named(tmp_path, capsys):
    missing = tmp_path / "no-such-dir"
    rc = main(["scan", "--workspace", str(missing), "app.py"])
    captured = capsys.readouterr()
    assert rc == 2
    assert captured.out == ""
    assert captured.err == f"Error: workspace path does not exist: {missing}\n"


def test_missing_file_argument_is_a_usage_error(ws, capsys):
    with pytest.raises(SystemExit) as exc:
        main(["scan"])
    assert exc.value.code == 2
    assert "FILE" in capsys.readouterr().err


def test_bootstrap_string_parses():
    """AGENTS.md and the MCP instructions tell agents to run the literal `aegis scan FILE`."""
    argv = shlex.split("aegis scan FILE")[1:]
    ns = _build_parser(prog="aegis").parse_args(argv)
    assert ns.command == "scan"
    assert ns.files == ["FILE"]

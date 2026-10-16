"""`aegis scan FILE...` records a scan row with host ``cli`` (v4.1 spec §2 "Behaviour" 1,
prerequisite (b)): the bootstrap's no-MCP fallback must satisfy the scan-before-edit hook
too. The row names the files as workspace-relative paths, resolved as aegis_scan resolves
them; recording never changes what the scan prints or its exit code."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re

import pytest

from aegis_cli.cli import _build_parser, main
from aegis_cli.scan import run_scan
from aegis_core.scan_compliance import CLI_HOST, scan_covers


def _workspace(root: Path) -> Path:
    traps = root / ".aegis" / "rules" / "traps"
    traps.mkdir(parents=True)
    (traps / "trap-src.md").write_text(
        "---\nid: trap-src\ntype: trap\nhypothesis: h\nprediction: p\ntarget_paths: ['src/*.py']\n---\n# Body\n",
        encoding="utf-8",
    )
    (root / "src").mkdir()
    (root / "src" / "a.py").write_text("a\n", encoding="utf-8")
    return root.resolve()


@pytest.fixture
def ws(tmp_path, monkeypatch) -> Path:
    root = _workspace(tmp_path / "project")
    monkeypatch.chdir(root)
    return root


def _rows(ws: Path) -> list:
    path = ws / ".aegis" / "state" / "activity.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_a_cli_scan_records_one_row_with_host_cli(ws, capsys):
    assert main(["scan", "src/a.py", "src/new.py"]) == 0
    (row,) = _rows(ws)
    assert (row["v"], row["event"], row["host"], row["files"], row["basis"]) == (
        1, "scan", CLI_HOST, ["src/a.py", "src/new.py"], "files")
    assert re.fullmatch(r"[0-9a-f]{32}", row["session"])
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", row["ts"])
    assert "client" not in row and "binding" not in row
    assert scan_covers(ws, ["src/a.py", "src/new.py"], 3600, datetime.now(timezone.utc))


def test_each_run_is_its_own_session(ws, capsys):
    main(["scan", "src/a.py"])
    main(["scan", "src/a.py"])
    first, second = _rows(ws)
    assert first["session"] != second["session"]


def test_json_output_is_unchanged_by_recording(ws, capsys):
    assert main(["scan", "src/a.py", "--json"]) == 0
    out = capsys.readouterr().out
    assert [r["name"] for r in json.loads(out)["relevant_rules"]] == ["trap-src"]
    assert len(_rows(ws)) == 1


def test_paths_are_workspace_relative_from_a_subdirectory_or_absolute(ws, monkeypatch, capsys):
    monkeypatch.chdir(ws / "src")
    assert main(["scan", "a.py", str(ws / "src" / "b.py"), "./c.py"]) == 0
    (row,) = _rows(ws)
    assert row["files"] == ["src/a.py", "src/b.py", "src/c.py"]


def test_a_symlinked_file_is_recorded_as_its_target_inside_the_workspace(ws, capsys):
    from tests.conftest import symlink_or_skip

    symlink_or_skip(ws / "src" / "a.py", ws / "src" / "link.py")
    assert main(["scan", "src/link.py"]) == 0
    (row,) = _rows(ws)
    assert row["files"] == ["src/a.py"]


def test_files_outside_the_workspace_are_left_out_of_the_row(ws, tmp_path, capsys):
    outside = tmp_path / "outside.py"
    outside.write_text("x\n", encoding="utf-8")
    assert main(["scan", "src/a.py", str(outside), "../outside.py"]) == 0
    (row,) = _rows(ws)
    assert row["files"] == ["src/a.py"]


def test_no_file_inside_the_workspace_records_nothing(ws, tmp_path, capsys):
    assert main(["scan", "../elsewhere.py"]) == 0
    assert _rows(ws) == []


def test_a_scan_that_cannot_serve_its_rules_records_nothing(ws, capsys):
    (ws / ".aegis" / "rules" / "traps" / "broken.md").write_text("---\nid: [unclosed\n---\n", encoding="utf-8")
    assert main(["scan", "src/a.py"]) == 1
    assert _rows(ws) == []


def test_an_unwritable_activity_log_never_fails_the_scan(ws, capsys):
    state = ws / ".aegis" / "state"
    state.mkdir(parents=True)
    (state / "activity.jsonl").mkdir()
    assert main(["scan", "src/a.py", "--json"]) == 0
    captured = capsys.readouterr()
    assert json.loads(captured.out)["relevant_rules"]
    assert "Warning: scan event not recorded" in captured.err


def test_a_directory_that_is_not_a_workspace_records_nothing(tmp_path, monkeypatch, capsys):
    plain = tmp_path / "plain"
    plain.mkdir()
    monkeypatch.chdir(plain)
    assert main(["scan", "a.py"]) == 2
    assert not (plain / ".aegis").exists()
    assert sorted(os.listdir(plain)) == []


def test_run_scan_records_the_row_for_the_files_it_scanned(ws, capsys):
    """run_scan, as the command runs it after parsing, records the row it scanned."""
    args = _build_parser().parse_args(["scan", "src/a.py", "--json"])
    assert run_scan(args) == 0
    assert json.loads(capsys.readouterr().out)["relevant_rules"]
    assert [(r["host"], r["files"]) for r in _rows(ws)] == [(CLI_HOST, ["src/a.py"])]

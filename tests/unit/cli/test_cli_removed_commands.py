"""v4 hard-cuts commands and aliases (ADR 0005 D5, H1): no aliases, no shims.

A removed name exits 2 and prints exactly one line on stderr pointing at the
replacement, so scripts and agents that call the old name fail loudly with
the next step instead of a generic argparse error.
"""
from __future__ import annotations

import json
import re

import pytest

from aegis_cli.cli import REMOVED_COMMANDS, _build_parser, main

REPORT_POINTER = (
    "aegis report was removed in v4: aegis status shows rule trigger counts; "
    "outcomes are recorded with the MCP tool aegis_report_outcome"
)


@pytest.mark.parametrize(
    "argv, line",
    [
        (["install"], "aegis install was removed in v4: use aegis init --host"),
        (["install", "--platform", "claude"], "aegis install was removed in v4: use aegis init --host"),
        (["system"], "aegis system was removed in v4: use aegis doctor"),
        (["sys"], "aegis sys was removed in v4: use aegis doctor"),
        (["system", "doctor", "--json"], "aegis system doctor was removed in v4: use aegis doctor"),
        (["system", "hook", "install"], "aegis system hook was removed in v4: use aegis hook"),
        (["detect"], "aegis detect was removed in v4: use aegis doctor"),
        (["languages"], "aegis languages was removed in v4: use aegis doctor"),
        (["drivers"], "aegis drivers was removed in v4: use aegis doctor"),
        (["audit"], "aegis audit was removed in v4: use aegis doctor"),
        (["rules"], "aegis rules was removed in v4: use aegis status"),
        (["agent", "scan", "a.py"], "aegis agent scan was removed in v4: use aegis scan"),
        (["agent", "record", "--outcome", "tp"],
         "aegis agent record was removed in v4: use aegis_report_outcome (MCP)"),
        (["report"], REPORT_POINTER),
        (["report", "--session", "0"], REPORT_POINTER),
        (["completion", "bash"], "aegis completion was removed in v4: no replacement"),
        (["skill", "list"], "aegis skill was removed in v4: no replacement"),
        (["handoff", "consume", "t-1"], "aegis handoff was removed in v4: no replacement"),
        (["--json", "report"], REPORT_POINTER),
        (["--workspace", "/nonexistent", "install"], "aegis install was removed in v4: use aegis init --host"),
    ],
)
def test_removed_name_exits_2_with_one_pointer_line(argv, line, capsys):
    rc = main(argv)
    captured = capsys.readouterr()
    assert rc == 2
    assert captured.out == ""
    assert captured.err == line + "\n"


HOST_HOOK_POINTER = "no replacement; remove it from your agent host's hook config"


@pytest.mark.parametrize(
    "argv, line",
    [
        (["hook", "pre-commit"], "aegis hook pre-commit was removed in v4: use aegis check --hook"),
        (["hook", "pre-commit", "--strict"], "aegis hook pre-commit was removed in v4: use aegis check --hook"),
        (["hook", "pre-invocation"], f"aegis hook pre-invocation was removed in v4: {HOST_HOOK_POINTER}"),
        (["hook", "governance-monitor"], f"aegis hook governance-monitor was removed in v4: {HOST_HOOK_POINTER}"),
        (["hook", "immune-init"], f"aegis hook immune-init was removed in v4: {HOST_HOOK_POINTER}"),
        (["hook", "session-close"], f"aegis hook session-close was removed in v4: {HOST_HOOK_POINTER}"),
        (["hook", "stop"], f"aegis hook stop was removed in v4: {HOST_HOOK_POINTER}"),
        (["hook", "post-session", "--transcript", "t.jsonl"],
         f"aegis hook post-session was removed in v4: {HOST_HOOK_POINTER}"),
    ],
)
def test_removed_hook_phase_exits_2_with_one_pointer_line(argv, line, capsys):
    rc = main(argv)
    captured = capsys.readouterr()
    assert rc == 2
    assert captured.out == ""
    assert captured.err == line + "\n"


def test_agent_without_a_known_action_points_at_both_replacements(capsys):
    assert main(["agent"]) == 2
    err = capsys.readouterr().err
    assert err.count("\n") == 1
    assert err.startswith("aegis agent was removed in v4: ")
    assert "aegis scan" in err and "aegis_report_outcome" in err


@pytest.mark.parametrize(
    "argv",
    [
        ["--plumbing", "status"],
        ["--internal", "status"],
        ["-q", "status"],
        ["-v", "status"],
        ["--no-emoji", "status"],
        ["--format", "json", "status"],
        ["status", "--format", "mermaid"],
        ["rule", "list", "--verbose"],
        ["rule", "list", "--no-emoji"],
    ],
)
def test_removed_global_flags_are_usage_errors(argv, capsys):
    with pytest.raises(SystemExit) as exc:
        main(argv)
    assert exc.value.code == 2
    assert "error:" in capsys.readouterr().err


@pytest.mark.parametrize("argv", [["--json", "status"], ["--plain", "status"], ["status", "--json"]])
def test_surviving_global_flags_still_parse(argv, tmp_path, monkeypatch, capsys):
    (tmp_path / ".aegis" / "rules").mkdir(parents=True)
    monkeypatch.chdir(tmp_path)
    assert main(argv) == 0
    if "--json" in argv:
        json.loads(capsys.readouterr().out)


# A subparser's own default for a shared flag overwrites the value the
# top-level parser already set, so `--json` before the command was silently
# dropped. Every position must reach the command.
@pytest.mark.parametrize(
    "argv",
    [
        ["--json", "scan", "a.py"],
        ["scan", "--json", "a.py"],
        ["--json", "rule", "list"],
        ["rule", "--json", "list"],
        ["rule", "list", "--json"],
        ["--json", "hook", "status"],
        ["hook", "--json", "status"],
    ],
)
def test_json_flag_is_honoured_before_or_after_the_command(argv, tmp_path, monkeypatch, capsys):
    (tmp_path / ".aegis" / "rules").mkdir(parents=True)
    monkeypatch.chdir(tmp_path)
    main(argv)
    out = capsys.readouterr().out
    json.loads(out)


@pytest.mark.parametrize("argv", [["status"], ["scan", "a.py"], ["rule", "list"], ["hook", "status"]])
def test_json_defaults_to_false_when_absent(argv):
    assert _build_parser().parse_args(argv).json is False


def test_check_format_json_is_json_mode_once_parsed():
    """Only `check` keeps --format; its json value is the one place that implies --json."""
    ns = _build_parser().parse_args(["check", "--format", "json"])
    assert ns.json is True
    assert ns.ui.json_mode is True


# Every `aegis <command> [--flag]` a pointer sends people to, as an argv that
# must parse, so a pointer can never name a command or flag that does not exist.
_REPLACEMENT_ARGV = {
    "aegis check": ["check"],
    "aegis check --hook": ["check", "--hook"],
    "aegis doctor": ["doctor"],
    "aegis hook": ["hook", "status"],
    "aegis init --host": ["init", "--host", "claude-code"],
    "aegis scan": ["scan", "a.py"],
    "aegis status": ["status"],
}
_NAMED = re.compile(r"\baegis ([a-z][a-z-]*)(?: (--[a-z][a-z-]*))?")


def test_the_replacement_table_covers_every_named_replacement():
    named = set()
    for text in REMOVED_COMMANDS.values():
        for command, flag in _NAMED.findall(text):
            named.add(" ".join(part for part in ("aegis", command, flag) if part))
    assert named == set(_REPLACEMENT_ARGV)


@pytest.mark.parametrize(
    "named",
    [
        pytest.param(
            name,
            marks=pytest.mark.xfail(
                strict=True,
                reason="init --host lands with the host table in wave C (v4.0-c); drop this mark then",
            ),
        ) if name == "aegis init --host" else name
        for name in sorted(_REPLACEMENT_ARGV)
    ],
)
def test_every_named_replacement_parses(named):
    try:
        _build_parser().parse_args(_REPLACEMENT_ARGV[named])
    except SystemExit as exc:
        pytest.fail(f"{named!r} does not parse (exit {exc.code})")

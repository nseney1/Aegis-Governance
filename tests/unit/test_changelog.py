"""The CHANGELOG's v4.0.0 breaking-change list must match what the parser does.

Every removed command and flag the entry names must be rejected with exit status 2.
Removed commands, and the removed ``init`` and ``uninstall`` flags, print one line
naming the replacement; the other removed flags get the argument parser's usage
error, so the entry's list is the only place that names their replacements.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from aegis_cli.cli import REMOVED_COMMANDS, main

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").exists())


def _v4_entry() -> str:
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    match = re.search(r"^## \[4\.0\.0\].*?(?=^## \[|\Z)", text, re.M | re.S)
    assert match, "CHANGELOG.md has no '## [4.0.0]' entry"
    return match.group(0)


def _run(argv, capsys):
    try:
        rc = main(argv)
    except SystemExit as exc:
        rc = exc.code
    return rc, capsys.readouterr().err


# (argv, the flag as the 4.0.0 entry writes it, whether a one-line pointer is printed)
REMOVED_FLAGS = [
    (["--plumbing", "status"], "--plumbing", False),
    (["--internal", "status"], "--internal", False),
    (["-q", "status"], "-q", False),
    (["-v", "status"], "-v", False),
    (["--no-emoji", "status"], "--no-emoji", False),
    (["init", "--platform", "claude"], "--platform", True),
    (["init", "--mcp"], "--mcp", True),
    (["init", "--local"], "--local", True),
    (["uninstall", "--platform", "claude"], "--platform", True),
    (["uninstall", "-p", "claude"], "-p", True),
    (["uninstall", "--local"], "--local", True),
    (["uninstall", "--purge"], "--purge", True),
    (["check", "--release"], "--release", False),
    (["check", "--release-gate"], "--release-gate", False),
    (["check", "--require-arbitration"], "--require-arbitration", False),
    (["check", "--provider", "x"], "--provider", False),
    (["check", "--in-band"], "--in-band", False),
    (["check", "--no-layer2"], "--no-layer2", False),
    (["check", "--all"], "--all", False),
    (["check", "--files", "a.py"], "--files", False),
    (["check", "--pre-commit"], "--pre-commit", False),
    (["check", "--checkpoint-only"], "--checkpoint-only", False),
    (["check", "--layer1-only"], "--layer1-only", False),
    (["check", "--deep"], "--deep", False),
    (["check", "--format", "sarif"], "--format sarif", False),
    (["rule", "create", "--from-description", "x"], "--from-description", False),
    (["rule", "create", "--weight", "1"], "--weight", False),
    (["rule", "create", "--expiry-sessions", "1"], "--expiry-sessions", False),
    (["rule", "create", "--expiry-days", "1"], "--expiry-days", False),
    (["rule", "create", "--minimum-mode", "x"], "--minimum-mode", False),
    (["rule", "create", "--effector", "x"], "--effector", False),
    (["rule", "create", "--memory", "x"], "--memory", False),
    (["rule", "promote", "x", "--rule", "y"], "--rule", False),
    (["rule", "promote", "x", "--reason", "y"], "--reason", False),
    (["rule", "demote", "x", "--force"], "--force", False),
    (["rule", "archive", "--apply"], "--apply", False),
    (["status", "--all"], "status --all", False),
    (["doctor", "--fix-path"], "doctor --fix-path", False),
]


@pytest.mark.parametrize(
    "argv, written, pointer", REMOVED_FLAGS, ids=[" ".join(argv) for argv, _, _ in REMOVED_FLAGS]
)
def test_each_removed_flag_in_the_entry_exits_2(argv, written, pointer, tmp_path, monkeypatch, capsys):
    assert f"`{written}`" in _v4_entry() or f"`aegis {written}`" in _v4_entry(), (
        f"the 4.0.0 entry does not name {written!r}"
    )
    monkeypatch.chdir(tmp_path)
    rc, err = _run(argv, capsys)
    assert rc == 2
    lines = err.strip().splitlines()
    if pointer:
        assert len(lines) == 1 and " was removed in v4: " in lines[0], err
    else:
        assert "was removed in v4" not in err
        assert "unrecognized arguments" in lines[-1] or "invalid choice" in lines[-1], err


def _named_in(name: str, entry: str) -> bool:
    words = name.split()
    forms = {f"`{name}`", f"`aegis {name}`"}
    if len(words) == 2 and words[0] in REMOVED_COMMANDS:
        forms.add(f"`{words[0]}`")  # 'system doctor' is removed with 'system'
    if len(words) == 2 and words[0] == "hook":
        forms.add(f"`{words[1]}`")  # the entry lists the hook phases by name
    return any(form in entry for form in forms)


def test_every_removed_command_is_named_in_the_entry():
    entry = _v4_entry()
    assert sorted(name for name in REMOVED_COMMANDS if not _named_in(name, entry)) == []


def test_the_lead_paragraph_promises_pointers_only_where_the_parser_prints_them():
    lead = _v4_entry().split("### ", 1)[0]
    assert not re.search(r"[Ee]very removed command and flag[^.]*prints", lead), lead
    assert re.search(r"removed `init` and `uninstall` flags, print one line", lead), lead

"""Rule files are read-only to every runtime path (ADR 0005 AD-1 / H6).

Fitness lives in the ledger (.aegis/state/ledger.jsonl), never in rule
frontmatter. `aegis check` used to bump triggers/true_positives/last_trigger_date
in every rule matching the changed files, which dirtied tracked .aegis/rules/**
on each pre-commit run and broke the committed v3 manifest (PR #173 CI failure).

Each test below drives one runtime entry point against a temp git repo whose
rules match the changed file, then asserts every byte under .aegis/rules is
unchanged, `git status` reports nothing there, and no derived counter key
(fitness, triggers, true_positives, ...) appears in a rule that had none
(v4.3 spec §10.2).
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from aegis_cli.cli import main
from aegis_core.telemetry_engine import ledger
from aegis_core.yaml_engine.frontmatter import parse_frontmatter
from aegis_mcp.tools import execute_tool

TRAP = (
    "---\n"
    "id: trap-app-drift\n"
    "domain: correctness\n"
    "type: trap\n"
    "enforcement: advisory\n"
    "hypothesis: Edits to src/ drift from the documented behaviour.\n"
    "target_paths:\n"
    '  - "src/*.py"\n'
    "fitness:\n"
    "  score: 0.5\n"
    "  impact_weight: 1.0\n"
    "  triggers: 3\n"
    "  true_positives: 1\n"
    "  false_positives: 1\n"
    '  last_trigger_date: "2026-01-01T00:00:00Z"\n'
    "---\n"
    "\n"
    "Check the docs when src/ changes.\n"
)

INVARIANT = (
    "---\n"
    "id: invariant-app-pure\n"
    "domain: correctness\n"
    "type: invariant\n"
    "enforcement: advisory\n"
    "hypothesis: src/ modules stay free of side effects at import time.\n"
    "target_paths:\n"
    "  - src/app.py\n"
    "---\n"
    "\n"
    "No work at import time.\n"
)

RULE_IDS = ("trap-app-drift", "invariant-app-pure")


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=str(repo), check=True, capture_output=True, text=True
    ).stdout


def _rule_bytes(repo: Path) -> dict:
    rules = repo / ".aegis" / "rules"
    return {p.relative_to(rules).as_posix(): p.read_bytes() for p in sorted(rules.rglob("*")) if p.is_file()}


def _ledger_rows(repo: Path) -> list:
    return ledger.read(repo).rows


DERIVED_KEYS = {
    "fitness", "triggers", "true_positives", "false_positives", "last_trigger_date",
    "score", "tp", "fp", "tp_rate", "fp_rate",
}


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """A committed workspace whose two rules match src/app.py, with that file then changed and staged."""
    root = tmp_path / "repo"
    rules = root / ".aegis" / "rules"
    (rules / "traps").mkdir(parents=True)
    (rules / "invariants").mkdir(parents=True)
    (rules / "traps" / "trap-app-drift.md").write_text(TRAP, encoding="utf-8")
    (rules / "invariants" / "invariant-app-pure.md").write_text(INVARIANT, encoding="utf-8")
    (root / "src").mkdir()
    (root / "src" / "app.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")

    _git(root, "init", "-b", "main")
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "Tester")
    _git(root, "add", ".")
    _git(root, "commit", "-m", "init")

    (root / "src" / "app.py").write_text("def add(a, b):\n    return a + b  # changed\n", encoding="utf-8")
    _git(root, "add", "src/app.py")
    monkeypatch.chdir(root)
    monkeypatch.delenv("AEGIS_WORKSPACE", raising=False)
    return root


def _assert_rules_untouched(repo: Path, before: dict) -> None:
    assert _rule_bytes(repo) == before
    assert _git(repo, "status", "--porcelain", "--", ".aegis/rules") == ""
    invariant = (repo / ".aegis" / "rules" / "invariants" / "invariant-app-pure.md").read_text(encoding="utf-8")
    assert not DERIVED_KEYS & set(parse_frontmatter(invariant) or {})


@pytest.mark.parametrize("argv", [["check"], ["check", "--hook"], ["check", "--hook", "--json"]])
def test_check_records_triggers_in_the_ledger_and_never_rewrites_rules(repo, argv, capsys):
    before = _rule_bytes(repo)

    rc = main(argv)

    out = capsys.readouterr().out
    assert rc in (0, 1), out
    assert "Layer 1" in out or '"passed"' in out
    _assert_rules_untouched(repo, before)
    # The telemetry path did run: the matched rules reached the ledger instead.
    triggered = {r["rule"] for r in _ledger_rows(repo) if r["source"] == "session"}
    assert set(RULE_IDS) <= triggered


def test_scan_never_rewrites_rules(repo, capsys):
    before = _rule_bytes(repo)

    assert main(["scan", "src/app.py", "--json"]) == 0

    out = capsys.readouterr().out
    assert "trap-app-drift" in out
    _assert_rules_untouched(repo, before)


def test_mcp_scan_list_and_create_never_rewrite_rules(repo):
    before = _rule_bytes(repo)

    scanned = execute_tool("aegis_scan", {"workspace": str(repo), "files": ["src/app.py"]})
    listed = execute_tool("aegis_list_rules", {"workspace": str(repo)})
    created = execute_tool("aegis_create_rule", {"workspace": str(repo), "description": "no prints in src"})

    assert "trap-app-drift" in json.dumps(scanned, default=str)
    assert "trap-app-drift" in json.dumps(listed, default=str)
    assert created.get("status") != "FAIL", created
    _assert_rules_untouched(repo, before)


@pytest.mark.parametrize("outcome", ["success", "failure", "partial"])
def test_mcp_report_outcome_appends_to_the_ledger_and_never_rewrites_rules(repo, outcome):
    before = _rule_bytes(repo)

    result = execute_tool(
        "aegis_report_outcome",
        {
            "workspace": str(repo),
            "outcome": outcome,
            "rules_used": list(RULE_IDS),
            "idempotency_key": f"no-rule-writes-{outcome}",
        },
    )

    assert result.get("status") == "recorded", result
    assert {r["rule"] for r in _ledger_rows(repo) if r["source"] == "mcp"} == set(RULE_IDS)
    _assert_rules_untouched(repo, before)


def test_hook_status_and_safety_gate_never_rewrite_rules(repo, capsys):
    before = _rule_bytes(repo)

    main(["hook", "status"])
    main(["hook", "safety-gate", "--cmd", "ls"])

    capsys.readouterr()
    _assert_rules_untouched(repo, before)


@pytest.mark.parametrize("argv", [["status"], ["status", "--json"], ["doctor"], ["doctor", "--json"]])
def test_status_and_doctor_never_rewrite_rules(repo, argv, capsys):
    before = _rule_bytes(repo)

    rc = main(argv)

    out = capsys.readouterr().out
    assert rc in (0, 1), out
    _assert_rules_untouched(repo, before)


@pytest.mark.parametrize("argv", [["sync"], ["sync", "--json"]])
def test_sync_rebuilds_derived_state_and_never_rewrites_rules(repo, argv, capsys):
    """`aegis sync` writes only .aegis/state/derived.json; `--apply` is the explicit move."""
    before = _rule_bytes(repo)

    rc = main(argv)

    capsys.readouterr()
    assert rc == 0
    assert (repo / ".aegis" / "state" / "derived.json").is_file()
    _assert_rules_untouched(repo, before)


@pytest.mark.parametrize(
    "argv",
    [
        ["rule", "promote", "--tier-check", "--dry-run"],
        ["rule", "promote"],
        ["rule", "demote"],
        ["rule", "archive", "--dry-run"],
        ["rule", "list"],
    ],
)
def test_rule_reports_and_dry_runs_never_rewrite_rules(repo, argv, capsys):
    """Listing candidates and dry runs only report; applying a transition is the explicit write."""
    before = _rule_bytes(repo)

    rc = main(argv)

    out = capsys.readouterr().out
    assert rc in (0, 1), out
    _assert_rules_untouched(repo, before)

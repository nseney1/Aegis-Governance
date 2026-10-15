"""`aegis check --hook`: the command the installed git pre-commit hook runs (defense #21).

Ported from tests/unit/core/test_precommit_layer1.py, which exercised the
parallel `run_pre_commit` implementation that no installed hook ever called.
These run the real `check --hook` path against staged files in a temp repo.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from aegis_cli.cli import main

CLEAN = "def add(a: int, b: int) -> int:\n    return a + b\n"

GATE_RULE = (
    "---\n"
    "id: no-subprocess-run\n"
    "type: invariant\n"
    "enforcement: gate\n"
    "hypothesis: Production code never shells out.\n"
    "target_paths:\n"
    "  - src/*\n"
    "forbid_ast:\n"
    "  calls:\n"
    "    - subprocess.run\n"
    "---\n"
    "# No subprocess.run\n"
)


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=str(repo), check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-b", "main")
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "Tester")
    monkeypatch.chdir(root)
    return root


def _stage(repo: Path, rel: str, text: str) -> None:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    _git(repo, "add", rel)


def test_clean_staged_python_file_passes(repo, capsys):
    _stage(repo, "calculator.py", CLEAN)
    assert main(["check", "--hook"]) == 0
    assert "PASSED" in capsys.readouterr().out


def test_staged_unguarded_third_party_import_blocks(repo, capsys):
    _stage(repo, "calculator.py", CLEAN)
    _stage(repo, "aegis_core/bad_mod.py", "import google.genai\n\ndef run():\n    return 1\n")
    assert main(["check", "--hook"]) == 1
    out = capsys.readouterr().out
    assert "import_guard" in out
    assert "google" in out


def test_json_mode_reports_the_blocking_check(repo, capsys):
    _stage(repo, "aegis_core/bad_mod.py", "import google.genai\n\ndef run():\n    return 1\n")
    assert main(["check", "--hook", "--json"]) == 1
    out = capsys.readouterr().out
    assert '"passed": false' in out
    assert '"import_guard"' in out


def _entries_naming(node, name):
    if isinstance(node, dict):
        if name in (node.get("tool"), node.get("check")):
            yield node
        for value in node.values():
            yield from _entries_naming(value, name)
    elif isinstance(node, list):
        for value in node:
            yield from _entries_naming(value, name)


def test_json_mode_stdout_is_one_document_naming_the_blocking_check(repo, capsys):
    """The removed `hook pre-commit --json` printed one parseable document; `check --hook --json` must too."""
    _stage(repo, "aegis_core/bad_mod.py", "import google.genai\n\ndef run():\n    return 1\n")
    assert main(["check", "--hook", "--json"]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["passed"] is False
    blocking = [e for e in _entries_naming(payload, "import_guard") if e.get("verdict") is not True]
    assert blocking, payload


def test_gate_rule_under_aegis_rules_blocks_a_forbid_ast_hit(repo, capsys):
    """BUG-100: rules under .aegis/rules are the ones the commit gate enforces."""
    _stage(repo, ".aegis/rules/invariants/no-subprocess-run.md", GATE_RULE)
    _stage(repo, "src/runner.py", "import subprocess\n\ndef go():\n    subprocess.run(['ls'])\n")
    assert main(["check", "--hook"]) == 1
    out = capsys.readouterr().out
    assert "forbid_ast:no-subprocess-run" in out
    assert "subprocess.run" in out


def test_gate_rule_passes_a_compliant_file(repo):
    _stage(repo, ".aegis/rules/invariants/no-subprocess-run.md", GATE_RULE)
    _stage(repo, "src/runner.py", CLEAN)
    assert main(["check", "--hook"]) == 0

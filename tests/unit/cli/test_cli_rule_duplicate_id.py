"""`aegis rule create` never replaces a rule: a duplicate id is an error (review F4).

The id is checked against every rule the one loader sees, in any type directory.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from aegis_cli.cli import main


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.delenv("AEGIS_WORKSPACE", raising=False)
    monkeypatch.delenv("AEGIS_ROOT", raising=False)
    repo = (home / "code" / "repo").resolve()
    (repo / ".git").mkdir(parents=True)
    rules = repo / ".aegis" / "rules"
    for tier, rule_id in (("traps", "trap-rule"), ("invariants", "inv-rule")):
        path = rules / tier / f"{rule_id}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"---\nid: {rule_id}\ntype: {tier[:-1]}\nenforcement: {'gate' if tier == 'invariants' else 'advisory'}\n---\nBody.\n", encoding="utf-8")
    monkeypatch.chdir(repo)
    return repo


def test_creating_an_existing_rule_id_fails_and_keeps_the_rule(repo, capsys) -> None:
    existing = repo / ".aegis" / "rules" / "traps" / "trap-rule.md"
    digest = hashlib.sha256(existing.read_bytes()).hexdigest()

    rc = main(["rule", "create", "--hypothesis", "Replacement", "--id", "trap-rule"])

    assert rc == 1
    assert capsys.readouterr().err == f"Error: rule 'trap-rule' already exists: {existing}\n"
    assert hashlib.sha256(existing.read_bytes()).hexdigest() == digest


def test_creating_an_id_held_by_another_tier_fails(repo, capsys) -> None:
    rc = main(["rule", "create", "--type", "trap", "--hypothesis", "Shadow", "--id", "inv-rule", "--json"])

    assert rc == 1
    existing = repo / ".aegis" / "rules" / "invariants" / "inv-rule.md"
    assert json.loads(capsys.readouterr().out) == {
        "status": "error", "error": f"rule 'inv-rule' already exists: {existing}",
    }
    assert not (repo / ".aegis" / "rules" / "traps" / "inv-rule.md").exists()

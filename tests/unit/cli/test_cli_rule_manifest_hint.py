"""`aegis rule` mutations tell the operator when the rules manifest is stale.

H1 removed the manifest auto-sync (lifecycle writes must never re-attest
tampered rules), so a create/promote/demote leaves `.aegis/rules/manifest.json`
behind the rules on disk. With an HMAC key configured the MCP rule cache then
refuses to load rules (aegis_mcp/rule_cache.py), and nothing said so (review
finding F6). The CLI now warns on stderr; it still never rewrites the manifest.
Also covers the CLI face of F4: a duplicate id is an error, not a replacement.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from aegis_cli.cli import main
from aegis_core.integrity import generate_key, generate_manifest, save_manifest


def _stale(n: int, signed: bool) -> str:
    msg = (
        f"Warning: .aegis/rules/manifest.json is out of date ({n} rule file(s) changed); "
        "re-run aegis init to regenerate it."
    )
    if signed:
        msg += " With an HMAC key configured, the MCP server will not load rules until then."
    return msg + "\n"


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
        path.write_text(f"---\nid: {rule_id}\ntype: {tier[:-1]}\nenforcement: advisory\n---\nBody.\n", encoding="utf-8")
    monkeypatch.chdir(repo)
    return repo


def _manifest_bytes(repo: Path) -> bytes:
    return (repo / ".aegis" / "rules" / "manifest.json").read_bytes()


def _sign(repo: Path, key: bool) -> bytes:
    if key:
        generate_key(repo)
    save_manifest(repo, generate_manifest(repo / ".aegis" / "rules"))
    return _manifest_bytes(repo)


@pytest.mark.parametrize("key", [True, False], ids=["signed", "unsigned"])
def test_create_warns_that_the_manifest_is_stale_and_leaves_it_alone(repo, capsys, key: bool) -> None:
    manifest = _sign(repo, key)

    rc = main(["rule", "create", "--hypothesis", "New rule", "--id", "new-rule"])

    captured = capsys.readouterr()
    assert rc == 0
    assert captured.err == _stale(1, signed=key)
    assert (repo / ".aegis" / "rules" / "traps" / "new-rule.md").is_file()
    assert _manifest_bytes(repo) == manifest


@pytest.mark.parametrize(
    "argv", [["promote", "trap-rule"], ["demote", "inv-rule"]], ids=["promote", "demote"]
)
def test_moves_warn_that_the_signed_manifest_is_stale(repo, capsys, argv: list[str]) -> None:
    manifest = _sign(repo, key=True)

    rc = main(["rule", *argv])

    captured = capsys.readouterr()
    assert rc == 0, captured.out
    assert captured.err == _stale(2, signed=True)
    assert _manifest_bytes(repo) == manifest


def test_archive_warns_that_the_signed_manifest_is_stale(repo, capsys) -> None:
    extinct = repo / ".aegis" / "rules" / "traps" / "extinct.md"
    extinct.write_text(
        "---\nid: extinct\ntype: trap\nfitness:\n  triggers: 10\n  true_positives: 0\n  false_positives: 0\n---\nB.\n",
        encoding="utf-8",
    )
    manifest = _sign(repo, key=True)

    rc = main(["rule", "archive"])

    captured = capsys.readouterr()
    assert rc == 0
    assert (repo / ".aegis" / "rules" / ".archive" / "extinct.md").is_file()
    # trap-rule and inv-rule have no triggers, so selection also marks them dormant.
    assert captured.err == _stale(4, signed=True)
    assert _manifest_bytes(repo) == manifest


def test_tier_check_rewrites_warn_without_the_signed_suffix(repo, capsys) -> None:
    """Rewritten rules are "modified" drift, which the MCP rule cache only warns about."""
    manifest = _sign(repo, key=True)

    rc = main(["rule", "promote", "--tier-check"])

    captured = capsys.readouterr()
    assert rc == 0
    assert captured.err == _stale(2, signed=False)
    assert _manifest_bytes(repo) == manifest


def test_rerunning_init_regenerates_the_manifest_as_the_warning_says(repo, capsys) -> None:
    """The remedy the warning names must work: after it, only newer changes count."""
    _sign(repo, key=True)
    assert main(["rule", "create", "--hypothesis", "First", "--id", "first"]) == 0
    assert capsys.readouterr().err == _stale(1, signed=True)

    assert main(["init", "--platform", "claude", "--yes", "--no-hooks"]) == 0
    capsys.readouterr()

    assert main(["rule", "create", "--hypothesis", "Second", "--id", "second"]) == 0
    assert capsys.readouterr().err == _stale(1, signed=True)


def test_no_manifest_means_no_warning(repo, capsys) -> None:
    rc = main(["rule", "create", "--hypothesis", "New rule", "--id", "new-rule"])

    assert rc == 0
    assert capsys.readouterr().err == ""


def test_dry_run_changes_nothing_and_does_not_warn(repo, capsys) -> None:
    _sign(repo, key=True)

    rc = main(["rule", "promote", "trap-rule", "--dry-run"])

    assert rc == 0
    assert capsys.readouterr().err == ""


def test_json_mode_keeps_stdout_machine_readable(repo, capsys) -> None:
    _sign(repo, key=True)

    rc = main(["rule", "create", "--hypothesis", "New rule", "--id", "new-rule", "--json"])

    captured = capsys.readouterr()
    assert rc == 0
    assert json.loads(captured.out)["status"] == "created"
    assert captured.err == _stale(1, signed=True)


def test_failed_create_does_not_warn(repo, capsys) -> None:
    _sign(repo, key=True)

    rc = main(["rule", "create", "--hypothesis", "x", "--id", "../escape"])

    captured = capsys.readouterr()
    assert rc == 1
    assert "Warning:" not in captured.err


# ── F4 at the CLI: a duplicate id is refused ───────────────────────────

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


def test_a_manifest_that_is_not_an_object_is_reported_not_raised(repo, capsys) -> None:
    (repo / ".aegis" / "rules" / "manifest.json").write_text("[]\n", encoding="utf-8")

    rc = main(["rule", "create", "--hypothesis", "New rule", "--id", "new-rule"])

    captured = capsys.readouterr()
    assert rc == 0
    assert captured.err == (
        "Warning: .aegis/rules/manifest.json is not a valid manifest; "
        "re-run aegis init to regenerate it.\n"
    )
    assert (repo / ".aegis" / "rules" / "traps" / "new-rule.md").is_file()

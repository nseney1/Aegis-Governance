"""`aegis approve` and `aegis doctor --github` through the real argument parser."""
from __future__ import annotations

import io
import json

import pytest

from aegis_cli import cli
from aegis_core import human_gate
from tests import helpers_humangate as hg

needs_git = pytest.mark.skipif(not hg.git_ok(), reason="needs git")


def test_approve_is_a_registered_command_with_a_base_flag(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["approve", "--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "--base" in out and "Aegis-Approve" in out


def test_approve_appears_in_the_categorized_help(capsys):
    assert cli.main([]) == 0
    assert "approve" in capsys.readouterr().out


def test_approve_outside_a_git_work_tree_is_a_refusal_not_a_traceback(tmp_path, capsys):
    rc = cli.main(["approve", "--workspace", str(tmp_path)])
    assert rc == 1
    assert "not inside a git work tree" in capsys.readouterr().err


@needs_git
def test_approve_without_a_terminal_refuses_through_main(tmp_path, monkeypatch, capsys):
    repo = hg.make_repo(tmp_path)
    repo.write(".aegis/config.json", "{}\n")
    repo.commit("governance")
    monkeypatch.setattr("sys.stdin", io.StringIO())
    key, _pub = hg.keygen(tmp_path / "k", "human")
    repo.home.sign_with(str(key))
    monkeypatch.setenv("HOME", str(repo.home.path))
    rc = cli.main(["approve", "--workspace", str(repo.root), "--base", "main", "--json"])
    doc = json.loads(capsys.readouterr().out)
    assert rc == 1 and doc["status"] == "refused" and doc["code"] == "no_terminal"
    for field in ("source", "aegis_version", "checked_at", "scope"):
        assert doc[field]


@needs_git
@pytest.mark.parametrize("flags,needle", [
    (["--tier", "B"], "--tier only applies"),
    (["--apply"], "--apply only applies"),
    (["--github", "--fix"], "cannot be combined"),
    (["--github", "--apply", "--tier", "B", "--json"], "cannot run with --json"),
    (["--github", "--apply"], "--tier A or --tier B"),
])
def test_doctor_github_flag_combinations_are_usage_errors(tmp_path, capsys, flags, needle):
    repo = hg.make_repo(tmp_path)
    rc = cli.main(["doctor", "--workspace", str(repo.root), *flags])
    assert rc == 2
    assert needle in capsys.readouterr().err


def test_an_approval_verdict_serializes_with_the_envelope():
    verdict = human_gate.Approval(False, "unsigned", "the commit is not signed", "a" * 40)
    doc = verdict.as_dict("/work")
    assert doc["valid"] is False and doc["code"] == "unsigned" and doc["scope"]["commit"] == "a" * 40
    assert doc["checked_at"].endswith("Z") and doc["source"] and doc["aegis_version"]

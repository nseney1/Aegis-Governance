"""Pre-tag release check .github/scripts/ci_green.py (ADR 0005 AD-10, defense #33).

A workflow job cannot see its own run's conclusion, so "CI green on the exact
SHA" is checked before tagging by asking `gh run list --commit <sha>`. The gh
subprocess is mocked; every case asserts the exit code and the message.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / ".github" / "scripts" / "ci_green.py"
SHA = "4f2810174fbd6014dd5db3e7c90121e1bc514676"
OTHER = "175f3b3aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"


@pytest.fixture
def ci_green():
    spec = importlib.util.spec_from_file_location("ci_green", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _gh(monkeypatch, module, runs=None, returncode=0, stdout=None, raises=None):
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        if raises is not None:
            raise raises
        out = stdout if stdout is not None else json.dumps(runs or [])
        return subprocess.CompletedProcess(argv, returncode, stdout=out, stderr="gh: boom" if returncode else "")

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    return calls


def _run(status: str = "completed", conclusion: str = "success", sha: str = SHA, name: str = "Validate"):
    return {"headSha": sha, "status": status, "conclusion": conclusion, "workflowName": name}


def test_green_when_every_run_on_the_sha_succeeded(ci_green, monkeypatch, capsys):
    calls = _gh(monkeypatch, ci_green, [_run(), _run(name="Publish")])
    assert ci_green.main([SHA]) == 0
    assert calls == [["gh", "run", "list", "--commit", SHA, "--json", "conclusion,headSha,status,workflowName", "--limit", "100"]]
    assert f"CI is green on {SHA}" in capsys.readouterr().out


def test_red_when_any_run_failed(ci_green, monkeypatch, capsys):
    _gh(monkeypatch, ci_green, [_run(), _run(conclusion="failure", name="Validate")])
    assert ci_green.main([SHA]) == 1
    assert "Validate: failure" in capsys.readouterr().err


def test_red_while_a_run_is_still_in_progress(ci_green, monkeypatch, capsys):
    _gh(monkeypatch, ci_green, [_run(status="in_progress", conclusion="")])
    assert ci_green.main([SHA]) == 1
    assert "Validate: in_progress" in capsys.readouterr().err


def test_red_when_no_run_exists_for_the_sha(ci_green, monkeypatch, capsys):
    _gh(monkeypatch, ci_green, [])
    assert ci_green.main([SHA]) == 1
    assert f"no CI run found for {SHA}" in capsys.readouterr().err


def test_runs_for_other_commits_do_not_count(ci_green, monkeypatch, capsys):
    _gh(monkeypatch, ci_green, [_run(sha=OTHER)])
    assert ci_green.main([SHA]) == 1
    assert f"no CI run found for {SHA}" in capsys.readouterr().err


def test_workflow_filter_is_passed_to_gh(ci_green, monkeypatch):
    calls = _gh(monkeypatch, ci_green, [_run()])
    assert ci_green.main([SHA, "--workflow", "validate.yml"]) == 0
    assert calls[0][-2:] == ["--workflow", "validate.yml"]


@pytest.mark.parametrize("bad", ["4f28101", "HEAD", "4F2810174FBD6014DD5DB3E7C90121E1BC514676", SHA + "0", ""])
def test_only_a_full_lowercase_sha_is_accepted(ci_green, monkeypatch, capsys, bad):
    calls = _gh(monkeypatch, ci_green, [_run()])
    assert ci_green.main([bad]) == 2
    assert calls == []
    assert "full 40-character commit SHA" in capsys.readouterr().err


def test_missing_gh_is_an_error(ci_green, monkeypatch, capsys):
    _gh(monkeypatch, ci_green, raises=FileNotFoundError("gh"))
    assert ci_green.main([SHA]) == 2
    assert "gh (GitHub CLI) not found" in capsys.readouterr().err


def test_gh_timeout_is_an_error(ci_green, monkeypatch, capsys):
    _gh(monkeypatch, ci_green, raises=subprocess.TimeoutExpired(["gh"], 120))
    assert ci_green.main([SHA]) == 2
    assert "gh run list did not answer within 120s" in capsys.readouterr().err


def test_gh_failure_is_an_error(ci_green, monkeypatch, capsys):
    _gh(monkeypatch, ci_green, returncode=1)
    assert ci_green.main([SHA]) == 2
    assert "gh run list failed (exit 1): gh: boom" in capsys.readouterr().err


def test_unparseable_gh_output_is_an_error(ci_green, monkeypatch, capsys):
    _gh(monkeypatch, ci_green, stdout="not json")
    assert ci_green.main([SHA]) == 2
    assert "could not parse gh output" in capsys.readouterr().err

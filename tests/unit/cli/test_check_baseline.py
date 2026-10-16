"""`aegis check --write-baseline`, `--prune-baseline` and `aegis check [--base REF]` (v4.2 #2).

The ratchet through the real CLI: a repository that already has findings records them,
then `check` fails only on findings the baseline does not hold. With `--base` the
baseline is read from the base commit and never from the candidate (the lens of this
suite: a candidate that edits its own baseline must not be able to excuse itself).
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil

import pytest

from aegis_cli.cli import main
from aegis_core import baseline, events
from aegis_core._version import __version__
from tests.helpers_checkmodes import NO_EVAL, commit, git, init_repo, write

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="needs git")

TS = re.compile(r"\A\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z\Z")
BASELINE = ".aegis/baseline.json"


@pytest.fixture(autouse=True)
def _no_ci_base(monkeypatch):
    monkeypatch.delenv("GITHUB_BASE_REF", raising=False)


@pytest.fixture
def repo(tmp_path: Path, monkeypatch) -> Path:
    """A repository with two existing findings: an eval in legacy.py and an unguarded import."""
    root = init_repo(tmp_path / "project")
    write(root, "legacy.py", "import google.genai\n\n\ndef old(x):\n    return eval(x)\n")
    write(root, "clean.py", "def fine():\n    return 1\n")
    commit(root, "base")
    monkeypatch.chdir(root)
    return root


def _run(capsys, *argv: str):
    try:
        rc = main(["check", *argv])
    except SystemExit as exc:  # argparse
        rc = exc.code
    captured = capsys.readouterr()
    return rc, captured.out, captured.err


def _json(capsys, *argv: str):
    rc, out, err = _run(capsys, *argv, "--json")
    return rc, json.loads(out), err


def _held(root: Path):
    return json.loads((root / BASELINE).read_text(encoding="utf-8"))["findings"]


def _write_baseline(capsys):
    rc, out, err = _run(capsys, "--write-baseline")
    assert rc == 0, err
    return out


# ── --write-baseline ─────────────────────────────────────────────────────────

def test_write_baseline_records_every_current_finding(repo: Path, capsys):
    out = _write_baseline(capsys)
    held = _held(repo)
    assert sorted((e["rule"], e["path"]) for e in held) == [
        ("forbid_ast:no-eval", "legacy.py"), ("import_guard", "legacy.py")]
    assert all(re.fullmatch(r"[0-9a-f]{64}", e["fp"]) for e in held)
    assert "wrote .aegis/baseline.json: 2 finding(s)" in out


def test_the_file_is_the_v1_document_and_deterministic(repo: Path, capsys):
    _write_baseline(capsys)
    first = (repo / BASELINE).read_bytes()
    assert json.loads(first)["v"] == 1 and first.endswith(b"}\n") and b"\r" not in first
    _write_baseline(capsys)
    assert (repo / BASELINE).read_bytes() == first


def test_a_rewrite_says_what_was_added_and_removed(repo: Path, capsys):
    _write_baseline(capsys)
    write(repo, "legacy.py", "import google.genai\n\n\ndef old(x):\n    return x\n")  # fixed the eval
    write(repo, "more.py", "y = eval('1')\n")
    out = _write_baseline(capsys)
    assert "2 finding(s)" in out and "1 added, 1 removed since the last baseline" in out


def test_untracked_files_are_in_the_baseline_too(repo: Path, capsys):
    write(repo, "fresh.py", "z = eval('1')\n")  # never added to git
    _write_baseline(capsys)
    assert "fresh.py" in {e["path"] for e in _held(repo)}


def test_git_ignored_files_are_not(repo: Path, capsys):
    write(repo, ".gitignore", "ignored.py\n")
    write(repo, "ignored.py", "z = eval('1')\n")
    _write_baseline(capsys)
    assert "ignored.py" not in {e["path"] for e in _held(repo)}


def test_write_baseline_works_outside_git(tmp_path: Path, monkeypatch, capsys):
    root = tmp_path / "plain"
    write(root, ".aegis/rules/invariants/no-eval.md", NO_EVAL)
    write(root, "app.py", "x = eval('1')\n")
    monkeypatch.chdir(root)
    assert _run(capsys, "--write-baseline")[0] == 0
    assert [e["path"] for e in _held(root)] == ["app.py"]


def test_write_baseline_names_the_failures_it_cannot_record(repo: Path, capsys):
    write(repo, "broken.py", "def (:\n")
    rc, out, _ = _run(capsys, "--write-baseline")
    assert rc == 0
    assert re.search(r"\d+ failure\(s\) cannot be baselined and keep failing aegis check", out)
    assert "broken.py" in out
    assert "broken.py" not in {e["path"] for e in _held(repo)}
    assert _run(capsys, "legacy.py", "broken.py")[0] == 1  # and the check still fails on it


def test_write_baseline_json_carries_the_envelope(repo: Path, capsys):
    rc, payload, _ = _json(capsys, "--write-baseline")
    assert rc == 0
    assert payload["source"] == "aegis check --write-baseline"
    assert payload["aegis_version"] == __version__ and TS.match(payload["checked_at"])
    assert payload["scope"]["workspace"] == str(repo)
    assert payload["status"] == "written" and payload["path"] == BASELINE
    assert (payload["entries"], payload["added"], payload["removed"]) == (2, 2, 0)
    assert payload["files_checked"] == 2 and payload["unbaselinable"] == []


def test_write_baseline_records_a_baseline_written_event(repo: Path, capsys):
    _write_baseline(capsys)
    (row,) = events.read(repo, "baseline_written").rows
    assert row["result"] == "written"
    assert row["detail"]["entries"] == 2 and row["detail"]["mode"] == "write"


def test_write_baseline_refuses_a_symlinked_baseline(repo: Path, capsys, tmp_path: Path):
    if os.name == "nt":
        pytest.skip("symlinks need privileges on Windows")
    elsewhere = tmp_path / "elsewhere.json"
    elsewhere.write_text("keep", encoding="utf-8")
    os.symlink(elsewhere, repo / BASELINE)
    rc, _, err = _run(capsys, "--write-baseline")
    assert rc == 1 and "is a symlink" in err
    assert elsewhere.read_text(encoding="utf-8") == "keep"


def test_an_invalid_previous_baseline_is_replaced_and_said(repo: Path, capsys):
    write(repo, BASELINE, "{oops")
    rc, out, _ = _run(capsys, "--write-baseline")
    assert rc == 0 and "the previous baseline was not valid (.aegis/baseline.json: not valid JSON)" in out
    assert len(_held(repo)) == 2


# ── check against the working tree's baseline (self-attested) ────────────────

def test_without_a_baseline_check_is_unchanged(repo: Path, capsys):
    rc, out, _ = _run(capsys, "legacy.py")
    assert rc == 1 and "baseline" not in out
    rc, payload, _ = _json(capsys, "legacy.py")
    assert rc == 1 and "baseline" not in payload


def test_a_baselined_repository_passes_and_labels_the_baseline(repo: Path, capsys):
    _write_baseline(capsys)
    rc, out, err = _run(capsys, "legacy.py")
    assert rc == 0, out + err
    assert "baseline: working tree (self-attested): 2 finding(s) grandfathered, 0 new" in out
    assert "PASSED" in out


def test_a_new_finding_fails_and_is_named(repo: Path, capsys):
    _write_baseline(capsys)
    write(repo, "fresh.py", "def run(x):\n    return eval(x)\n")
    rc, out, _ = _run(capsys, "fresh.py", "legacy.py")
    assert rc == 1
    assert "baseline: working tree (self-attested): 2 finding(s) grandfathered, 1 new" in out
    assert "new: fresh.py:2 forbid_ast:no-eval  return eval(x)" in out


def test_a_new_finding_in_a_baselined_file_fails(repo: Path, capsys):
    _write_baseline(capsys)
    write(repo, "legacy.py", "import google.genai\n\n\ndef old(x):\n    return eval(x)\n\n\ndef worse(x):\n    return eval(x + 1)\n")
    rc, out, _ = _run(capsys, "legacy.py")
    assert rc == 1 and "1 new" in out and "legacy.py:9" in out


def test_inserting_lines_above_a_baselined_finding_does_not_fail(repo: Path, capsys):
    _write_baseline(capsys)
    write(repo, "legacy.py", "# a new header\n# and another\nimport google.genai\n\n\ndef old(x):\n    return eval(x)\n")
    assert _run(capsys, "legacy.py")[0] == 0


def test_json_reports_the_baseline_and_its_effect(repo: Path, capsys):
    _write_baseline(capsys)
    write(repo, "fresh.py", "def run(x):\n    return eval(x)\n")
    rc, payload, _ = _json(capsys, "fresh.py", "legacy.py")
    assert rc == 1 and payload["passed"] is False
    info = payload["baseline"]
    assert info["label"] == "baseline: working tree (self-attested)" and info["source"] == "working-tree"
    assert info["commit"] is None and info["entries"] == 2 and info["grandfathered"] == 2
    assert [(f["path"], f["line"], f["rule"]) for f in info["new"]] == [("fresh.py", 2, "forbid_ast:no-eval")]
    assert info["blocked"] == []
    grandfathered = [e for e in payload["layer1"] if "grandfathered" in e["detail"]]
    assert grandfathered and all(e["verdict"] for e in grandfathered)


def test_a_failure_that_cannot_be_baselined_still_fails(repo: Path, capsys):
    _write_baseline(capsys)
    write(repo, "broken.py", "def (:\n")
    rc, payload, _ = _json(capsys, "broken.py", "legacy.py")
    assert rc == 1
    assert payload["baseline"]["new"] == [] and len(payload["baseline"]["blocked"]) >= 1


def test_an_invalid_working_tree_baseline_fails_the_check_loudly(repo: Path, capsys):
    write(repo, BASELINE, '{"v": 2, "findings": []}')
    rc, out, err = _run(capsys, "clean.py")
    assert rc == 1
    assert "Error: .aegis/baseline.json: v must be 1" in err
    assert "PASSED" not in out


def test_the_check_records_a_baseline_check_event(repo: Path, capsys):
    _write_baseline(capsys)
    _run(capsys, "legacy.py")
    write(repo, "fresh.py", "def run(x):\n    return eval(x)\n")
    _run(capsys, "fresh.py")
    rows = events.read(repo, "baseline_check").rows
    assert [r["result"] for r in rows] == ["pass", "fail"]
    assert rows[1]["detail"]["new"] == 1 and rows[1]["detail"]["source"] == "working-tree"


def test_a_check_without_a_baseline_records_no_baseline_event(repo: Path, capsys):
    _run(capsys, "legacy.py")
    assert events.read(repo, "baseline_check").rows == []


# ── check --base: the baseline comes from the base, never the candidate ──────

def _feature(repo: Path) -> None:
    git(repo, "checkout", "-q", "-b", "feature")


def _baseline_on_main(repo: Path, capsys) -> str:
    _write_baseline(capsys)
    return commit(repo, "baseline on main")


def test_a_candidate_cannot_excuse_itself_by_editing_its_own_baseline(repo: Path, capsys):
    tip = _baseline_on_main(repo, capsys)
    _feature(repo)
    write(repo, "evil.py", "def run(x):\n    return eval(x)\n")
    _write_baseline(capsys)  # the candidate re-baselines, absorbing its new finding
    commit(repo, "candidate widens its baseline")

    rc, out, _ = _run(capsys)  # no base: the candidate's own file is trusted, and says so
    assert rc == 0 and "baseline: working tree (self-attested)" in out

    rc, out, _ = _run(capsys, "--base", "main")
    assert rc == 1
    assert f"baseline: base@{tip}: 0 finding(s) grandfathered, 1 new" in out
    assert "new: evil.py:2 forbid_ast:no-eval" in out


def test_an_uncommitted_edit_of_the_baseline_is_ignored_with_a_base(repo: Path, capsys):
    _baseline_on_main(repo, capsys)
    _feature(repo)
    write(repo, "evil.py", "def run(x):\n    return eval(x)\n")
    _write_baseline(capsys)  # left uncommitted
    rc, out, _ = _run(capsys, "--base", "main", "evil.py")
    assert rc == 1 and "1 new" in out


def test_a_baseline_absent_at_base_is_empty_and_the_candidate_cannot_supply_one(repo: Path, capsys):
    _feature(repo)
    _write_baseline(capsys)
    commit(repo, "candidate adds a baseline where main has none")
    rc, out, _ = _run(capsys, "--base", "main", "legacy.py")
    assert rc == 1
    assert "baseline: absent at base: 0 finding(s) grandfathered, 2 new" in out


def test_a_base_that_does_not_resolve_fails_and_never_falls_back(repo: Path, capsys):
    _write_baseline(capsys)
    rc, out, err = _run(capsys, "--base", "origin/nope", "legacy.py")
    assert rc == 1
    assert "Error: cannot resolve the base 'origin/nope' to a commit" in err
    assert "PASSED" not in out and "grandfathered" not in out


def test_an_invalid_baseline_at_base_fails_and_names_the_base(repo: Path, capsys):
    write(repo, BASELINE, "{oops")
    commit(repo, "bad baseline on main")
    _feature(repo)
    write(repo, BASELINE, baseline.render([]))
    commit(repo, "candidate repairs it")
    rc, _, err = _run(capsys, "--base", "main", "clean.py")
    assert rc == 1 and "Error: .aegis/baseline.json at main: not valid JSON" in err


def test_base_selects_the_files_the_candidate_changed_since_it(repo: Path, capsys):
    _baseline_on_main(repo, capsys)
    _feature(repo)
    write(repo, "evil.py", "def run(x):\n    return eval(x)\n")
    commit(repo, "candidate")  # committed: the working tree is clean
    rc, payload, _ = _json(capsys, "--base", "main")
    assert payload["files"] == ["evil.py"]
    assert rc == 1 and [f["path"] for f in payload["baseline"]["new"]] == ["evil.py"]


def test_base_checks_uncommitted_changes_too(repo: Path, capsys):
    _baseline_on_main(repo, capsys)
    _feature(repo)
    write(repo, "one.py", "x = 1\n")
    commit(repo, "committed")
    write(repo, "one.py", "x = eval('1')\n")  # not committed yet
    rc, payload, _ = _json(capsys, "--base", "main")
    assert payload["files"] == ["one.py"] and rc == 1


def test_a_clean_candidate_passes_against_the_base_baseline(repo: Path, capsys):
    tip = _baseline_on_main(repo, capsys)
    _feature(repo)
    write(repo, "extra.py", "def tidy():\n    return 1\n")
    commit(repo, "candidate adds a clean file")
    rc, payload, err = _json(capsys, "--base", "main")
    assert rc == 0, err
    assert payload["baseline"]["label"] == f"baseline: base@{tip}"
    assert payload["baseline"]["commit"] == tip and payload["baseline"]["source"] == "base"


def test_base_with_explicit_files_checks_those_files(repo: Path, capsys):
    tip = _baseline_on_main(repo, capsys)
    rc, out, _ = _run(capsys, "--base", "main", "legacy.py")
    assert rc == 0 and f"baseline: base@{tip}: 2 finding(s) grandfathered, 0 new" in out


def test_base_outside_git_is_a_usage_error(tmp_path: Path, monkeypatch, capsys):
    root = tmp_path / "plain"
    (root / ".aegis").mkdir(parents=True)
    write(root, "a.py", "x = 1\n")
    monkeypatch.chdir(root)
    rc, _, err = _run(capsys, "--base", "main", "a.py")
    assert rc == 2 and "--base needs a git work tree" in err


def test_the_event_names_the_base_provenance(repo: Path, capsys):
    _baseline_on_main(repo, capsys)
    _feature(repo)
    write(repo, "evil.py", "def run(x):\n    return eval(x)\n")
    commit(repo, "candidate")
    _run(capsys, "--base", "main")
    rows = events.read(repo, "baseline_check").rows
    assert rows[-1]["result"] == "fail"
    assert rows[-1]["detail"]["source"] == "base" and rows[-1]["detail"]["label"].startswith("baseline: base@")


# ── --prune-baseline ─────────────────────────────────────────────────────────

def test_prune_drops_the_entries_whose_findings_are_gone(repo: Path, capsys):
    _write_baseline(capsys)
    write(repo, "legacy.py", "import google.genai\n\n\ndef old(x):\n    return x\n")  # the eval is fixed
    rc, out, _ = _run(capsys, "--prune-baseline")
    assert rc == 0
    assert "pruned .aegis/baseline.json: dropped 1 fixed finding(s), 1 kept" in out
    assert [e["rule"] for e in _held(repo)] == ["import_guard"]
    assert _run(capsys, "legacy.py")[0] == 0


def test_prune_never_adds_a_finding(repo: Path, capsys):
    _write_baseline(capsys)
    write(repo, "legacy.py", "import google.genai\n\n\ndef old(x):\n    return x\n")
    write(repo, "fresh.py", "y = eval('1')\n")
    rc, out, _ = _run(capsys, "--prune-baseline")
    assert rc == 0 and "1 current finding(s) are not in the baseline and were not added" in out
    assert "fresh.py" not in {e["path"] for e in _held(repo)}


def test_prune_drops_the_entries_of_a_deleted_file(repo: Path, capsys):
    _write_baseline(capsys)
    (repo / "legacy.py").unlink()
    rc, out, _ = _run(capsys, "--prune-baseline")
    assert rc == 0 and _held(repo) == [] and "dropped 2 fixed finding(s), 0 kept" in out


def test_prune_with_nothing_to_drop_leaves_the_file_alone(repo: Path, capsys):
    _write_baseline(capsys)
    before = (repo / BASELINE).read_bytes()
    rc, out, _ = _run(capsys, "--prune-baseline")
    assert rc == 0 and "nothing to prune: every entry still matches a finding" in out
    assert (repo / BASELINE).read_bytes() == before
    assert events.read(repo, "baseline_written").rows[-1]["result"] == "written"  # no "pruned" row


def test_prune_without_a_baseline_is_an_error(repo: Path, capsys):
    rc, _, err = _run(capsys, "--prune-baseline")
    assert rc == 1 and "no baseline to prune: .aegis/baseline.json does not exist" in err


def test_prune_keeps_the_entries_of_a_file_it_could_not_check(repo: Path, capsys):
    _write_baseline(capsys)
    write(repo, "legacy.py", "def (:\n")  # no longer parses: its findings cannot be judged fixed
    rc, out, _ = _run(capsys, "--prune-baseline")
    assert rc == 0 and "nothing to prune" in out
    assert len(_held(repo)) == 2


def test_prune_refuses_when_the_checks_could_not_run_at_all(repo: Path, capsys):
    _write_baseline(capsys)
    write(repo, ".aegis/rules/invariants/broken.md", "---\nid: broken\ntype: invariant\nforbid_ast: [eval]\n---\nx\n")
    before = (repo / BASELINE).read_bytes()
    rc, _, err = _run(capsys, "--prune-baseline")
    assert rc == 1 and "cannot prune: a check could not run" in err
    assert (repo / BASELINE).read_bytes() == before


def test_prune_records_a_pruned_event(repo: Path, capsys):
    _write_baseline(capsys)
    (repo / "legacy.py").unlink()
    _run(capsys, "--prune-baseline")
    last = events.read(repo, "baseline_written").rows[-1]
    assert last["result"] == "pruned" and last["detail"]["mode"] == "prune" and last["detail"]["removed"] == 2


def test_prune_json_carries_the_envelope(repo: Path, capsys):
    _write_baseline(capsys)
    (repo / "legacy.py").unlink()
    rc, payload, _ = _json(capsys, "--prune-baseline")
    assert rc == 0
    assert payload["source"] == "aegis check --prune-baseline" and TS.match(payload["checked_at"])
    assert payload["status"] == "pruned" and (payload["removed"], payload["kept"], payload["entries"]) == (2, 0, 0)


# ── The pre-commit hook ──────────────────────────────────────────────────────

def test_the_hook_honours_the_baseline_for_staged_files(repo: Path, capsys):
    _write_baseline(capsys)
    write(repo, "legacy.py", "# touched\nimport google.genai\n\n\ndef old(x):\n    return eval(x)\n")
    git(repo, "add", "legacy.py")
    rc, out, err = _run(capsys, "--hook")
    assert rc == 0, out + err
    assert "baseline: working tree (self-attested): 2 finding(s) grandfathered, 0 new" in out


def test_the_hook_reads_the_staged_content_for_new_findings(repo: Path, capsys):
    _write_baseline(capsys)
    write(repo, "legacy.py", "import google.genai\n\n\ndef old(x):\n    return eval(x)\n\n\ndef new(x):\n    return eval(x + 1)\n")
    git(repo, "add", "legacy.py")
    write(repo, "legacy.py", "import google.genai\n\n\ndef old(x):\n    return eval(x)\n")  # reverted, unstaged
    rc, out, _ = _run(capsys, "--hook")
    assert rc == 1 and "legacy.py:9" in out

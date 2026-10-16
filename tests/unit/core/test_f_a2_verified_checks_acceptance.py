"""Acceptance contract for lane f-a2-verified-checks (v4.3 spec §3 T1, §9; v4.4 spec §12).

Given/When/Then, written before the code and never weakened to make it pass:

1. No credit without CI confirmation: a check row is a label until the required workflow on the
   landing commit concluded success; a failing run voids it, and only ``confirmed`` counts.
2. Hidden files cannot fake a pass: an assume-unchanged file makes the tree unbindable, and a file
   hidden through .git/info/exclude is not in the snapshot the tests run on.
3. A file swap during the run does not reach the snapshot, and the row binds the tree that was run.
4. A ``conftest.py`` change is protected: the row says so and credit is withheld until approved.
5. Exit 5 and zero passed tests are never evidence; a failing check is never a witness.
6. The repository never chooses the command that runs.
7. A report with no check row for the current tree writes at most one ``claimed`` row per
   (session, tree), never earns credit, and the session is capped.
8. The credited rules are the ones the server saw: exposed in this session's scans and matching the
   change; the agent's ``rules_used`` is ignored.
"""
from __future__ import annotations

import os
from pathlib import Path
import subprocess

import pytest

from aegis_core import checkrun, credit, treeid
from aegis_core.telemetry_engine import ledger
from tests import helpers_humangate as hg
from tests import helpers_verified as hv

needs_git = pytest.mark.skipif(not hg.git_ok(), reason="needs git")

SECOND_RULE = ("---\nid: trap-docs\ntype: trap\nenforcement: advisory\nhypothesis: docs\n"
               "target_paths:\n  - docs/*.md\n---\n# Docs\n\nBody long enough to be a rule body.\n")
THIRD_RULE = ("---\nid: trap-src\ntype: trap\nenforcement: advisory\nhypothesis: src\n"
              "target_paths:\n  - src/*.py\n---\n# Src\n\nBody long enough to be a rule body.\n")


@pytest.fixture(autouse=True)
def _home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    for name in ("HOME", "USERPROFILE"):
        monkeypatch.setenv(name, str(home))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.delenv("GIT_CONFIG_GLOBAL", raising=False)


def _edit_app(repo: hg.Repo, value: int = 2) -> None:
    repo.write("src/app.py", f"def app():\n    return {value}\n")


def _scan(repo: hg.Repo, files=("src/app.py",), session: str = "sess-1") -> None:
    res = hv.mcp_call("aegis_scan", repo.root, session=session, files=list(files))
    assert res.get("status") != "FAIL", res


def _report(repo: hg.Repo, rules=("trap-sample",), key: str = "k1", outcome: str = "success", session: str = "sess-1"):
    return hv.mcp_call("aegis_report_outcome", repo.root, session=session, outcome=outcome,
                       rules_used=list(rules), idempotency_key=key)


def _landed(repo: hg.Repo):
    return credit.landed_lookup(repo.root, refs=("HEAD",))


def _credits(repo: hg.Repo, approved=None):
    return credit.derive(credit.read_rows(repo.root), landed=_landed(repo), approved=approved)


# ── 1. No credit without CI confirmation ─────────────────────────────────────

@needs_git
@pytest.mark.parametrize("runs,state,counts", [
    ([("success", "completed")], "confirmed", True),
    ([("failure", "completed")], "voided", False),
    ([("timed_out", "completed")], "voided", False),
    ([("cancelled", "completed")], "landed", False),
    ([(None, "in_progress")], "landed", False),
    ([], "landed", False),
])
def test_only_a_ci_confirmed_landing_counts(tmp_path, runs, state, counts):
    repo = hv.make_project(tmp_path)
    hv.use_stub_runner(repo.home.path)
    _edit_app(repo)
    _scan(repo)
    out = checkrun.record(repo.root, tests=True)
    assert out.status == "recorded" and out.row["witness"] == "aegis"
    assert _report(repo)["status"] == "recorded"
    assert [c.state for c in _credits(repo)] == ["witnessed"]  # a label until it lands
    commit = repo.commit("work")
    client = hv.FakeCI([hv.ci_run(commit, conclusion, status=status, run_id=i + 1)
                        for i, (conclusion, status) in enumerate(runs)])
    credit.confirm(repo.root, client=client, workflow=hv.CI_WORKFLOW, landed=_landed(repo))
    derived, = _credits(repo)
    assert (derived.rule, derived.state, derived.counts) == ("trap-sample", state, counts)
    rows = credit.confirmed_outcome_rows(_credits(repo))
    assert [r["rule"] for r in rows] == (["trap-sample"] if counts else [])
    # nothing in the ledger scores the rule before CI said so
    assert ledger.aggregate(repo.root, "trap-sample")["triggers"] == 0


@needs_git
def test_a_check_that_never_landed_stays_a_label(tmp_path):
    repo = hv.make_project(tmp_path)
    hv.use_stub_runner(repo.home.path)
    _edit_app(repo)
    _scan(repo)
    checkrun.record(repo.root, tests=True)
    _report(repo)
    credit.confirm(repo.root, client=hv.FakeCI(), workflow=hv.CI_WORKFLOW, landed=_landed(repo))
    derived, = _credits(repo)
    assert derived.state == "witnessed" and not derived.counts


@needs_git
def test_a_void_row_is_terminal_even_when_ci_later_succeeds(tmp_path):
    repo = hv.make_project(tmp_path)
    hv.use_stub_runner(repo.home.path)
    _edit_app(repo)
    _scan(repo)
    out = checkrun.record(repo.root, tests=True)
    _report(repo)
    commit = repo.commit("work")
    credit.record_void(repo.root, out.row["id"], "ci_divergence")
    credit.confirm(repo.root, client=hv.FakeCI([hv.ci_run(commit)]), workflow=hv.CI_WORKFLOW, landed=_landed(repo))
    derived, = _credits(repo)
    assert derived.state == "voided" and derived.reason == "ci_divergence" and not derived.counts


# ── 2. Hidden files cannot fake a pass ───────────────────────────────────────

@needs_git
def test_an_assume_unchanged_file_makes_the_tree_unbindable_and_gives_no_label(tmp_path):
    repo = hv.make_project(tmp_path)
    hv.use_stub_runner(repo.home.path)
    repo.git("update-index", "--assume-unchanged", "src/app.py")
    _edit_app(repo, 999)  # git no longer sees the edit
    out = checkrun.record(repo.root, tests=True)
    assert out.status == "unbindable" and out.row is None
    assert "assume-unchanged" in out.reason
    assert hv.rows_of(repo.root, "check") == []
    _scan(repo)
    res = _report(repo)
    assert res["witness"] == "self" and res["status"] == "claimed"


@needs_git
def test_a_skip_worktree_file_present_on_disk_makes_the_tree_unbindable(tmp_path):
    repo = hv.make_project(tmp_path)
    hv.use_stub_runner(repo.home.path)
    repo.git("update-index", "--skip-worktree", "src/app.py")
    _edit_app(repo, 999)
    out = checkrun.record(repo.root, tests=True)
    assert out.status == "unbindable" and "skip-worktree" in out.reason


@needs_git
def test_a_file_hidden_through_info_exclude_is_not_in_the_snapshot_so_the_run_fails(tmp_path):
    repo = hv.make_project(tmp_path, runner="import sys\nimport hidden_helper\nprint('3 passed in 0s')\n")
    hv.use_stub_runner(repo.home.path)
    (repo.root / ".git" / "info").mkdir(exist_ok=True)
    (repo.root / ".git" / "info" / "exclude").write_text("hidden_helper.py\n", encoding="utf-8")
    repo.write("hidden_helper.py", "FORGED = True\n")
    _edit_app(repo)
    out = checkrun.record(repo.root, tests=True)
    assert out.status == "recorded"
    assert out.row["passed"] is False and out.row["exit"] != 0
    assert "hidden_helper.py" not in treeid.tree_files(repo.root)
    _scan(repo)
    assert _report(repo)["witness"] == "self"


@needs_git
def test_sabotage_after_the_check_changes_the_tree_and_loses_the_label(tmp_path):
    repo = hv.make_project(tmp_path)
    hv.use_stub_runner(repo.home.path)
    _edit_app(repo)
    _scan(repo)
    out = checkrun.record(repo.root, tests=True)
    assert out.row["passed"] is True
    repo.write("src/app.py", "def app():\n    raise SystemExit(1)\n")  # sabotage after verification
    res = _report(repo)
    assert res["witness"] == "self" and res["status"] == "claimed"
    assert _credits(repo) == []


# ── 3. File swaps do not fool the snapshot ───────────────────────────────────

@needs_git
@pytest.mark.skipif(os.name == "nt", reason="symlinks are POSIX here")
def test_a_tree_holding_any_symlink_gets_no_witness_label(tmp_path):
    repo = hv.make_project(tmp_path)
    hv.use_stub_runner(repo.home.path)
    _edit_app(repo)
    os.symlink("app.py", repo.root / "src" / "alias.py")  # inside the tree, still refused
    _scan(repo)
    out = checkrun.record(repo.root, tests=True, base="main")
    assert out.status == "unbindable" and out.row is None and "src/alias.py" in out.reason
    res = _report(repo)
    assert res["witness"] == "self" and res["status"] == "claimed"
    assert _credits(repo) == []


@needs_git
def test_a_swap_during_the_run_does_not_reach_the_snapshot(tmp_path):
    root = tmp_path / "project"
    swap = (
        "import os, pathlib, sys\n"
        f"pathlib.Path({str(root)!r}, 'src', 'app.py').write_text('def app():\\n    return 999\\n')\n"
        "sys.path.insert(0, os.getcwd())\n"
        "from src.app import app\n"
        "ok = app() == 2\n"
        "print('1 passed in 0s' if ok else '1 failed in 0s')\n"
        "sys.exit(0 if ok else 1)\n"
    )
    repo = hv.make_project(tmp_path, runner=swap)
    hv.use_stub_runner(repo.home.path)
    _edit_app(repo, 2)
    before = hv.tree_now(repo.root)
    out = checkrun.record(repo.root, tests=True)
    assert out.status == "recorded"
    assert out.row["tree"] == before  # the row names the tree that was run, not the swapped one
    assert out.row["passed"] is True  # the snapshot still held the version that returns 2
    assert hv.tree_now(repo.root) != before  # and the swap really happened in the work tree
    _scan(repo)
    assert _report(repo)["witness"] == "self"  # the work tree no longer is the verified tree


# ── 4. conftest.py changes are gated ─────────────────────────────────────────

@needs_git
def test_a_conftest_change_is_protected_and_earns_no_credit_until_approved(tmp_path):
    repo = hv.make_project(tmp_path)
    hv.use_stub_runner(repo.home.path)
    repo.write("conftest.py", "import pytest\n")
    _edit_app(repo)
    _scan(repo)
    out = checkrun.record(repo.root, tests=True, base="main")
    assert out.row["protected_changed"] is True and "test-infra" in out.row["protected"]
    assert _report(repo)["status"] == "recorded"
    commit = repo.commit("work")
    credit.confirm(repo.root, client=hv.FakeCI([hv.ci_run(commit)]), workflow=hv.CI_WORKFLOW, landed=_landed(repo))
    withheld, = _credits(repo)
    assert withheld.state == "confirmed" and withheld.counts is False and withheld.reason == "protected_changed"
    assert credit.confirmed_outcome_rows(_credits(repo)) == []
    approved, = _credits(repo, approved=lambda check_id, categories: True)
    assert approved.counts is True


@needs_git
def test_an_unprotected_change_has_protected_changed_false(tmp_path):
    repo = hv.make_project(tmp_path)
    hv.use_stub_runner(repo.home.path)
    _edit_app(repo)
    out = checkrun.record(repo.root, tests=True, base="main")
    assert out.row["protected_changed"] is False and out.row["protected"] == []


# ── 5. Exit 5, zero passed and failures are never evidence ───────────────────

@needs_git
@pytest.mark.parametrize("runner", [hv.NO_TESTS, hv.ZERO_PASSED, hv.FAILING])
def test_a_run_without_passing_tests_is_never_a_witness(tmp_path, runner):
    repo = hv.make_project(tmp_path, runner=runner)
    hv.use_stub_runner(repo.home.path)
    _edit_app(repo)
    _scan(repo)
    out = checkrun.record(repo.root, tests=True)
    assert out.status == "recorded" and out.row["passed"] is False
    res = _report(repo)
    assert res["witness"] == "self" and res["status"] == "claimed"
    assert _credits(repo) == []


# ── 6. The repository never chooses the command ──────────────────────────────

@needs_git
def test_the_repository_config_cannot_name_the_test_command(tmp_path):
    marker = tmp_path / "evil-ran"
    repo = hv.make_project(tmp_path)
    repo.write("evil.py", f"import pathlib\npathlib.Path({str(marker)!r}).write_text('x')\n")
    repo.write(".aegis/config.json", '{"v": 1, "tests": {"command": "python evil.py"}}\n')
    repo.commit("repo config names a command")
    _edit_app(repo)
    out = checkrun.record(repo.root, tests=True, base="main")
    assert not marker.exists()
    assert out.row["tests"]["exit"] != 0 or out.row["passed"] is False


# ── 7. The limited-write tier ────────────────────────────────────────────────

@needs_git
def test_a_report_with_no_check_row_writes_one_claimed_row_per_session_and_tree(tmp_path):
    repo = hv.make_project(tmp_path)
    _edit_app(repo)
    _scan(repo)
    first = _report(repo, key="a", rules=("trap-sample",), outcome="success")
    again = _report(repo, key="b", rules=("trap-sample", "trap-sample"), outcome="failure")
    assert first["status"] == again["status"] == "claimed"
    assert first["witness"] == "self" and first.get("credited", []) == []
    assert len(hv.rows_of(repo.root, "claimed")) == 1
    assert hv.rows_of(repo.root, "report") == []
    agg = ledger.aggregate(repo.root, "trap-sample")
    assert (agg["triggers"], agg["tp"], agg["fp"]) == (0, 0, 0)
    assert _credits(repo) == []
    other = _report(repo, key="c", session="sess-2")  # another session is another claim
    assert other["status"] == "claimed" and len(hv.rows_of(repo.root, "claimed")) == 2
    _edit_app(repo, 3)  # and another tree is another claim
    _report(repo, key="d")
    assert len(hv.rows_of(repo.root, "claimed")) == 3


@needs_git
def test_claimed_rows_have_their_own_count_apart_from_per_rule_evidence(tmp_path):
    repo = hv.make_project(tmp_path)
    _edit_app(repo)
    _report(repo)
    summary = credit.claimed_summary(repo.root)
    assert summary["claimed"] == 1 and summary["sessions"] == 1 and summary["label"] == "claimed (unwitnessed)"
    assert ledger.aggregate(repo.root) == {}


@needs_git
@pytest.mark.parametrize("command", ["status", "sync"])
def test_status_and_sync_show_claims_apart_from_every_rule(tmp_path, monkeypatch, capsys, command):
    import json

    from aegis_cli.cli import main

    repo = hv.make_project(tmp_path)
    _edit_app(repo)
    _scan(repo)
    assert _report(repo)["status"] == "claimed"
    monkeypatch.chdir(repo.root)
    capsys.readouterr()
    main([command, "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["claimed"] == {"label": "claimed (unwitnessed)", "claimed": 1, "sessions": 1}
    rules = {r.get("name") or r.get("id"): r for r in payload["rules"]}
    assert rules["trap-sample"]["triggers"] == 0


@needs_git
def test_a_rate_limited_report_writes_nothing_and_says_so(tmp_path, monkeypatch):
    repo = hv.make_project(tmp_path)
    monkeypatch.setattr(credit, "MAX_REPORT_ROWS_PER_SESSION", 1)
    _edit_app(repo)
    assert _report(repo, key="a")["status"] == "claimed"
    _edit_app(repo, 3)
    before = hv.ledger_path(repo.root).read_bytes()
    limited = _report(repo, key="b", rules=("trap-sample",))
    assert limited["status"] == "rate_limited" and limited["limit"] == 1 and limited["credited"] == []
    assert hv.ledger_path(repo.root).read_bytes() == before


@needs_git
def test_the_report_result_carries_the_machine_readable_head(tmp_path):
    repo = hv.make_project(tmp_path)
    _edit_app(repo)
    res = _report(repo)
    assert res["source"] == "aegis_report_outcome" and res["aegis_version"]
    assert res["checked_at"].endswith("Z") and res["scope"] == {"tree": hv.tree_now(repo.root)}


def test_the_session_cap_is_a_documented_constant():
    assert credit.MAX_REPORT_ROWS_PER_SESSION == 200


@needs_git
def test_a_flood_of_reports_leaves_the_ledger_bounded(tmp_path, monkeypatch):
    repo = hv.make_project(tmp_path)
    trees = [f"{n:040x}" for n in range(1, 400)]
    state = {"n": 0}

    def fake_tree(root):
        state["n"] += 1
        return treeid.TreeBinding("ok", trees[state["n"] % len(trees)], "")

    monkeypatch.setattr(treeid, "tree_of", fake_tree)
    results = [_report(repo, key=f"k{n}") for n in range(10_000)]
    statuses = {r["status"] for r in results}
    assert "rate_limited" in statuses
    written = [r for r in hv.ledger_rows(repo.root) if r.get("event") in ("claimed", "report")]
    assert len(written) <= credit.MAX_REPORT_ROWS_PER_SESSION
    limited = next(r for r in results if r["status"] == "rate_limited")
    assert limited["limit"] == credit.MAX_REPORT_ROWS_PER_SESSION
    assert len(hv.ledger_rows(repo.root)) <= credit.MAX_REPORT_ROWS_PER_SESSION


@needs_git
def test_the_cap_is_per_session_so_another_session_still_reports(tmp_path, monkeypatch):
    repo = hv.make_project(tmp_path)
    monkeypatch.setattr(credit, "MAX_REPORT_ROWS_PER_SESSION", 2)
    counter = {"n": 0}

    def fake_tree(root):
        counter["n"] += 1
        return treeid.TreeBinding("ok", f"{counter['n']:040x}", "")

    monkeypatch.setattr(treeid, "tree_of", fake_tree)
    assert [_report(repo, key=f"a{n}")["status"] for n in range(4)] == ["claimed", "claimed", "rate_limited", "rate_limited"]
    assert _report(repo, key="z", session="sess-2")["status"] == "claimed"


# ── 8. The credited rules are the server's, not the agent's ──────────────────

@needs_git
def test_the_credited_rules_are_exposed_in_the_session_and_match_the_change(tmp_path):
    repo = hv.make_project(tmp_path)
    repo.write(".aegis/rules/traps/trap-docs.md", SECOND_RULE)
    repo.write("docs/guide.md", "# guide\n")
    repo.commit("a second rule", allow_empty=False)
    hv.use_stub_runner(repo.home.path)
    _edit_app(repo)
    repo.write("docs/guide.md", "# guide v2\n")
    _scan(repo, files=("src/app.py",))  # only src is scanned: trap-docs is never exposed
    checkrun.record(repo.root, tests=True, base="main")
    res = _report(repo, rules=("trap-docs",))  # the agent names a rule it never saw
    assert res["status"] == "recorded" and res["credited"] == ["trap-sample"]
    assert [c.rule for c in _credits(repo)] == ["trap-sample"]


@needs_git
def test_an_exposed_rule_that_does_not_match_the_change_is_not_credited(tmp_path):
    repo = hv.make_project(tmp_path)
    repo.write(".aegis/rules/traps/trap-docs.md", SECOND_RULE)
    repo.write("docs/guide.md", "# guide\n")
    repo.commit("a second rule")
    hv.use_stub_runner(repo.home.path)
    repo.write("docs/guide.md", "# guide v2\n")  # the change touches only docs
    _scan(repo, files=("src/app.py", "docs/guide.md"))  # both rules were exposed
    checkrun.record(repo.root, tests=True, base="main")
    res = _report(repo, rules=("trap-sample", "trap-docs"))
    assert res["credited"] == ["trap-docs"]


@needs_git
def test_one_report_crediting_two_rules_writes_one_row_per_rule(tmp_path):
    repo = hv.make_project(tmp_path)
    repo.write(".aegis/rules/traps/trap-src.md", THIRD_RULE)
    repo.commit("a second src rule")
    hv.use_stub_runner(repo.home.path)
    _edit_app(repo)
    _scan(repo)
    assert _report(repo, key="early")["status"] == "claimed"  # before the check: a claim
    checkrun.record(repo.root, tests=True, base="main")
    res = _report(repo, key="early")  # the same key once a check exists still credits
    assert res["status"] == "recorded" and res["credited"] == ["trap-sample", "trap-src"]
    assert sorted(r["for_rule"] for r in hv.rows_of(repo.root, "report")) == ["trap-sample", "trap-src"]
    assert sorted(c.rule for c in _credits(repo)) == ["trap-sample", "trap-src"]


@needs_git
def test_a_rule_the_session_never_scanned_earns_nothing_whatever_the_agent_says(tmp_path):
    repo = hv.make_project(tmp_path)
    hv.use_stub_runner(repo.home.path)
    _edit_app(repo)
    checkrun.record(repo.root, tests=True, base="main")  # no scan in this session
    res = _report(repo, rules=("trap-sample",))
    assert res["credited"] == [] and hv.rows_of(repo.root, "report") == []


@needs_git
def test_the_tool_takes_no_receipt_and_keys_are_namespaced_by_server_session(tmp_path):
    from aegis_mcp.registry import TOOL_ARGUMENTS

    assert not {"receipt", "check", "tree", "token"} & set(TOOL_ARGUMENTS["aegis_report_outcome"])
    repo = hv.make_project(tmp_path)
    hv.use_stub_runner(repo.home.path)
    _edit_app(repo)
    _scan(repo)
    _scan(repo, session="sess-2")
    checkrun.record(repo.root, tests=True, base="main")
    first = _report(repo, key="same")
    retry = _report(repo, key="same")
    other = _report(repo, key="same", session="sess-2", outcome="failure")  # same key, another server session
    assert first["credited"] == retry["credited"] == ["trap-sample"]
    assert other["status"] == "recorded" and other["credited"] == ["trap-sample"]
    assert len(hv.rows_of(repo.root, "report")) == 1  # credit identity is (check, rule): unique
    conflict = _report(repo, key="same", outcome="failure")
    assert conflict["status"] == "FAIL" and "already used for a different report" in conflict["error"]


# ── Flaky runs are excluded without penalty ──────────────────────────────────

@needs_git
def test_a_tree_with_both_a_pass_and_a_fail_is_flaky_and_excluded(tmp_path):
    repo = hv.make_project(tmp_path)
    hv.use_stub_runner(repo.home.path)
    _edit_app(repo)
    _scan(repo)
    first = checkrun.record(repo.root, tests=True, base="main")
    assert first.row["run_ordinal"] == 1
    _report(repo)
    # the same tree, the same command, a different outcome: write the failing row the run would give
    failing = dict(first.row, passed=False, exit=1, run_ordinal=2, id="f" * 16)
    ledger.append_rows(repo.root, [failing])
    commit = repo.commit("work")
    credit.confirm(repo.root, client=hv.FakeCI([hv.ci_run(commit)]), workflow=hv.CI_WORKFLOW, landed=_landed(repo))
    derived, = _credits(repo)
    assert derived.flaky is True and derived.counts is False and derived.state != "voided"

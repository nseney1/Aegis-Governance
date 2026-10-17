"""Acceptance contract for lane f-b3-regression (v4.3 spec §3 T5, §9).

Given/When/Then, written before the code and never weakened to make it pass:

1. Trigger rule (two signals required):
   - A non-merge commit in ``merge-base(base, head)..head`` triggers T5 iff it has BOTH:
     (a) a Conventional Commit ``fix`` subject (``fix:``, ``fix(<scope>):``, ``fix!:``) with scope
         outside ``{ci, build, docs, deps, release, chore, tests}`` OR a ``Fixes:`` / ``Closes:``
         issue trailer, AND
     (b) at least one changed non-test, non-doc, non-config source file.
   - ``fix(ci):``, ``fix(docs):``, or a ``fix:`` commit touching only ``README.md`` or
     ``pyproject.toml`` does not trigger T5.
   - A non-fix commit (e.g. ``feat:``) touching ``src/app.py`` without tests does not trigger T5,
     but is reported in the non-failing ``untested_changes`` report.
2. Evidence: fail-to-pass on a temporary snapshot:
   - Overlaying the changed test files onto ``base`` source in a hermetic temporary directory and
     running pytest requires at least one test nodeid that FAILS on ``base`` (assertion/test
     failure, not collection syntax error) and PASSES on ``head``.
   - A tautological ``assert True`` test passes on ``base`` and therefore fails T5
     (``reason="passed_on_base"``).
   - A ``fix:`` commit with no test file changes fails T5 (``reason="no_test_changes"``).
   - The repository's working tree, index, refs, and object count are untouched by the run.
3. Exemptions require §2.2 ``human_gate`` approval:
   - An ``Aegis-No-Test: <reason>`` trailer alone is recorded as an explanation and never
     exempts a failing fix commit.
   - With a verified ``human_gate`` approval (signed ``Aegis-Approve`` from a key in ``base``'s
     ``allowed_signers``), the commit is ``exempted`` and ``exemption_rate`` is reported.
4. Rollout at warning tier in ``aegis check --ci``:
   - Default ``warning`` tier reports findings in ``regression`` in ``--format json`` and emits
     ``::warning`` annotations in ``--format github`` while exiting 0 when rules are intact.
   - At ``gate`` tier (``--strict`` or user config ``regression.tier="gate"``), unapproved
     regression failures exit 1 and emit ``::error`` annotations.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Tuple

import pytest

from aegis_cli.cli import main
from aegis_core import human_gate, regression
from tests import helpers_humangate as hg

needs_git = pytest.mark.skipif(not hg.git_ok(), reason="needs git")
needs_signing = pytest.mark.skipif(not hg.signing_ok(), reason="needs git >= 2.34 and ssh-keygen")


@pytest.fixture(autouse=True)
def _isolated_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    for name in ("HOME", "USERPROFILE"):
        monkeypatch.setenv(name, str(home))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.delenv("SSH_AUTH_SOCK", raising=False)
    monkeypatch.delenv("GIT_CONFIG_GLOBAL", raising=False)
    monkeypatch.delenv("GITHUB_BASE_REF", raising=False)
    monkeypatch.delenv("GITHUB_EVENT_PATH", raising=False)
    before = os.getcwd()
    yield
    os.chdir(before)


@pytest.fixture
def keys(tmp_path: Path) -> Dict[str, Any]:
    human, human_pub = hg.keygen(tmp_path / "keys", "human")
    return {"human": human, "human_pub": human_pub}


def make_calc_repo(tmp_path: Path, signer_pub: str | None = None) -> hg.Repo:
    """Create a repo on ``main`` with a buggy ``src/calc.py``, then check out ``work``."""
    home = hg.Home(tmp_path / "home")
    repo = hg.Repo(tmp_path / "project", home)
    repo.write("README.md", "# calc\n")
    repo.write("pyproject.toml", "[project]\nname = 'calc'\nversion = '0.1.0'\n")
    repo.write("src/__init__.py", "")
    repo.write(
        "src/calc.py",
        "def divide(a: int, b: int) -> float:\n"
        "    return a / b\n\n"
        "def add(a: int, b: int) -> int:\n"
        "    return a - b  # buggy on base!\n",
    )
    repo.write(
        "tests/test_calc.py",
        "from src.calc import divide\n\n"
        "def test_divide():\n"
        "    assert divide(6, 2) == 3.0\n",
    )
    if signer_pub is not None:
        repo.write("allowed_signers", hg.allowed_signers_text(signer_pub))
    repo.commit("initial base")
    repo.git("update-ref", "refs/remotes/origin/main", "HEAD")
    repo.git("symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")
    repo.branch("work")
    return repo


def run_ci(repo: hg.Repo, capsys: pytest.CaptureFixture[str], *extra: str, base: str = "main") -> Tuple[int, str, str]:
    os.chdir(repo.root)
    try:
        rc = main(["check", "--ci", "--base", base, *extra])
    except SystemExit as exc:
        rc = int(exc.code) if exc.code is not None else 0
    captured = capsys.readouterr()
    return rc, captured.out, captured.err


# ── 1. Trigger rule (two signals required) ───────────────────────────────────


@needs_git
@pytest.mark.parametrize(
    "message,touched_path,content",
    [
        ("fix(ci): adjust pipeline step", "src/calc.py", "def add(a, b):\n    return a + b\n"),
        ("fix(docs): clarify docstring", "src/calc.py", "def add(a, b):\n    return a + b\n"),
        ("fix(build): tweak wheel build", "src/calc.py", "def add(a, b):\n    return a + b\n"),
        ("fix(deps): bump dependency", "src/calc.py", "def add(a, b):\n    return a + b\n"),
        ("fix(release): tag script", "src/calc.py", "def add(a, b):\n    return a + b\n"),
        ("fix(chore): tidy formatting", "src/calc.py", "def add(a, b):\n    return a + b\n"),
        ("fix(tests): adjust test helper", "src/calc.py", "def add(a, b):\n    return a + b\n"),
        ("fix: typo in readme", "README.md", "# updated readme\n"),
        ("fix: bump project version", "pyproject.toml", "[project]\nname = 'calc'\nversion = '0.1.1'\n"),
    ],
)
def test_exempt_scopes_and_non_source_files_do_not_trigger_fail_to_pass(
    tmp_path: Path, message: str, touched_path: str, content: str
):
    repo = make_calc_repo(tmp_path)
    repo.write(touched_path, content)
    repo.commit(message)

    report = regression.check_ci_regressions(repo.root, "main", "HEAD")
    assert report.passed is True
    assert report.total_fix_commits == 0
    assert report.commits == ()
    assert report.findings == ()


@needs_git
def test_feat_commit_without_tests_does_not_trigger_t5_but_is_in_untested_changes(tmp_path: Path):
    repo = make_calc_repo(tmp_path)
    repo.write(
        "src/calc.py",
        "def divide(a: int, b: int) -> float:\n    return a / b\n\n"
        "def multiply(a: int, b: int) -> int:\n    return a * b\n",
    )
    oid = repo.commit("feat: add multiply function")

    report = regression.check_ci_regressions(repo.root, "main", "HEAD")
    assert report.passed is True
    assert report.total_fix_commits == 0
    assert report.findings == ()
    assert len(report.untested_changes) == 1
    untested = report.untested_changes[0]
    assert untested.commit == oid
    assert "src/calc.py" in untested.source_files


@needs_git
def test_fixes_or_closes_trailer_with_source_change_triggers_fail_to_pass(tmp_path: Path):
    repo = make_calc_repo(tmp_path)
    repo.write("src/calc.py", "def add(a: int, b: int) -> int:\n    return a + b\n")
    oid = repo.commit("resolve arithmetic issue\n\nFixes: #42")

    report = regression.check_ci_regressions(repo.root, "main", "HEAD")
    assert report.passed is False
    assert report.total_fix_commits == 1
    assert report.commits[0].commit == oid
    assert report.commits[0].reason == "no_test_changes"


# ── 2. Fail-to-pass execution (base + new tests vs head) ─────────────────────


@needs_git
def test_real_fail_to_pass_regression_test_passes(tmp_path: Path):
    repo = make_calc_repo(tmp_path)
    repo.write(
        "src/calc.py",
        "def divide(a: int, b: int) -> float:\n"
        "    return a / b\n\n"
        "def add(a: int, b: int) -> int:\n"
        "    return a + b\n",
    )
    repo.write(
        "tests/test_calc.py",
        "from src.calc import add, divide\n\n"
        "def test_divide():\n"
        "    assert divide(6, 2) == 3.0\n\n"
        "def test_add_regression():\n"
        "    assert add(2, 3) == 5\n",
    )
    repo.commit("fix: correct addition operator in add()")

    before_state = (
        repo.git("count-objects", "-v"),
        repo.git("for-each-ref"),
        repo.git("status", "--porcelain"),
    )
    report = regression.check_ci_regressions(repo.root, "main", "HEAD")
    after_state = (
        repo.git("count-objects", "-v"),
        repo.git("for-each-ref"),
        repo.git("status", "--porcelain"),
    )
    assert after_state == before_state, "regression check must never mutate repo objects, refs, or working tree"

    assert report.passed is True
    assert report.total_fix_commits == 1
    item = report.commits[0]
    assert item.status == "passed"
    assert item.failed_on_base is True
    assert item.passed_on_head is True
    assert any("test_add_regression" in nodeid for nodeid in item.fail_to_pass_tests)
    assert report.findings == ()


@needs_git
def test_tautological_assert_true_fails_fail_to_pass_because_it_passes_on_base(tmp_path: Path):
    repo = make_calc_repo(tmp_path)
    repo.write(
        "src/calc.py",
        "def divide(a: int, b: int) -> float:\n"
        "    return a / b\n\n"
        "def add(a: int, b: int) -> int:\n"
        "    return a + b\n",
    )
    repo.write(
        "tests/test_calc.py",
        "from src.calc import divide\n\n"
        "def test_divide():\n"
        "    assert divide(6, 2) == 3.0\n\n"
        "def test_trivial():\n"
        "    assert True\n",
    )
    repo.commit("fix: correct addition operator")

    report = regression.check_ci_regressions(repo.root, "main", "HEAD")
    assert report.passed is False
    assert report.total_fix_commits == 1
    item = report.commits[0]
    assert item.status == "failed"
    assert item.reason == "passed_on_base"
    assert item.failed_on_base is False
    assert item.passed_on_head is True
    assert len(report.findings) == 1
    assert report.findings[0].code == "passed_on_base"


@needs_git
def test_fix_commit_with_no_test_changes_flags_no_test_changes(tmp_path: Path):
    repo = make_calc_repo(tmp_path)
    repo.write(
        "src/calc.py",
        "def divide(a: int, b: int) -> float:\n"
        "    return a / b\n\n"
        "def add(a: int, b: int) -> int:\n"
        "    return a + b\n",
    )
    repo.commit("fix(calc): fix addition without adding a test")

    report = regression.check_ci_regressions(repo.root, "main", "HEAD")
    assert report.passed is False
    assert report.total_fix_commits == 1
    item = report.commits[0]
    assert item.status == "failed"
    assert item.reason == "no_test_changes"
    assert item.failed_on_base is False
    assert item.passed_on_head is False
    assert len(report.findings) == 1
    assert report.findings[0].code == "no_test_changes"


# ── 3. Exemptions require §2.2 human_gate approval ───────────────────────────


@needs_git
def test_aegis_no_test_trailer_without_human_gate_approval_does_not_exempt(tmp_path: Path):
    repo = make_calc_repo(tmp_path)
    repo.write("src/calc.py", "def add(a: int, b: int) -> int:\n    return a + b\n")
    repo.commit("fix: hotfix addition\n\nAegis-No-Test: pure refactor of internal expression")

    report = regression.check_ci_regressions(repo.root, "main", "HEAD")
    assert report.passed is False
    assert report.exempted_count == 0
    assert report.exemption_rate == 0.0
    item = report.commits[0]
    assert item.status == "failed"
    assert item.exempted is False
    assert item.no_test_reason == "pure refactor of internal expression"
    assert len(report.findings) == 1
    assert "pure refactor of internal expression" in report.findings[0].message


@needs_git
@needs_signing
def test_aegis_no_test_with_verified_human_gate_approval_exempts_and_reports_rate(
    tmp_path: Path, keys: Dict[str, Any]
):
    repo = make_calc_repo(tmp_path, signer_pub=keys["human_pub"])
    # Fix 1: has a real fail-to-pass test
    repo.write(
        "src/calc.py",
        "def divide(a: int, b: int) -> float:\n"
        "    return a / b\n\n"
        "def add(a: int, b: int) -> int:\n"
        "    return a + b\n",
    )
    repo.write(
        "tests/test_calc.py",
        "from src.calc import add\n\n"
        "def test_add():\n"
        "    assert add(2, 3) == 5\n",
    )
    repo.commit("fix: fix add")

    # Fix 2: no test, carries Aegis-No-Test explanation + signed human_gate approval
    repo.write("src/other.py", "def ping() -> str:\n    return 'pong'\n")
    repo.commit("fix: add fallback ping\n\nAegis-No-Test: trivial constant return")
    digest = human_gate.governance_tree_hash(repo.root, "HEAD")
    repo.commit(f"chore: approve exemption\n\nAegis-Approve: {digest}\n", sign_key=keys["human"], allow_empty=True)

    report = regression.check_ci_regressions(repo.root, "main", "HEAD")
    assert report.passed is True
    assert report.total_fix_commits == 2
    assert report.passed_count == 1
    assert report.exempted_count == 1
    assert report.exemption_rate == 0.5
    assert report.prune_box_exceeded is True
    assert report.commits[1].status == "exempted"
    assert report.commits[1].exempted is True
    assert report.commits[1].no_test_reason == "trivial constant return"
    assert report.findings == ()


# ── 4. Warning-tier rollout & `aegis check --ci` integration ─────────────────


@needs_git
def test_check_ci_starts_at_warning_tier_and_emits_warning_annotations_without_failing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    repo = make_calc_repo(tmp_path)
    repo.write("src/calc.py", "def add(a: int, b: int) -> int:\n    return a + b\n")
    repo.write("tests/test_calc.py", "def test_trivial():\n    assert True\n")
    repo.commit("fix: addition fix with tautological test")

    # JSON output includes regression report and exits 0 at warning tier
    rc_json, out_json, err_json = run_ci(repo, capsys, "--format", "json")
    assert rc_json == 0, err_json
    payload = json.loads(out_json)
    assert payload["status"] == "pass"
    assert "regression" in payload
    reg = payload["regression"]
    assert reg["tier"] == "warning"
    assert reg["passed"] is False
    assert reg["total_fix_commits"] == 1
    assert reg["findings"][0]["code"] == "passed_on_base"

    # GitHub output emits ::warning annotation and exits 0 at warning tier
    rc_gh, out_gh, _err_gh = run_ci(repo, capsys, "--format", "github")
    assert rc_gh == 0
    warnings = [line for line in out_gh.splitlines() if line.startswith("::warning")]
    assert len(warnings) == 1
    assert "passed_on_base" in warnings[0]


@needs_git
def test_check_ci_in_strict_or_gate_mode_fails_on_unapproved_regression(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    repo = make_calc_repo(tmp_path)
    repo.write("src/calc.py", "def add(a: int, b: int) -> int:\n    return a + b\n")
    repo.commit("fix: addition fix without test")

    rc, out, _err = run_ci(repo, capsys, "--strict", "--format", "json")
    assert rc == 1
    payload = json.loads(out)
    assert payload["status"] == "fail"
    assert payload["regression"]["tier"] == "gate"
    assert payload["regression"]["passed"] is False
    assert payload["regression"]["blocking"] is True

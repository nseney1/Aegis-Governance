"""The outcome engine never executes a project's own test or build commands (ADR 0005 AD-1, D1).

It used to run `make test`, `npm test`, `npm run build`, `cargo test` and friends with
shell=True whenever it ran (every MCP server shutdown and every session-close hook), so a
repo's own targets executed once per server process and their exit codes were credited to
rules. Outcomes now come only from explicit reports and CI.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from aegis_core.outcomes import (
    capture_build_outcome,
    capture_test_outcome,
    detect_test_runner,
    run_outcome_engine,
)
from aegis_core.yaml import dump_frontmatter

requires_make = pytest.mark.skipif(shutil.which("make") is None, reason="make not installed")
requires_npm = pytest.mark.skipif(shutil.which("npm") is None, reason="npm not installed")


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid",
         "-c", "commit.gpgsign=false", *args],
        cwd=repo, check=True, capture_output=True,
    )


def _write_rule(ws: Path, rule_id: str, target_paths: list[str]) -> Path:
    rules = ws / ".aegis" / "rules" / "traps"
    rules.mkdir(parents=True, exist_ok=True)
    path = rules / f"{rule_id}.md"
    fm = {"id": rule_id, "type": "trap", "target_paths": target_paths,
          "hypothesis": "h", "prediction": "p"}
    path.write_text(dump_frontmatter(fm, body="Body\n"), encoding="utf-8")
    return path


def _make_project(ws: Path) -> list[Path]:
    (ws / "Makefile").write_text("test:\n\ttouch MAKE_TEST_RAN\n", encoding="utf-8")
    return [ws / "MAKE_TEST_RAN"]


def _npm_project(ws: Path) -> list[Path]:
    scripts = {"test": "touch NPM_TEST_RAN", "build": "touch NPM_BUILD_RAN"}
    (ws / "package.json").write_text(
        json.dumps({"name": "p", "version": "0.0.0", "scripts": scripts}), encoding="utf-8"
    )
    return [ws / "NPM_TEST_RAN", ws / "NPM_BUILD_RAN"]


PROJECTS = [
    pytest.param(_make_project, marks=requires_make, id="makefile"),
    pytest.param(_npm_project, marks=requires_npm, id="npm"),
]


@pytest.mark.parametrize("make_project", PROJECTS)
def test_engine_runs_no_project_test_or_build_command(tmp_path: Path, make_project) -> None:
    _write_rule(tmp_path, "guard-src", ["src/*.py"])
    markers = make_project(tmp_path)

    assert run_outcome_engine(str(tmp_path)) == 0

    assert [m.name for m in markers if m.exists()] == []


@pytest.mark.parametrize("make_project", PROJECTS)
def test_capture_test_outcome_is_unverified_and_runs_nothing(tmp_path: Path, make_project) -> None:
    markers = make_project(tmp_path)

    outcome = capture_test_outcome(str(tmp_path))

    assert outcome["verified"] is False
    assert outcome["passed"] is None
    assert [m.name for m in markers if m.exists()] == []


@requires_npm
def test_capture_build_outcome_is_unverified_and_runs_nothing(tmp_path: Path) -> None:
    markers = _npm_project(tmp_path)

    outcome = capture_build_outcome(str(tmp_path))

    assert outcome["verified"] is False
    assert outcome["passed"] is None
    assert [m.name for m in markers if m.exists()] == []


@pytest.mark.parametrize(
    "config_file,content",
    [
        ("pyproject.toml", "[project]\nname = 'p'\n"),
        ("package.json", '{"name": "p"}'),
        ("Cargo.toml", "[package]\nname = 'p'\n"),
        ("Makefile", "test:\n\ttrue\n"),
    ],
)
def test_detect_test_runner_proposes_no_command(tmp_path: Path, config_file: str, content: str) -> None:
    (tmp_path / config_file).write_text(content, encoding="utf-8")

    assert detect_test_runner(str(tmp_path)) == (None, None)


def test_run_verify_refuses_to_execute(tmp_path: Path) -> None:
    from aegis_core.outcomes import _run_verify

    with pytest.raises(RuntimeError, match=r"implicit test/build execution was removed \(ADR 0005 AD-1\)"):
        _run_verify("touch RAN", cwd=str(tmp_path))

    assert not (tmp_path / "RAN").exists()


def test_engine_matches_rule_for_unstaged_modification(tmp_path: Path) -> None:
    """`git status --porcelain` lines start with a space for unstaged edits (" M path").

    The engine stripped that space before slicing off the 3-char status, so " M src/app.py"
    became "rc/app.py" and no rule ever matched an unstaged edit in a single-commit repo.
    """
    _write_rule(tmp_path, "guard-src", ["src/*.py"])
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("x = 1\n", encoding="utf-8")
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "init")
    (tmp_path / "src" / "app.py").write_text("x = 2\n", encoding="utf-8")

    assert run_outcome_engine(str(tmp_path)) == 0

    ledger = tmp_path / ".aegis" / "evidence" / "signals.jsonl"
    rows = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines() if line.strip()] \
        if ledger.is_file() else []
    assert "guard-src" in {r.get("cell") or r.get("rule_id") for r in rows}


def test_engine_matches_rule_for_renamed_destination(tmp_path: Path) -> None:
    """A staged rename is reported as "R  old -> new"; the rule on the destination must match."""
    _write_rule(tmp_path, "guard-lib", ["lib/*.py"])
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("x = 1\n", encoding="utf-8")
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "init")
    (tmp_path / "lib").mkdir()
    _git(tmp_path, "mv", "src/a.py", "lib/a.py")

    assert run_outcome_engine(str(tmp_path)) == 0

    ledger = tmp_path / ".aegis" / "evidence" / "signals.jsonl"
    rows = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines() if line.strip()] \
        if ledger.is_file() else []
    assert "guard-lib" in {r.get("cell") or r.get("rule_id") for r in rows}

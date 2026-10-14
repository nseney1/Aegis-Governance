"""Tests for aegis_core.outcomes.telemetry — Verifiable outcome reflection and ambient verification telemetry."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import pytest

from aegis_core.outcomes.telemetry import (
    VERIFY_TIMEOUT,
    _run_verify,
    detect_test_runner,
    capture_test_outcome,
    capture_build_outcome,
    capture_mcp_outcomes,
    record_verification_telemetry,
)
from aegis_core.yaml import dump_frontmatter


def test_run_verify_success_and_failure(tmp_path: Path):
    cwd = str(tmp_path)
    res_pass = _run_verify("echo 'hello'", cwd=cwd, timeout=5)
    assert res_pass["passed"] is True
    assert res_pass["exit_code"] == 0
    assert "hello" in res_pass["stdout_tail"]

    res_fail = _run_verify("exit 1", cwd=cwd, timeout=5)
    assert res_fail["passed"] is False
    assert res_fail["exit_code"] == 1


def test_run_verify_timeout_and_errors(tmp_path: Path, monkeypatch):
    cwd = str(tmp_path)
    # Timeout
    def fake_timeout(*a, **kw):
        raise subprocess.TimeoutExpired(cmd="sleep 10", timeout=1)

    monkeypatch.setattr(subprocess, "run", fake_timeout)
    res_to = _run_verify("sleep 10", cwd=cwd, timeout=1)
    assert res_to["error"] == "timeout"
    assert res_to["passed"] is None

    # Generic exception
    def fake_exc(*a, **kw):
        raise RuntimeError("exec failed")

    monkeypatch.setattr(subprocess, "run", fake_exc)
    res_err = _run_verify("echo hi", cwd=cwd)
    assert res_err["passed"] is None
    assert "exec failed" in res_err["error"]


def test_detect_test_runner(tmp_path: Path, monkeypatch):
    ws = str(tmp_path)
    # Empty dir
    cmd, name = detect_test_runner(ws)
    assert cmd is None

    # pyproject.toml with python3 -c import pytest check passing
    orig_run = subprocess.run
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, stdout="", stderr="") if isinstance(cmd, str) and "import pytest" in cmd else orig_run(cmd, **kw))

    (tmp_path / "pyproject.toml").write_text("[project]\nname='test'\n", encoding="utf-8")
    cmd, name = detect_test_runner(ws)
    assert name == "pytest"

    # remove pyproject.toml and add package.json
    (tmp_path / "pyproject.toml").unlink()
    (tmp_path / "package.json").write_text('{"name": "test"}', encoding="utf-8")
    cmd, name = detect_test_runner(ws)
    assert name == "npm test"

    # Makefile
    (tmp_path / "package.json").unlink()
    (tmp_path / "Makefile").write_text("test:\n\tpytest\n", encoding="utf-8")
    cmd, name = detect_test_runner(ws)
    assert name == "Makefile"


def test_detect_test_runner_skips_makefile_when_make_missing(tmp_path: Path, monkeypatch):
    """BUG-094: When make binary is not on PATH, Makefile test target is skipped."""
    import shutil
    monkeypatch.setattr(shutil, "which", lambda cmd: None if cmd == "make" else "/usr/bin/" + cmd)
    (tmp_path / "Makefile").write_text("test:\n\tpytest\n", encoding="utf-8")
    cmd, name = detect_test_runner(str(tmp_path))
    assert cmd is None
    assert name is None


def test_run_verify_command_not_found(monkeypatch):
    """BUG-094: Exit code 127 must be treated as passed=None (unverified), not passed=False."""
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **kw: subprocess.CompletedProcess(
            args="nonexistent_cmd", returncode=127, stdout="", stderr="sh: nonexistent_cmd: not found"
        ),
    )
    outcome = _run_verify("nonexistent_cmd", cwd=".")
    assert outcome["exit_code"] == 127
    assert outcome["passed"] is None
    assert "command not found" in outcome["error"]



def test_capture_test_outcome(tmp_path: Path, monkeypatch):
    ws = str(tmp_path)
    # No test runner
    assert capture_test_outcome(ws)["verified"] is False

    # Mock detect_test_runner
    monkeypatch.setattr("aegis_core.outcomes.telemetry.detect_test_runner", lambda w: ("true", "mocktest"))
    res_pass = capture_test_outcome(ws)
    assert res_pass["verified"] is True
    assert res_pass["passed"] is True

    monkeypatch.setattr("aegis_core.outcomes.telemetry.detect_test_runner", lambda w: ("false", "mocktest"))
    res_fail = capture_test_outcome(ws)
    assert res_fail["verified"] is True
    assert res_fail["passed"] is False

    # Subprocess error
    monkeypatch.setattr("aegis_core.outcomes.telemetry._run_verify", lambda c, cwd: {"passed": None, "error": "broken"})
    res_err = capture_test_outcome(ws)
    assert res_err["verified"] is False


def test_capture_build_outcome(tmp_path: Path, monkeypatch):
    ws = str(tmp_path)
    # No build system
    assert capture_build_outcome(ws)["verified"] is False

    # Package.json present
    (tmp_path / "package.json").write_text('{"scripts": {"build": "exit 0"}}', encoding="utf-8")
    monkeypatch.setattr("aegis_core.outcomes.telemetry._run_verify", lambda c, cwd: {"passed": True, "exit_code": 0})
    res = capture_build_outcome(ws)
    assert res["verified"] is True
    assert res["passed"] is True


def test_capture_mcp_outcomes(tmp_path: Path):
    ws = str(tmp_path)
    # File missing
    assert capture_mcp_outcomes(ws) == []

    evidence_dir = tmp_path / ".aegis" / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    signals_file = evidence_dir / "signals.jsonl"

    records = [
        "",
        "not json",
        json.dumps({}),  # no signal_type
        json.dumps({"signal_type": "tp", "cell_name": "cell-tp"}),
        json.dumps({"signal_type": "fp", "cell_id": "cell-fp"}),
        json.dumps({"signal_type": "trigger", "cell": "cell-trig"}),
        json.dumps({"signal": "custom_sig", "cell_name": "cell-custom"}),
    ]
    signals_file.write_text("\n".join(records) + "\n", encoding="utf-8")

    outcomes = capture_mcp_outcomes(ws)
    assert len(outcomes) == 4
    assert outcomes[0]["outcome"] == "success"
    assert outcomes[0]["cell_id"] == "cell-tp"
    assert outcomes[1]["outcome"] == "failure"
    assert outcomes[2]["outcome"] == "partial"
    assert outcomes[3]["outcome"] == "custom_sig"


def test_record_verification_telemetry(tmp_path: Path):
    ws = str(tmp_path)
    # Missing args
    assert record_verification_telemetry("", [], passed=True) is False
    assert record_verification_telemetry(ws, [], passed=True) is False

    # Missing cells_dir
    assert record_verification_telemetry(ws, ["src/foo.py"], passed=True) is False

    cells_dir = tmp_path / ".aegis" / "rules" / "vacuoles"
    cells_dir.mkdir(parents=True, exist_ok=True)
    cell_file = cells_dir / "test-cell.md"
    fm = {
        "id": "test-cell",
        "type": "vacuole",
        "target_paths": ["src/*.py"],
        "fitness": {"triggers": 0, "true_positives": 0, "false_positives": 0, "score": 0.5},
    }
    cell_file.write_text(f"---\n{dump_frontmatter(fm)}---\n\n# Body\n", encoding="utf-8")

    # Pass
    ok = record_verification_telemetry(
        ws,
        target_files=["src/foo.py"],
        passed=True,
        verdict="APPROVED",
        layer1_evidence=["dummy"],
        source="session",
    )
    assert ok is True

    # Fail
    ok_fail = record_verification_telemetry(
        ws,
        target_files=["src/foo.py"],
        passed=False,
        verdict="REJECTED",
        layer1_evidence=[],
        source="session",
    )
    assert ok_fail is True

    # Target files do not match
    assert record_verification_telemetry(ws, ["unmatched/file.txt"], passed=True) is False


def test_detect_test_runner_other_frameworks(tmp_path: Path, monkeypatch):
    ws = str(tmp_path)
    orig_run = subprocess.run
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, stdout="", stderr="") if isinstance(cmd, str) and ("import pytest" in cmd or "cargo" in cmd or "go version" in cmd) else orig_run(cmd, **kw))

    (tmp_path / "setup.cfg").write_text("[metadata]\nname=foo\n", encoding="utf-8")
    cmd, name = detect_test_runner(ws)
    assert name == "pytest"

    (tmp_path / "setup.cfg").unlink()
    (tmp_path / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    cmd, name = detect_test_runner(ws)
    assert name == "pytest"

    (tmp_path / "pytest.ini").unlink()
    (tmp_path / "Cargo.toml").write_text("[package]\nname='c'\n", encoding="utf-8")
    cmd, name = detect_test_runner(ws)
    assert name == "cargo test"

    (tmp_path / "Cargo.toml").unlink()
    (tmp_path / "go.mod").write_text("module test\n", encoding="utf-8")
    cmd, name = detect_test_runner(ws)
    assert name == "go test"


def test_capture_build_outcome_cargo_and_go(tmp_path: Path, monkeypatch):
    ws = str(tmp_path)
    monkeypatch.setattr("aegis_core.outcomes.telemetry._run_verify", lambda c, cwd: {"passed": True, "exit_code": 0})
    (tmp_path / "Cargo.toml").write_text("[package]\n", encoding="utf-8")
    res = capture_build_outcome(ws)
    assert res["verified"] is True
    assert res["command"] == "cargo"

    (tmp_path / "Cargo.toml").unlink()
    (tmp_path / "go.mod").write_text("module m\n", encoding="utf-8")
    res_go = capture_build_outcome(ws)
    assert res_go["verified"] is True
    assert res_go["command"] == "go"


def test_telemetry_edge_cases_and_error_branches(tmp_path: Path, monkeypatch):
    from aegis_core.outcomes.telemetry import (
        _run_verify,
        detect_test_runner,
        capture_mcp_outcomes,
        record_verification_telemetry,
    )
    ws = str(tmp_path)

    # 1. line 47: _run_verify FileNotFoundError -> None
    def mock_run_fnf(*args, **kwargs):
        raise FileNotFoundError("not found")
    monkeypatch.setattr(subprocess, "run", mock_run_fnf)
    assert _run_verify("nonexistent_binary", cwd=ws) is None
    monkeypatch.undo()

    # 2. line 78: Makefile read exception handled
    makefile = tmp_path / "Makefile"
    makefile.write_text("test:\n\t@echo ok\n", encoding="utf-8")
    real_open = open
    def mock_open_err(file, *args, **kwargs):
        if str(file).endswith("Makefile") or str(file).endswith("signals.jsonl"):
            raise OSError("read error")
        return real_open(file, *args, **kwargs)
    monkeypatch.setattr("builtins.open", mock_open_err)
    cmd, name = detect_test_runner(ws)
    assert cmd is None and name is None

    # 3. lines 166-167: capture_mcp_outcomes exception handled
    signals_file = tmp_path / ".aegis" / "evidence" / "signals.jsonl"
    signals_file.parent.mkdir(parents=True, exist_ok=True)
    signals_file.write_text("dummy\n", encoding="utf-8")
    assert capture_mcp_outcomes(ws) == []
    monkeypatch.undo()

    # 4. lines 259-261: record_verification_telemetry exception handled
    cells_dir = tmp_path / ".aegis" / "rules" / "vacuoles"
    cells_dir.mkdir(parents=True, exist_ok=True)
    cell_file = cells_dir / "test-cell.md"
    fm = {
        "id": "test-cell",
        "type": "vacuole",
        "target_paths": ["src/*.py"],
        "fitness": {"triggers": 0, "true_positives": 0, "false_positives": 0, "score": 0.5},
    }
    cell_file.write_text(f"---\n{dump_frontmatter(fm)}---\n\n# Body\n", encoding="utf-8")
    def mock_append_err(*args, **kwargs):
        raise RuntimeError("db error")
    monkeypatch.setattr("aegis_core.telemetry.append_signals", mock_append_err)
    assert record_verification_telemetry(ws, ["src/foo.py"], passed=True) is False




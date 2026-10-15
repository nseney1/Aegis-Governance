"""Tests for aegis_core.outcomes.telemetry — MCP-reported outcomes and ambient verification telemetry.

Implicit test/build execution is gone (ADR 0005 AD-1); its behavioral tests live in
test_outcomes_no_implicit_execution.py.
"""
from __future__ import annotations

import json
from pathlib import Path

from aegis_core.outcomes.telemetry import (
    detect_test_runner,
    capture_mcp_outcomes,
    record_verification_telemetry,
)
from aegis_core.yaml import dump_frontmatter


def test_detect_test_runner_skips_makefile_when_make_missing(tmp_path: Path, monkeypatch):
    """BUG-094: a shutdown reflector ran `make test` where make was missing and scored rules -1.0.

    Nothing runs a project's test target any more, with or without make on PATH.
    """
    import shutil
    monkeypatch.setattr(shutil, "which", lambda cmd: None if cmd == "make" else "/usr/bin/" + cmd)
    (tmp_path / "Makefile").write_text("test:\n\tpytest\n", encoding="utf-8")
    cmd, name = detect_test_runner(str(tmp_path))
    assert cmd is None
    assert name is None


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


def test_telemetry_edge_cases_and_error_branches(tmp_path: Path, monkeypatch):
    ws = str(tmp_path)

    # 1. capture_mcp_outcomes: an unreadable signals file is handled
    real_open = open
    def mock_open_err(file, *args, **kwargs):
        if str(file).endswith("signals.jsonl"):
            raise OSError("read error")
        return real_open(file, *args, **kwargs)
    monkeypatch.setattr("builtins.open", mock_open_err)
    signals_file = tmp_path / ".aegis" / "evidence" / "signals.jsonl"
    signals_file.parent.mkdir(parents=True, exist_ok=True)
    signals_file.write_text("dummy\n", encoding="utf-8")
    assert capture_mcp_outcomes(ws) == []
    monkeypatch.undo()

    # 2. record_verification_telemetry: a failing ledger append is handled
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

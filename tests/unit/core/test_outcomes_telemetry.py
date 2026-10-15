"""Tests for aegis_core.outcomes.telemetry — ambient verification telemetry in the ledger."""
from __future__ import annotations

from pathlib import Path

from aegis_core.outcomes.telemetry import record_verification_telemetry
from aegis_core.yaml import dump_frontmatter


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

    # record_verification_telemetry: a failing ledger append is handled
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
    monkeypatch.setattr("aegis_core.telemetry_engine.ledger.append_signals", mock_append_err)
    assert record_verification_telemetry(ws, ["src/foo.py"], passed=True) is False

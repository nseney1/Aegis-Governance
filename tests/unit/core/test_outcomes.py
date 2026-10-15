"""Tests for aegis_core.outcomes — Verifiable outcome reflection and credit assignment."""
from __future__ import annotations

import json
from pathlib import Path

from aegis_core.outcomes import (
    compute_credit_weights,
    compute_fitness_signals,
    detect_test_runner,
    to_fraction,
    update_cell_fitness,
    capture_mcp_outcomes,
    _read_insight_cursor,
    commit_insight_cursor,
    read_human_insight_signals,
    update_fitness,
)
from aegis_core.yaml import dump_frontmatter, parse_frontmatter


def test_detect_test_runner_empty(tmp_path: Path) -> None:
    cmd, name = detect_test_runner(str(tmp_path))
    assert cmd is None
    assert name is None


def test_to_fraction_deterministic() -> None:
    assert to_fraction(0.5) == "1/2"
    assert to_fraction("1/3") == "1/3"
    assert to_fraction(1.0) == "1/1"
    assert to_fraction(0.0) == "0/1"
    assert to_fraction(-0.5) == "0/1"
    assert to_fraction(1.5) == "1/1"
    assert to_fraction("invalid") == "0/1"


def test_compute_credit_weights_narrowing() -> None:
    cells = [
        {"_name": "cell-a", "target_paths": ["src/a.py"]},
        {"_name": "cell-b", "target_paths": ["src/b.py"]},
        {"_name": "cell-shared", "target_paths": ["src/*.py"]},
    ]
    # src/a.py matches cell-a and cell-shared (split 0.5 each)
    # src/b.py matches cell-b and cell-shared (split 0.5 each)
    weights = compute_credit_weights(cells, ["src/a.py", "src/b.py"])
    assert weights["cell-a"] == 0.5
    assert weights["cell-b"] == 0.5
    assert weights["cell-shared"] == 1.0


def test_compute_credit_weights_empty() -> None:
    cells = [{"_name": "cell-a"}]
    assert compute_credit_weights(cells, []) == {"cell-a": 1.0}


def test_compute_fitness_signals_test_pass() -> None:
    cells = [{"_name": "cell-1", "_path": "/path/cell-1.md", "target_paths": ["src/*.py"]}]
    outcomes = {
        "tests": {"verified": True, "passed": True, "framework": "pytest"},
        "build": {"verified": False},
        "git": {"reverts": 0, "rework_files": []},
        "mcp": [],
    }
    signals = compute_fitness_signals(cells, outcomes, ["src/main.py"])
    assert len(signals) == 1
    assert signals[0]["cell"] == "cell-1"
    assert signals[0]["signal"] == 1.0
    assert signals[0]["verified"] is True
    assert "tests passed (pytest)" in signals[0]["reasons"][0]


def test_compute_fitness_signals_overconfidence_penalty() -> None:
    cells = [{"_name": "cell-1", "_path": "/path/cell-1.md", "target_paths": ["src/*.py"]}]
    outcomes = {
        "tests": {"verified": True, "passed": False, "framework": "pytest"},
        "build": {"verified": False},
        "git": {"reverts": 0, "rework_files": []},
        "mcp": [{"cell_id": "cell-1", "outcome": "success"}],
    }
    signals = compute_fitness_signals(cells, outcomes, ["src/main.py"])
    assert len(signals) == 1
    # -1.0 for test failure, -2.0 for overconfidence penalty = clamped to -2.0
    assert signals[0]["signal"] == -2.0
    assert any("overconfidence penalty" in r for r in signals[0]["reasons"])


def test_update_cell_fitness_positive_and_negative(tmp_path: Path) -> None:
    cell_file = tmp_path / "cell-1.md"
    initial_fm = {
        "id": "cell-1",
        "type": "vacuole",
        "fitness": {"score": 0.5, "triggers": 1, "true_positives": 1, "false_positives": 0},
    }
    cell_file.write_text(f"---\n{dump_frontmatter(initial_fm).strip()}\n---\n\nBody", encoding="utf-8")

    # Positive signal with credit weight 0.5
    signals_pos = [{
        "_path": str(cell_file),
        "signal": 1.0,
        "credit_weight": 0.5,
    }]
    update_cell_fitness(str(tmp_path), signals_pos)

    fm_after_pos = parse_frontmatter(cell_file.read_text(encoding="utf-8"))
    assert fm_after_pos["fitness"]["triggers"] == 2
    assert fm_after_pos["fitness"]["true_positives"] == 1.5

    # Negative signal with credit weight 0.25
    signals_neg = [{
        "_path": str(cell_file),
        "signal": -1.0,
        "credit_weight": 0.25,
    }]
    update_cell_fitness(str(tmp_path), signals_neg)

    fm_after_neg = parse_frontmatter(cell_file.read_text(encoding="utf-8"))
    assert fm_after_neg["fitness"]["triggers"] == 3
    assert fm_after_neg["fitness"]["false_positives"] == 0.25


def test_insight_cursor_roundtrip(tmp_path: Path) -> None:
    ws = str(tmp_path)
    assert _read_insight_cursor(ws) == 0
    assert commit_insight_cursor(ws, 128) is True
    assert _read_insight_cursor(ws) == 128


def test_capture_mcp_outcomes(tmp_path: Path) -> None:
    ws = str(tmp_path)
    evidence_dir = tmp_path / ".aegis" / "evidence"
    evidence_dir.mkdir(parents=True)
    signals_file = evidence_dir / "signals.jsonl"
    signals_file.write_text(
        json.dumps({"signal_type": "tp", "cell_name": "cell-x"}) + "\n" +
        json.dumps({"signal_type": "fp", "cell_name": "cell-y"}) + "\n",
        encoding="utf-8"
    )
    records = capture_mcp_outcomes(ws)
    assert len(records) == 2
    assert records[0]["outcome"] == "success"
    assert records[0]["cell_id"] == "cell-x"
    assert records[1]["outcome"] == "failure"
    assert records[1]["cell_id"] == "cell-y"


def test_read_human_insight_signals(tmp_path: Path) -> None:
    ws = str(tmp_path)
    soma_dir = tmp_path / ".aegis"
    soma_dir.mkdir()
    insights_file = soma_dir / "human_insights.jsonl"
    insights_file.write_text(
        json.dumps({"was_covered": False, "insight": "Missing rate limit"}) + "\n",
        encoding="utf-8"
    )
    signals, new_offset = read_human_insight_signals(ws)
    assert len(signals) == 1
    assert signals[0]["signal_type"] == "blind_spot"
    assert new_offset > 0


def test_update_fitness_transcript(tmp_path: Path) -> None:
    evidence_dir = tmp_path / ".aegis" / "evidence"
    evidence_dir.mkdir(parents=True)
    triggered = [{"cell_id": "cell-transcript", "matched_files": ["foo.py"]}]
    events = update_fitness(triggered, "trans-1", evidence_dir)
    assert len(events) == 1
    assert events[0]["cell"] == "cell-transcript"
    assert events[0]["signal"] == "trigger"


def test_frontmatter_consolidation_handles_embedded_dashes(tmp_path: Path) -> None:
    """A quoted '---' inside a scalar does not end the frontmatter block."""
    from aegis_core.yaml import _get_body, parse_frontmatter

    content = '---\nid: rule-embedded-dashes\ntype: invariant\nhypothesis: "Avoid --- inline delimiters"\n---\nActual body text.\n'
    meta = parse_frontmatter(content)
    assert meta["id"] == "rule-embedded-dashes"
    assert meta["hypothesis"] == "Avoid --- inline delimiters"
    assert _get_body(content).strip() == "Actual body text."

"""Behavioral tests for aegis_core.sweep_session."""
import json
from pathlib import Path
from aegis_core.sweep_session import scan_transcript, to_session_metrics


def test_scan_empty_transcript(tmp_path):
    empty_file = tmp_path / "transcript.jsonl"
    empty_file.write_text("\n\n   \n", encoding="utf-8")
    assert scan_transcript(str(empty_file)) is None


def test_scan_transcript_clean(tmp_path):
    f = tmp_path / "transcript.jsonl"
    lines = [
        json.dumps({"content": "Analyzing repository structure"}),
        json.dumps({"content": "Running test suite successfully"}),
        json.dumps({"content": "Implementing requested feature"}),
    ]
    f.write_text("\n".join(lines), encoding="utf-8")
    result = scan_transcript(str(f))
    assert result is not None
    assert result["total_steps"] == 3
    assert result["estimated_waste_rate"] == 0.0
    assert result["estimated_wasted_steps"] == 0
    assert result["estimated_productive_steps"] == 3


def test_scan_transcript_detects_waste_signals(tmp_path):
    f = tmp_path / "transcript.jsonl"
    lines = [
        json.dumps({"content": "Running pip install package"}),
        json.dumps({"content": "Running git add -A"}),
        json.dumps({"content": "Using ast.parse to check syntax"}),
        json.dumps({"content": "Normal coding task"}),
    ]
    f.write_text("\n".join(lines), encoding="utf-8")
    result = scan_transcript(str(f))
    assert result is not None
    assert result["total_steps"] == 4
    assert result["waste_signals"]["pip install"] == 1
    assert result["waste_signals"]["git add -A"] == 1
    assert result["waste_signals"]["ast.parse"] == 1
    patterns = {p["pattern"] for p in result["top_patterns"]}
    assert "VIRTUALENV_DRIFT" in patterns
    assert "DIRTY_VCS_STAGING" in patterns
    assert "SYNTAX_ONLY_VERIFICATION" in patterns


def test_scan_transcript_rework_heuristic(tmp_path):
    f = tmp_path / "transcript.jsonl"
    lines = [
        json.dumps({"content": "ModuleNotFoundError: No module named 'xyz'"}),
        json.dumps({"content": "Traceback: Error in execution"}),
        json.dumps({"content": "SyntaxError: unexpected EOF"}),
        json.dumps({"content": "Traceback: again"}),
    ]
    f.write_text("\n".join(lines), encoding="utf-8")
    result = scan_transcript(str(f))
    assert result is not None
    assert result["total_steps"] == 4
    # High error rate triggers rework loop heuristic
    patterns = {p["pattern"] for p in result["top_patterns"]}
    assert "REWORK_LOOP" in patterns


def test_to_session_metrics():
    scan_result = {
        "total_steps": 10,
        "estimated_wasted_steps": 2,
        "estimated_productive_steps": 8,
        "estimated_waste_rate": 0.2,
        "top_patterns": [{"pattern": "VIRTUALENV_DRIFT", "count": 2}],
        "scanned_at": "2026-10-05T00:00:00",
    }
    metrics = to_session_metrics("sess-12345678", scan_result)
    assert metrics["session_id"] == "sess-12345678"
    assert metrics["total_steps"] == 10
    assert metrics["wasted_steps"] == 2
    assert metrics["productive_steps"] == 8
    assert metrics["waste_rate"] == 0.2
    assert metrics["patterns"] == {"VIRTUALENV_DRIFT": 2}

"""Tests for aegis_core.outcomes.insights — Developer insight reading and atomic cursor persistence."""
from __future__ import annotations

import json
import os
from pathlib import Path
import pytest

from aegis_core.outcomes.insights import (
    _insight_cursor_path,
    _read_insight_cursor,
    commit_insight_cursor,
    capture_human_insight_signals,
    read_human_insight_signals,
)
from aegis_core.yaml import dump_frontmatter


def test_insight_cursor_path(tmp_path: Path):
    path = _insight_cursor_path(str(tmp_path))
    assert path.endswith("insight_cursor")


def test_read_insight_cursor_missing_and_invalid(tmp_path: Path):
    ws = str(tmp_path)
    # Missing file
    assert _read_insight_cursor(ws) == 0

    cursor_file = tmp_path / ".aegis" / "insight_cursor"
    cursor_file.parent.mkdir(parents=True, exist_ok=True)

    # Invalid string
    cursor_file.write_text("invalid\n", encoding="utf-8")
    assert _read_insight_cursor(ws) == 0

    # Negative integer
    cursor_file.write_text("-10\n", encoding="utf-8")
    assert _read_insight_cursor(ws) == 0

    # Valid integer
    cursor_file.write_text("42\n", encoding="utf-8")
    assert _read_insight_cursor(ws) == 42


def test_commit_insight_cursor_atomic(tmp_path: Path):
    ws = str(tmp_path)
    # offset=None should return True
    assert commit_insight_cursor(ws, None) is True

    # Initial commit
    assert commit_insight_cursor(ws, 100) is True
    assert _read_insight_cursor(ws) == 100

    # Redundant commit with same offset
    assert commit_insight_cursor(ws, 100) is True

    # Advance cursor
    assert commit_insight_cursor(ws, 250) is True
    assert _read_insight_cursor(ws) == 250


def test_commit_insight_cursor_failure_cleanup(tmp_path: Path, monkeypatch):
    ws = str(tmp_path)
    # Simulate os.replace failure
    def fake_replace(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", fake_replace)
    assert commit_insight_cursor(ws, 500) is False


def test_read_and_capture_human_insight_signals_missing_file(tmp_path: Path):
    ws = str(tmp_path)
    signals, offset = read_human_insight_signals(ws)
    assert signals == []
    assert offset == 0

    captured = capture_human_insight_signals(ws)
    assert captured == []


def test_capture_human_insight_signals_advances_cursor(tmp_path: Path):
    ws = str(tmp_path)
    insights_file = tmp_path / ".aegis" / "human_insights.jsonl"
    insights_file.parent.mkdir(parents=True, exist_ok=True)
    insights_file.write_text(json.dumps({"was_covered": False, "insight": "adv"}) + "\n", encoding="utf-8")

    assert _read_insight_cursor(ws) == 0
    signals = capture_human_insight_signals(ws)
    assert len(signals) == 1
    assert _read_insight_cursor(ws) > 0


def test_read_human_insight_signals_cursor_reset_if_truncated(tmp_path: Path):
    ws = str(tmp_path)
    insights_file = tmp_path / ".aegis" / "human_insights.jsonl"
    insights_file.parent.mkdir(parents=True, exist_ok=True)
    insights_file.write_text(json.dumps({"was_covered": False, "insight": "test"}) + "\n", encoding="utf-8")

    cursor_file = tmp_path / ".aegis" / "insight_cursor"
    cursor_file.write_text("99999\n", encoding="utf-8")  # cursor > file size

    signals, offset = read_human_insight_signals(ws)
    assert len(signals) == 1
    assert offset > 0


def test_read_human_insight_signals_custom_weight_and_cells(tmp_path: Path):
    ws = str(tmp_path)
    soma_dir = tmp_path / ".aegis"
    cells_dir = soma_dir / "rules" / "vacuoles"
    cells_dir.mkdir(parents=True, exist_ok=True)

    # Cell file
    cell_file = cells_dir / "cell-auth.md"
    cell_file.write_text(dump_frontmatter({"id": "cell-auth"}), encoding="utf-8")

    # Config with custom insight_signal_weight
    config_file = soma_dir / "config.yaml"
    config_file.write_text("insight_signal_weight: 0.8\n", encoding="utf-8")

    # Insights file with both covered and blind spot records, plus empty/invalid lines
    insights_file = soma_dir / "human_insights.jsonl"
    lines = [
        "",  # empty line
        "not json",  # invalid json
        json.dumps("string not dict"),  # non-dict
        json.dumps({
            "was_covered": True,
            "covering_cells": ["cell-auth", "nonexistent-cell"],
            "insight": "Auth bypass flaw",
            "context_files": ["auth.py"],
        }),
        json.dumps({
            "was_covered": False,
            "insight": "Uncovered vulnerability",
            "context_files": ["api.py"],
        }),
    ]
    insights_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

    signals, offset = read_human_insight_signals(ws)
    assert len(signals) == 2  # 1 for cell-auth, 1 for blind spot
    assert signals[0]["cell"] == "cell-auth"
    assert signals[0]["weight"] == 0.8
    assert signals[1]["signal_type"] == "blind_spot"
    assert signals[1]["weight"] == 0.8

    # Commit cursor then check capture_human_insight_signals
    assert commit_insight_cursor(ws, offset) is True
    captured = capture_human_insight_signals(ws)
    assert captured == []  # Cursor was advanced to end of file, no new signals


def test_read_human_insight_signals_no_newline(tmp_path: Path):
    ws = str(tmp_path)
    insights_file = tmp_path / ".aegis" / "human_insights.jsonl"
    insights_file.parent.mkdir(parents=True, exist_ok=True)
    # Write line without newline
    insights_file.write_text(json.dumps({"was_covered": False, "insight": "partial"}))

    signals, offset = read_human_insight_signals(ws)
    assert signals == []
    assert offset == 0


def test_read_human_insight_signals_config_error(tmp_path: Path):
    ws = str(tmp_path)
    soma_dir = tmp_path / ".aegis"
    soma_dir.mkdir(parents=True, exist_ok=True)
    config_file = soma_dir / "config.yaml"
    config_file.write_text("invalid: [unclosed\n", encoding="utf-8")
    insights_file = soma_dir / "human_insights.jsonl"
    insights_file.write_text(json.dumps({"was_covered": False, "insight": "ok"}) + "\n", encoding="utf-8")

    signals, offset = read_human_insight_signals(ws)
    assert len(signals) == 1
    assert signals[0]["weight"] == 0.5


def test_read_human_insight_signals_read_error(tmp_path: Path, monkeypatch):
    ws = str(tmp_path)
    soma_dir = tmp_path / ".aegis"
    soma_dir.mkdir(parents=True, exist_ok=True)
    insights_file = soma_dir / "human_insights.jsonl"
    insights_file.write_text("dummy\n", encoding="utf-8")

    orig_open = open
    def fake_open(p, *a, **kw):
        if str(p).endswith("human_insights.jsonl") and a and "b" in a[0]:
            raise OSError("permission denied")
        return orig_open(p, *a, **kw)

    monkeypatch.setattr("builtins.open", fake_open)
    signals, offset = read_human_insight_signals(ws)
    assert signals == []


def test_commit_insight_cursor_unlink_error(tmp_path: Path, monkeypatch):
    ws = str(tmp_path)
    monkeypatch.setattr(os, "replace", lambda s, d: (_ for _ in ()).throw(OSError("replace fail")))
    monkeypatch.setattr(os, "unlink", lambda p: (_ for _ in ()).throw(OSError("unlink fail")))
    assert commit_insight_cursor(ws, 123) is False


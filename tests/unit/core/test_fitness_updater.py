"""TDD tests for enzymes/fitness_updater.py (Phase C).

Written BEFORE the implementation — these tests define the contract.
All tests should FAIL initially (RED phase), then pass after implementation (GREEN).
"""

import json
import os
import tempfile
from pathlib import Path
from datetime import datetime, timezone

import pytest
from aegis_core.yaml import dump_frontmatter

# Will fail until implementation exists — that's the TDD red phase
from aegis_core.telemetry import (
    detect_platform,
    extract_modified_files,
    match_cells,
    resolve_transcript_id,
    update_fitness,
)


# ── Helpers ──


def _make_transcript(tmp_path, tool_calls):
    """Create a minimal transcript.jsonl with write tool calls."""
    transcript = tmp_path / "transcript.jsonl"
    lines = []
    for i, tc in enumerate(tool_calls):
        step = {
            "step_index": i,
            "source": "MODEL",
            "type": "PLANNER_RESPONSE",
            "status": "DONE",
            "tool_calls": [tc],
        }
        lines.append(json.dumps(step))
    transcript.write_text("\n".join(lines) + "\n")
    return transcript


def _make_cell(cells_dir, name, target_paths, subdir="vacuoles"):
    """Create a minimal cell markdown file with frontmatter."""
    cell_dir = cells_dir / subdir
    cell_dir.mkdir(parents=True, exist_ok=True)
    cell_file = cell_dir / f"{name}.md"
    fm = {
        "id": name,
        "domain": "correctness",
        "type": "vacuole",
        "target_paths": target_paths,
    }
    content = dump_frontmatter(fm, body="Test cell.\n")
    cell_file.write_text(content)
    return cell_file


def _make_evidence_dir(tmp_path):
    """Create the evidence directory structure."""
    evidence = tmp_path / ".soma" / "evidence"
    evidence.mkdir(parents=True, exist_ok=True)
    return evidence


# ── extract_modified_files ──


class TestExtractModifiedFiles:
    """Tests for extracting file paths from transcript tool calls."""

    def test_extracts_target_file_from_write(self, tmp_path):
        """write_to_file and replace_file_content TargetFile args are extracted."""
        transcript = _make_transcript(tmp_path, [
            {"name": "write_to_file", "arguments": {"TargetFile": "/home/user/soma/enzymes/foo.py"}},
            {"name": "replace_file_content", "arguments": {"TargetFile": "/home/user/soma/tests/test_bar.py"}},
        ])
        result = extract_modified_files(transcript)
        assert "/home/user/soma/enzymes/foo.py" in result
        assert "/home/user/soma/tests/test_bar.py" in result

    def test_extracts_multi_replace(self, tmp_path):
        """multi_replace_file_content TargetFile args are extracted."""
        transcript = _make_transcript(tmp_path, [
            {"name": "multi_replace_file_content", "arguments": {"TargetFile": "/home/user/soma/genome/rule.md"}},
        ])
        result = extract_modified_files(transcript)
        assert "/home/user/soma/genome/rule.md" in result

    def test_ignores_read_only_tools(self, tmp_path):
        """view_file, grep_search etc. should NOT be counted as modifications."""
        transcript = _make_transcript(tmp_path, [
            {"name": "view_file", "arguments": {"AbsolutePath": "/home/user/soma/enzymes/foo.py"}},
            {"name": "grep_search", "arguments": {"SearchPath": "/home/user/soma/"}},
        ])
        result = extract_modified_files(transcript)
        assert len(result) == 0

    def test_empty_transcript(self, tmp_path):
        """Empty transcript returns empty set."""
        transcript = tmp_path / "transcript.jsonl"
        transcript.write_text("")
        result = extract_modified_files(transcript)
        assert result == set()

    def test_malformed_line_skipped(self, tmp_path):
        """Malformed JSON lines are skipped, not crash."""
        transcript = tmp_path / "transcript.jsonl"
        transcript.write_text(
            '{"this is": "valid json but no tool_calls"}\n'
            'this is not valid json at all\n'
            '{"tool_calls": [{"name": "write_to_file", "arguments": {"TargetFile": "/a/b.py"}}]}\n'
        )
        result = extract_modified_files(transcript)
        assert "/a/b.py" in result
        assert len(result) == 1

    def test_nonexistent_transcript(self, tmp_path):
        """Nonexistent transcript path returns empty set, no crash."""
        result = extract_modified_files(tmp_path / "nonexistent.jsonl")
        assert result == set()

    def test_deduplicates_paths(self, tmp_path):
        """Same file modified multiple times appears once."""
        transcript = _make_transcript(tmp_path, [
            {"name": "write_to_file", "arguments": {"TargetFile": "/a/b.py"}},
            {"name": "replace_file_content", "arguments": {"TargetFile": "/a/b.py"}},
            {"name": "multi_replace_file_content", "arguments": {"TargetFile": "/a/b.py"}},
        ])
        result = extract_modified_files(transcript)
        assert result == {"/a/b.py"}


# ── match_cells ──


class TestMatchCells:
    """Tests for matching modified files against cell target_paths."""

    def test_glob_match(self, tmp_path):
        """Cell with target_paths: ['enzymes/*.py'] matches enzymes/foo.py."""
        cells_dir = tmp_path / "cells"
        _make_cell(cells_dir, "trap-test", ["enzymes/*.py"])
        matches = match_cells(
            {"/home/user/soma/enzymes/foo.py"},
            cells_dir,
            repo_root="/home/user/soma"
        )
        assert len(matches) == 1
        assert matches[0]["cell_id"] == "trap-test"

    def test_no_match(self, tmp_path):
        """Cell monitoring 'genome/*.md' does not match enzymes/foo.py."""
        cells_dir = tmp_path / "cells"
        _make_cell(cells_dir, "trap-genome", ["genome/*.md"])
        matches = match_cells(
            {"/home/user/soma/enzymes/foo.py"},
            cells_dir,
            repo_root="/home/user/soma"
        )
        assert len(matches) == 0

    def test_multiple_cells_match(self, tmp_path):
        """Multiple cells can match the same modified file."""
        cells_dir = tmp_path / "cells"
        _make_cell(cells_dir, "trap-a", ["enzymes/*.py"])
        _make_cell(cells_dir, "trap-b", ["enzymes/*.py"], subdir="walls")
        matches = match_cells(
            {"/home/user/soma/enzymes/foo.py"},
            cells_dir,
            repo_root="/home/user/soma"
        )
        assert len(matches) == 2
        ids = {m["cell_id"] for m in matches}
        assert ids == {"trap-a", "trap-b"}

    def test_cell_with_no_target_paths(self, tmp_path):
        """Cell with empty target_paths matches nothing."""
        cells_dir = tmp_path / "cells"
        _make_cell(cells_dir, "trap-empty", [])
        matches = match_cells(
            {"/home/user/soma/enzymes/foo.py"},
            cells_dir,
            repo_root="/home/user/soma"
        )
        assert len(matches) == 0

    def test_empty_modified_files(self, tmp_path):
        """No modified files triggers zero cells."""
        cells_dir = tmp_path / "cells"
        _make_cell(cells_dir, "trap-test", ["enzymes/*.py"])
        matches = match_cells(set(), cells_dir, repo_root="/home/user/soma")
        assert len(matches) == 0

    def test_nonexistent_cells_dir(self, tmp_path):
        """Nonexistent cells directory returns empty list."""
        matches = match_cells(
            {"/home/user/soma/enzymes/foo.py"},
            tmp_path / "nonexistent",
            repo_root="/home/user/soma"
        )
        assert len(matches) == 0

    def test_matched_files_recorded(self, tmp_path):
        """Each match record includes the specific files that triggered it."""
        cells_dir = tmp_path / "cells"
        _make_cell(cells_dir, "trap-test", ["enzymes/*.py"])
        matches = match_cells(
            {"/home/user/soma/enzymes/foo.py", "/home/user/soma/enzymes/bar.py"},
            cells_dir,
            repo_root="/home/user/soma"
        )
        assert len(matches) == 1
        assert set(matches[0]["matched_files"]) == {"enzymes/foo.py", "enzymes/bar.py"}


# ── update_fitness ──


class TestUpdateFitness:
    """Tests for writing fitness records via unified telemetry."""

    def test_appends_to_signals_jsonl(self, tmp_path):
        """Triggered cells are written as JSONL entries to signals.jsonl."""
        evidence = _make_evidence_dir(tmp_path)
        triggered = [
            {"cell_id": "trap-a", "cell_path": "cells/trap-a.md", "matched_files": ["enzymes/foo.py"]},
        ]
        update_fitness(triggered, "session-001", evidence)
        signals_file = evidence / "signals.jsonl"
        assert signals_file.exists()
        records = [json.loads(l) for l in signals_file.read_text().splitlines()]
        assert len(records) == 1
        assert records[0]["cell"] == "trap-a"
        assert records[0]["signal"] == "trigger"
        assert records[0]["source"] == "session"
        assert "timestamp" in records[0]

    def test_idempotent_on_same_session(self, tmp_path):
        """Running twice with the same transcript_id does not duplicate entries."""
        evidence = _make_evidence_dir(tmp_path)
        triggered = [
            {"cell_id": "trap-a", "cell_path": "cells/trap-a.md", "matched_files": ["enzymes/foo.py"]},
        ]
        update_fitness(triggered, "session-001", evidence)
        update_fitness(triggered, "session-001", evidence)
        signals_file = evidence / "signals.jsonl"
        records = [json.loads(l) for l in signals_file.read_text().splitlines()]
        assert len(records) == 1  # Not 2

    def test_different_sessions_append(self, tmp_path):
        """Different sessions append new records."""
        evidence = _make_evidence_dir(tmp_path)
        triggered = [
            {"cell_id": "trap-a", "cell_path": "cells/trap-a.md", "matched_files": ["enzymes/foo.py"]},
        ]
        update_fitness(triggered, "session-001", evidence)
        update_fitness(triggered, "session-002", evidence)
        signals_file = evidence / "signals.jsonl"
        records = [json.loads(l) for l in signals_file.read_text().splitlines()]
        assert len(records) == 2

    def test_sessions_processed_updated(self, tmp_path):
        """Idempotency tracking uses signals.jsonl."""
        evidence = _make_evidence_dir(tmp_path)
        triggered = [
            {"cell_id": "trap-a", "cell_path": "cells/trap-a.md", "matched_files": ["enzymes/foo.py"]},
        ]
        update_fitness(triggered, "session-001", evidence)
        ledger = evidence / "signals.jsonl"
        assert ledger.exists()
        records = [json.loads(l) for l in ledger.read_text().splitlines()]
        assert records[0]["metadata"]["transcript_id"] == "session-001"


    def test_empty_triggered_list(self, tmp_path):
        """Zero triggered cells is handled correctly without failing."""
        evidence = _make_evidence_dir(tmp_path)
        update_fitness([], "session-001", evidence)
        ledger = evidence / "signals.jsonl"
        assert not ledger.exists() # Should not create the file if nothing triggered
        # No signals.jsonl entries
        signals_file = evidence / "signals.jsonl"
        if signals_file.exists():
            assert signals_file.read_text().strip() == ""

    def test_first_run_creates_files(self, tmp_path):
        """First run on empty evidence dir creates both JSONL files."""
        evidence = _make_evidence_dir(tmp_path)
        triggered = [
            {"cell_id": "trap-a", "cell_path": "cells/trap-a.md", "matched_files": ["a.py"]},
        ]
        update_fitness(triggered, "session-001", evidence)
        assert (evidence / "signals.jsonl").exists()


# ── Platform detection & transcript ID ──


class TestDetectPlatform:
    """Tests for auto-detecting platform from transcript content."""

    def test_detects_antigravity_from_write_to_file(self, tmp_path):
        """Transcript with write_to_file calls detects as antigravity."""
        transcript = _make_transcript(tmp_path, [
            {"name": "write_to_file", "arguments": {"TargetFile": "/a/b.py"}},
        ])
        assert detect_platform(transcript) == "antigravity"

    def test_detects_antigravity_from_replace_file_content(self, tmp_path):
        """Transcript with replace_file_content detects as antigravity."""
        transcript = _make_transcript(tmp_path, [
            {"name": "replace_file_content", "arguments": {"TargetFile": "/a/b.py"}},
        ])
        assert detect_platform(transcript) == "antigravity"

    def test_defaults_on_unknown_tools(self, tmp_path):
        """Transcript with no known write tools returns default."""
        transcript = _make_transcript(tmp_path, [
            {"name": "some_other_tool", "arguments": {"path": "/a/b.py"}},
        ])
        assert detect_platform(transcript) == "antigravity"  # default

    def test_defaults_on_nonexistent_file(self, tmp_path):
        """Nonexistent transcript returns default."""
        assert detect_platform(tmp_path / "nope.jsonl") == "antigravity"


class TestResolveTranscriptId:
    """Tests for extracting conversation ID from transcript path."""

    def test_antigravity_path(self, tmp_path):
        """Standard Antigravity path resolves to conversation UUID."""
        # Simulate: brain/<uuid>/.system_generated/logs/transcript.jsonl
        t_dir = tmp_path / "abc-123" / ".system_generated" / "logs"
        t_dir.mkdir(parents=True)
        transcript = t_dir / "transcript.jsonl"
        transcript.touch()
        assert resolve_transcript_id(transcript, "antigravity") == "abc-123"

    def test_flat_path(self, tmp_path):
        """Transcript directly in a named directory resolves to dir name."""
        transcript = tmp_path / "my-session" / "transcript.jsonl"
        transcript.parent.mkdir(parents=True)
        transcript.touch()
        assert resolve_transcript_id(transcript, "antigravity") == "my-session"

"""Tests for self-healing corrupt file quarantine (aegis_core.quarantine)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from aegis_core.quarantine import (
    quarantine_file,
    safe_parse_cell_file,
    safe_read_jsonl,
    QUARANTINE_DIR,
)


class TestCorruptFileQuarantine:
    """Test suite for isolating damaged governance state without system crash."""

    def test_quarantines_corrupt_yaml_cell(self, tmp_path: Path):
        """Corrupted YAML frontmatter in a cell is isolated and logged cleanly."""
        cells_dir = tmp_path / ".soma" / "cells" / "walls"
        cells_dir.mkdir(parents=True)
        bad_cell = cells_dir / "bad_rule.md"
        bad_cell.write_text(
            "---\n"
            "id: bad_rule\n"
            "triggers: [unclosed list\n"
            "type: wall\n"
            "---\n"
            "Rule content here\n",
            encoding="utf-8",
        )

        metadata, body, status = safe_parse_cell_file(bad_cell, workspace=tmp_path)
        assert status == "quarantined"
        assert not bad_cell.exists()

        quarantine_dir = tmp_path / ".soma" / QUARANTINE_DIR
        assert quarantine_dir.exists()
        quarantined_files = list(quarantine_dir.glob("bad_rule.*.corrupt"))
        assert len(quarantined_files) == 1

        log_file = quarantine_dir / "quarantine_log.jsonl"
        assert log_file.exists()
        log_entries = [json.loads(line) for line in log_file.read_text(encoding="utf-8").splitlines() if line]
        assert len(log_entries) == 1
        assert log_entries[0]["original_path"].endswith("bad_rule.md")
        assert "bad_rule" in log_entries[0]["quarantined_file"]

    def test_safe_parse_healthy_cell_leaves_file_intact(self, tmp_path: Path):
        """Valid cell frontmatter is parsed normally without triggering quarantine."""
        cell_file = tmp_path / "valid_rule.md"
        cell_file.write_text(
            "---\n"
            "id: valid_rule\n"
            "type: wall\n"
            "triggers: 10\n"
            "---\n"
            "Valid body content\n",
            encoding="utf-8",
        )

        metadata, body, status = safe_parse_cell_file(cell_file, workspace=tmp_path)
        assert status == "ok"
        assert metadata["id"] == "valid_rule"
        assert "Valid body content" in body
        assert cell_file.exists()

    def test_safe_read_jsonl_quarantines_completely_corrupted_file(self, tmp_path: Path):
        """Completely binary garbage in a JSONL file is quarantined."""
        ev_dir = tmp_path / ".soma" / "evidence"
        ev_dir.mkdir(parents=True)
        corrupt_jsonl = ev_dir / "corrupted_ledger.jsonl"
        corrupt_jsonl.write_bytes(b"\x00\x01\x02\xff\xfe\x00\x00NOT_JSON_AT_ALL")

        records, status = safe_read_jsonl(corrupt_jsonl, workspace=tmp_path)
        assert status == "quarantined"
        assert records == []
        assert not corrupt_jsonl.exists()
        quarantine_dir = tmp_path / ".soma" / QUARANTINE_DIR
        assert any(quarantine_dir.glob("corrupted_ledger.*.corrupt"))

    def test_safe_read_jsonl_whitespace_only_not_quarantined(self, tmp_path: Path):
        """Whitespace-only or blank JSONL files are not falsely quarantined."""
        jsonl_file = tmp_path / "empty_ledger.jsonl"
        jsonl_file.write_text("\n\n   \n", encoding="utf-8")
        records, status = safe_read_jsonl(jsonl_file, workspace=tmp_path)
        assert status == "ok"
        assert records == []
        assert jsonl_file.exists()
        assert not (tmp_path / ".soma" / QUARANTINE_DIR).exists()

    def test_safe_parse_cell_without_frontmatter_preserves_thematic_breaks(self, tmp_path: Path):
        """Markdown cell without frontmatter preserves entire body including thematic breaks."""
        cell = tmp_path / "raw_cell.md"
        raw_content = "# Header\n\nIntro paragraph\n\n---\n\nBody paragraph"
        cell.write_text(raw_content, encoding="utf-8")
        meta, body, status = safe_parse_cell_file(cell, workspace=tmp_path)
        assert status == "ok"
        assert meta == {}
        assert "Intro paragraph" in body
        assert "Body paragraph" in body
        assert cell.exists()


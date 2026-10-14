"""TDD tests for enzymes/insight_capture.py — Gate 1 of Core Change Protocol.

Tests written BEFORE implementation. Must fail (red phase) until
insight_capture.py is implemented.
"""
import json
import os
import pytest


class TestCaptureInsight:
    """Tests for the capture_insight() function."""

    def test_creates_jsonl_file(self, tmp_path):
        """Capturing an insight creates .soma/human_insights.jsonl if missing."""
        from aegis_core.insights import capture_insight

        workspace = str(tmp_path)
        os.makedirs(os.path.join(workspace, ".soma"), exist_ok=True)

        capture_insight(
            workspace=workspace,
            insight="Sprite dimensions don't match slicer expectations",
            context_files=["tools/slice_sprite_sheet.py"],
        )

        jsonl_path = os.path.join(workspace, ".soma", "human_insights.jsonl")
        assert os.path.exists(jsonl_path)

    def test_record_has_required_fields(self, tmp_path):
        """Each record must contain timestamp, insight, context_files, was_covered."""
        from aegis_core.insights import capture_insight

        workspace = str(tmp_path)
        os.makedirs(os.path.join(workspace, ".soma"), exist_ok=True)

        result = capture_insight(
            workspace=workspace,
            insight="Check API response schema",
            context_files=["api/handler.py"],
        )

        assert "timestamp" in result
        assert result["insight"] == "Check API response schema"
        assert result["context_files"] == ["api/handler.py"]
        assert "was_covered" in result
        assert "covering_cells" in result

    def test_appends_to_existing_file(self, tmp_path):
        """Multiple captures append to the same JSONL file."""
        from aegis_core.insights import capture_insight

        workspace = str(tmp_path)
        os.makedirs(os.path.join(workspace, ".soma"), exist_ok=True)

        capture_insight(workspace=workspace, insight="First", context_files=["a.py"])
        capture_insight(workspace=workspace, insight="Second", context_files=["b.py"])

        jsonl_path = os.path.join(workspace, ".soma", "human_insights.jsonl")
        with open(jsonl_path) as f:
            lines = [json.loads(line) for line in f if line.strip()]
        assert len(lines) == 2
        assert lines[0]["insight"] == "First"
        assert lines[1]["insight"] == "Second"

    def test_optional_category(self, tmp_path):
        """Category field is optional and included when provided."""
        from aegis_core.insights import capture_insight

        workspace = str(tmp_path)
        os.makedirs(os.path.join(workspace, ".soma"), exist_ok=True)

        result = capture_insight(
            workspace=workspace,
            insight="Contract mismatch",
            context_files=["a.py"],
            category="contract_mismatch",
        )
        assert result["category"] == "contract_mismatch"

    def test_optional_source_conversation(self, tmp_path):
        """source_conversation field is optional and included when provided."""
        from aegis_core.insights import capture_insight

        workspace = str(tmp_path)
        os.makedirs(os.path.join(workspace, ".soma"), exist_ok=True)

        result = capture_insight(
            workspace=workspace,
            insight="Check this",
            context_files=["a.py"],
            source_conversation="abc-123",
        )
        assert result["source_conversation"] == "abc-123"

    def test_covering_cells_detected(self, tmp_path):
        """When a cell's target_paths match context_files, it appears in covering_cells."""
        from aegis_core.insights import capture_insight

        workspace = str(tmp_path)
        cells_dir = os.path.join(workspace, ".soma", "cells", "vacuoles")
        os.makedirs(cells_dir, exist_ok=True)

        # Create a cell that covers "api/*.py"
        cell_content = """---
type: vacuole
enforcement: advisory
hypothesis: "API handlers should validate input"
target_paths:
  - "api/*.py"
fitness:
  triggers: 3
  true_positives: 2
  false_positives: 0
---
Check API input validation.
"""
        with open(os.path.join(cells_dir, "vacuole-api-validation.md"), "w") as f:
            f.write(cell_content)

        result = capture_insight(
            workspace=workspace,
            insight="Missing input validation",
            context_files=["api/handler.py"],
        )
        assert result["was_covered"] is True
        assert "vacuole-api-validation" in result["covering_cells"]

    def test_uncovered_insight(self, tmp_path):
        """When no cells cover context_files, was_covered is False."""
        from aegis_core.insights import capture_insight

        workspace = str(tmp_path)
        os.makedirs(os.path.join(workspace, ".soma"), exist_ok=True)

        result = capture_insight(
            workspace=workspace,
            insight="Unrelated insight",
            context_files=["totally/unrelated/file.py"],
        )
        assert result["was_covered"] is False
        assert result["covering_cells"] == []

    def test_empty_context_files_rejected(self, tmp_path):
        """Insights must reference at least one file."""
        from aegis_core.insights import capture_insight

        workspace = str(tmp_path)
        os.makedirs(os.path.join(workspace, ".soma"), exist_ok=True)

        with pytest.raises(ValueError, match="context_files"):
            capture_insight(
                workspace=workspace,
                insight="No files referenced",
                context_files=[],
            )

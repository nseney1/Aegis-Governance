"""TDD tests for create_cell_from_insight_cluster in cell_create_nl.py.

Gate 1 return: these functions were shipped without tests (Gate 1 violation
caught by Tempest review).
"""
import os
import sys
import pytest

from aegis_core.insights import create_cell_from_insight_cluster


class TestCreateCellFromInsightCluster:
    """Tests for create_cell_from_insight_cluster()."""

    def test_creates_cell_file(self, tmp_path):
        """A cluster produces a cell file in .aegis/rules/vacuoles/."""

        workspace = str(tmp_path)
        cluster = {
            "pattern_id": "contract-mismatch-abc123",
            "insight_count": 5,
            "common_files": ["api/*.py", "handlers/*.py"],
            "common_category": "contract_mismatch",
            "confidence": 0.71,
        }

        filepath = create_cell_from_insight_cluster(cluster, workspace)
        assert os.path.isfile(filepath)
        assert "vacuoles" in filepath

    def test_cell_contains_frontmatter(self, tmp_path):
        """Generated cell has YAML frontmatter with required fields."""

        workspace = str(tmp_path)
        cluster = {
            "pattern_id": "attention-gap-def456",
            "insight_count": 3,
            "common_files": ["src/*.py"],
            "common_category": "attention_gap",
            "confidence": 0.6,
        }

        filepath = create_cell_from_insight_cluster(cluster, workspace)
        with open(filepath) as f:
            content = f.read()

        assert content.startswith("---")
        assert "type: vacuole" in content
        assert "origin: human_insight" in content
        assert "src/*.py" in content

    def test_cell_has_hypothesis(self, tmp_path):
        """Generated cell has a hypothesis in frontmatter."""

        workspace = str(tmp_path)
        cluster = {
            "pattern_id": "test-cluster",
            "insight_count": 4,
            "common_files": ["tools/*.py"],
            "common_category": "contract",
            "confidence": 0.67,
        }

        filepath = create_cell_from_insight_cluster(cluster, workspace)
        with open(filepath) as f:
            content = f.read()

        assert "hypothesis:" in content

    def test_slug_sanitized(self, tmp_path):
        """Category with special characters produces a safe filename."""

        workspace = str(tmp_path)
        cluster = {
            "pattern_id": "weird-cat",
            "insight_count": 3,
            "common_files": ["x.py"],
            "common_category": "weird/category with spaces!",
            "confidence": 0.6,
        }

        filepath = create_cell_from_insight_cluster(cluster, workspace)
        basename = os.path.basename(filepath)
        assert "/" not in basename
        assert " " not in basename
        assert "!" not in basename

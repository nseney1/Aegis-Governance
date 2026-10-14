"""TDD tests for enzymes/insight_correlator.py — Gate 1 of Core Change Protocol.

Tests written BEFORE implementation.
"""
import json
import os
import pytest


def _write_insights(workspace, insights):
    """Helper: write a list of insight dicts to .soma/human_insights.jsonl."""
    jsonl_path = os.path.join(workspace, ".soma", "human_insights.jsonl")
    os.makedirs(os.path.dirname(jsonl_path), exist_ok=True)
    with open(jsonl_path, "w") as f:
        for record in insights:
            f.write(json.dumps(record) + "\n")


class TestClusterInsights:
    """Tests for cluster_insights()."""

    def test_clusters_by_category(self, tmp_path):
        """Insights with the same category are grouped."""
        from aegis_core.insights import cluster_insights

        workspace = str(tmp_path)
        insights = [
            {"insight": "A", "context_files": ["a.py"], "category": "contract_mismatch",
             "timestamp": "2026-09-29T10:00:00Z", "was_covered": False, "covering_cells": []},
            {"insight": "B", "context_files": ["b.py"], "category": "contract_mismatch",
             "timestamp": "2026-09-29T11:00:00Z", "was_covered": False, "covering_cells": []},
            {"insight": "C", "context_files": ["c.py"], "category": "contract_mismatch",
             "timestamp": "2026-09-29T12:00:00Z", "was_covered": False, "covering_cells": []},
        ]
        _write_insights(workspace, insights)

        clusters = cluster_insights(workspace, min_cluster_size=3)
        assert len(clusters) >= 1
        assert clusters[0]["common_category"] == "contract_mismatch"
        assert clusters[0]["insight_count"] >= 3

    def test_below_threshold_no_cluster(self, tmp_path):
        """Fewer insights than min_cluster_size produces no clusters."""
        from aegis_core.insights import cluster_insights

        workspace = str(tmp_path)
        insights = [
            {"insight": "A", "context_files": ["a.py"], "category": "attention_gap",
             "timestamp": "2026-09-29T10:00:00Z", "was_covered": False, "covering_cells": []},
            {"insight": "B", "context_files": ["b.py"], "category": "attention_gap",
             "timestamp": "2026-09-29T11:00:00Z", "was_covered": False, "covering_cells": []},
        ]
        _write_insights(workspace, insights)

        clusters = cluster_insights(workspace, min_cluster_size=3)
        assert len(clusters) == 0

    def test_separate_categories_separate_clusters(self, tmp_path):
        """Different categories produce separate clusters."""
        from aegis_core.insights import cluster_insights

        workspace = str(tmp_path)
        insights = [
            {"insight": f"C{i}", "context_files": ["a.py"], "category": "contract",
             "timestamp": f"2026-09-29T1{i}:00:00Z", "was_covered": False, "covering_cells": []}
            for i in range(3)
        ] + [
            {"insight": f"A{i}", "context_files": ["b.py"], "category": "attention",
             "timestamp": f"2026-09-29T1{i}:00:00Z", "was_covered": False, "covering_cells": []}
            for i in range(3)
        ]
        _write_insights(workspace, insights)

        clusters = cluster_insights(workspace, min_cluster_size=3)
        categories = {c["common_category"] for c in clusters}
        assert "contract" in categories
        assert "attention" in categories

    def test_null_category_coerced(self, tmp_path):
        """Insights with category=None are grouped as 'uncategorized'."""
        from aegis_core.insights import cluster_insights

        workspace = str(tmp_path)
        insights = [
            {"insight": f"N{i}", "context_files": ["a.py"], "category": None,
             "timestamp": f"2026-09-29T1{i}:00:00Z", "was_covered": False, "covering_cells": []}
            for i in range(3)
        ]
        _write_insights(workspace, insights)

        clusters = cluster_insights(workspace, min_cluster_size=3)
        assert len(clusters) == 1
        assert clusters[0]["common_category"] == "uncategorized"

    def test_window_days_filters_old(self, tmp_path):
        """Insights older than window_days are excluded."""
        from aegis_core.insights import cluster_insights

        workspace = str(tmp_path)
        insights = [
            {"insight": f"Old{i}", "context_files": ["a.py"], "category": "stale",
             "timestamp": "2025-01-01T10:00:00Z", "was_covered": False, "covering_cells": []}
            for i in range(5)
        ]
        _write_insights(workspace, insights)

        clusters = cluster_insights(workspace, min_cluster_size=3, window_days=30)
        assert len(clusters) == 0

    def test_empty_file_no_crash(self, tmp_path):
        """Empty or missing JSONL file returns empty list."""
        from aegis_core.insights import cluster_insights

        workspace = str(tmp_path)
        os.makedirs(os.path.join(workspace, ".soma"), exist_ok=True)

        clusters = cluster_insights(workspace)
        assert clusters == []


class TestGenerateCellCandidates:
    """Tests for generate_cell_candidates()."""

    def test_produces_candidate_per_cluster(self, tmp_path):
        """Each cluster produces one cell candidate."""
        from aegis_core.insights import generate_cell_candidates

        workspace = str(tmp_path)
        clusters = [
            {
                "pattern_id": "contract-mismatch-tools",
                "insight_count": 4,
                "common_files": ["tools/*.py"],
                "common_category": "contract_mismatch",
                "confidence": 0.75,
            }
        ]

        candidates = generate_cell_candidates(clusters, workspace)
        assert len(candidates) == 1
        assert "hypothesis" in candidates[0]
        assert "target_paths" in candidates[0]
        assert candidates[0]["origin"] == "human_insight"

    def test_candidate_has_target_paths(self, tmp_path):
        """Candidate target_paths derived from cluster common_files."""
        from aegis_core.insights import generate_cell_candidates

        workspace = str(tmp_path)
        clusters = [
            {
                "pattern_id": "test-cluster",
                "insight_count": 3,
                "common_files": ["api/*.py", "handlers/*.py"],
                "common_category": "validation",
                "confidence": 0.6,
            }
        ]

        candidates = generate_cell_candidates(clusters, workspace)
        assert set(candidates[0]["target_paths"]) == {"api/*.py", "handlers/*.py"}

    def test_empty_clusters_empty_candidates(self, tmp_path):
        """No clusters means no candidates."""
        from aegis_core.insights import generate_cell_candidates

        workspace = str(tmp_path)
        candidates = generate_cell_candidates([], workspace)
        assert candidates == []

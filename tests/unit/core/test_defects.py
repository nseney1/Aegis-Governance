"""Unit tests for aegis_core.defects and aegis_core.insights."""
import os
import json
import tempfile
import pytest

from aegis_core.defects import (
    BoostConfig,
    HotZoneReport,
    compute_hot_zones,
    compute_cell_boost,
    match_glob,
    load_cells,
    find_covering_cells,
    record_escaped_defect,
    update_cell_escaped_rate,
    compute_enhanced_fitness,
    audit_expiry,
    prune_expired,
)
from aegis_core.insights import (
    capture_insight,
    cluster_insights,
    generate_cell_candidates,
)


def test_defects_hot_zones_computation():
    registry = {
        "bugs": [
            {"id": "BUG-001", "affected_files": ["foo.py"], "root_cause": "path_error"},
            {"id": "BUG-002", "affected_files": ["foo.py", "bar.py"], "root_cause": "path_error"},
            {"id": "BUG-003", "affected_files": ["bar.py"], "root_cause": "schema_drift"},
        ],
        "boost_config": {
            "file_heat_threshold": 2,
            "pattern_heat_threshold": 2,
        },
    }
    report = compute_hot_zones(registry)
    assert report.total_bugs_analyzed == 3
    assert "foo.py" in report.active_file_zones
    assert "path_error" in report.active_pattern_zones


def test_defects_match_glob():
    assert match_glob("soma_core/scoring.py", "soma_core/*.py")
    assert match_glob("a/b/c/d.py", "**/*.py")
    assert not match_glob("a/b/c/d.txt", "**/*.py")


def test_insights_capture_and_clustering(tmp_path):
    ws = str(tmp_path)
    os.makedirs(os.path.join(ws, ".soma", "cells"), exist_ok=True)

    rec = capture_insight(
        workspace=ws,
        insight="Cache invalidation defect",
        context_files=["cache.py"],
        category="cache",
    )
    assert rec["insight"] == "Cache invalidation defect"
    assert rec["category"] == "cache"

    # Add 2 more to reach cluster threshold of 3
    capture_insight(workspace=ws, insight="Cache TTL expired early", context_files=["cache.py"], category="cache")
    capture_insight(workspace=ws, insight="Cache key collision", context_files=["cache.py"], category="cache")

    clusters = cluster_insights(ws, min_cluster_size=3)
    assert len(clusters) == 1
    assert clusters[0]["common_category"] == "cache"

    candidates = generate_cell_candidates(clusters, ws)
    assert len(candidates) == 1
    assert "cache" in candidates[0]["hypothesis"]

"""Unit tests for aegis_core.defects."""
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



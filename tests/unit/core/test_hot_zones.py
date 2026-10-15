from pathlib import Path
"""Tests for aegis_sdk.hot_zones — bug registry → cell fitness boost."""
import os
import sys

import pytest

REPO_ROOT = str(next(p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").exists()))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from aegis_sdk.hot_zones import (
    BoostConfig,
    HotZoneReport,
    compute_cell_boost,
    compute_hot_zones,
    load_config,
    load_report_from_workspace,
)


def _registry(bugs, config_overrides=None):
    """Build a minimal registry dict."""
    reg = {
        "schema_version": "1.0",
        "boost_config": {
            "file_heat_threshold": 2,
            "pattern_heat_threshold": 3,
            "release_window": 10,
            "min_outcomes_for_boost": 3,
            "max_file_boost": 0.5,
            "max_pattern_boost": 0.3,
        },
        "root_cause_categories": {
            "path_error": "Wrong path",
            "schema_drift": "Schema mismatch",
            "silent_failure": "Error swallowed",
        },
        "severity_levels": ["critical", "moderate", "low"],
        "bugs": bugs,
    }
    if config_overrides:
        reg["boost_config"].update(config_overrides)
    return reg


def _bug(bug_id, root_cause, files):
    return {
        "id": bug_id,
        "title": f"Bug {bug_id}",
        "discovered_in": "v0.1",
        "fixed_in": "v0.2",
        "root_cause": root_cause,
        "severity": "critical",
        "affected_files": files,
        "regression_test": "tests/test_foo.py::test_bar",
        "changelog_ref": "v0.2",
    }


class TestComputeHotZones:
    """Core hot zone computation."""

    def test_empty_registry(self):
        report = compute_hot_zones(_registry([]))
        assert report.file_heat == {}
        assert report.pattern_heat == {}
        assert report.active_file_zones == []
        assert report.active_pattern_zones == []

    def test_single_bug_no_hot_zones(self):
        """One bug per file/category → below threshold → no active zones."""
        bugs = [_bug("B1", "path_error", ["foo.py"])]
        report = compute_hot_zones(_registry(bugs))
        assert report.file_heat == {"foo.py": 1}
        assert report.pattern_heat == {"path_error": 1}
        assert report.active_file_zones == []  # Below threshold=2
        assert report.active_pattern_zones == []  # Below threshold=3

    def test_file_heat_activates_at_threshold(self):
        """Two bugs on same file → file becomes hot zone."""
        bugs = [
            _bug("B1", "path_error", ["engine.py"]),
            _bug("B2", "schema_drift", ["engine.py"]),
        ]
        report = compute_hot_zones(_registry(bugs))
        assert report.file_heat["engine.py"] == 2
        assert "engine.py" in report.active_file_zones

    def test_pattern_heat_activates_at_threshold(self):
        """Three bugs with same root cause → pattern becomes hot zone."""
        bugs = [
            _bug("B1", "path_error", ["a.py"]),
            _bug("B2", "path_error", ["b.py"]),
            _bug("B3", "path_error", ["c.py"]),
        ]
        report = compute_hot_zones(_registry(bugs))
        assert report.pattern_heat["path_error"] == 3
        assert "path_error" in report.active_pattern_zones

    def test_pattern_below_threshold_not_active(self):
        """Two bugs with same root cause → below threshold=3."""
        bugs = [
            _bug("B1", "path_error", ["a.py"]),
            _bug("B2", "path_error", ["b.py"]),
        ]
        report = compute_hot_zones(_registry(bugs))
        assert report.pattern_heat["path_error"] == 2
        assert report.active_pattern_zones == []

    def test_multiple_hot_zones(self):
        """Multiple files and patterns can be hot simultaneously."""
        bugs = [
            _bug("B1", "path_error", ["engine.py"]),
            _bug("B2", "path_error", ["engine.py", "sync.py"]),
            _bug("B3", "path_error", ["sync.py"]),
        ]
        report = compute_hot_zones(_registry(bugs))
        assert "engine.py" in report.active_file_zones
        assert "sync.py" in report.active_file_zones
        assert "path_error" in report.active_pattern_zones


class TestComputeCellBoost:
    """Rule boost calculation."""

    def test_zero_boost_below_outcome_threshold(self):
        """Cells with too few outcomes get zero boost."""
        report = HotZoneReport(
            file_heat={"engine.py": 3},
            active_file_zones=["engine.py"],
            config=BoostConfig(min_outcomes_for_boost=3),
        )
        cell = {"_name": "trap-test", "target_paths": ["engine.py"]}
        assert compute_cell_boost(cell, report, outcome_count=2) == 0.0

    def test_file_boost_with_matching_target(self):
        """Rule targeting a hot zone file gets file boost."""
        report = HotZoneReport(
            file_heat={"enzymes/engine.py": 3},
            active_file_zones=["enzymes/engine.py"],
            config=BoostConfig(min_outcomes_for_boost=0),
        )
        cell = {"_name": "trap-test", "target_paths": ["enzymes/*.py"]}
        boost = compute_cell_boost(cell, report, outcome_count=5)
        assert boost > 0.0

    def test_no_boost_without_matching_target(self):
        """Rule not targeting hot zone files gets no file boost."""
        report = HotZoneReport(
            file_heat={"enzymes/engine.py": 3},
            active_file_zones=["enzymes/engine.py"],
            config=BoostConfig(min_outcomes_for_boost=0),
        )
        cell = {"_name": "trap-test", "target_paths": ["docs/*.md"]}
        boost = compute_cell_boost(cell, report, outcome_count=5)
        assert boost == 0.0

    def test_file_boost_capped(self):
        """File boost cannot exceed max_file_boost."""
        report = HotZoneReport(
            file_heat={"a.py": 10, "b.py": 10, "c.py": 10},
            active_file_zones=["a.py", "b.py", "c.py"],
            config=BoostConfig(min_outcomes_for_boost=0, max_file_boost=0.5),
        )
        cell = {"_name": "trap-test", "target_paths": ["*.py"]}
        boost = compute_cell_boost(cell, report, outcome_count=5)
        assert boost <= 0.5

    def test_pattern_boost_with_matching_tag(self):
        """Rule with tag matching hot pattern gets pattern boost."""
        report = HotZoneReport(
            pattern_heat={"path_error": 4},
            active_pattern_zones=["path_error"],
            config=BoostConfig(min_outcomes_for_boost=0),
        )
        cell = {"_name": "trap-test", "target_paths": [], "tags": ["data_path"]}
        boost = compute_cell_boost(cell, report, outcome_count=5)
        assert boost > 0.0

    def test_combined_boost(self):
        """File + pattern boost combine additively."""
        report = HotZoneReport(
            file_heat={"engine.py": 3},
            pattern_heat={"path_error": 4},
            active_file_zones=["engine.py"],
            active_pattern_zones=["path_error"],
            config=BoostConfig(min_outcomes_for_boost=0),
        )
        cell = {"_name": "trap-test", "target_paths": ["engine.py"], "tags": ["data_path"]}
        boost = compute_cell_boost(cell, report, outcome_count=5)
        # Should have both file and pattern components
        assert boost > 0.0

    def test_empty_report_zero_boost(self):
        """Empty report → zero boost."""
        report = HotZoneReport()
        cell = {"_name": "trap-test", "target_paths": ["*.py"], "tags": ["path"]}
        boost = compute_cell_boost(cell, report, outcome_count=5)
        assert boost == 0.0


class TestLoadConfig:
    """Config loading from registry."""

    def test_defaults_when_missing(self):
        config = load_config({})
        assert config.file_heat_threshold == 2
        assert config.pattern_heat_threshold == 3

    def test_overrides(self):
        config = load_config({"boost_config": {"file_heat_threshold": 5}})
        assert config.file_heat_threshold == 5
        assert config.pattern_heat_threshold == 3  # Default preserved


class TestLoadFromWorkspace:
    """Workspace loading integration."""

    def test_missing_registry_returns_none(self, tmp_path):
        assert load_report_from_workspace(str(tmp_path)) is None

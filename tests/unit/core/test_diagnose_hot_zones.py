from pathlib import Path
"""Tests for enzymes/diagnose_hot_zones.py — hot zone monitoring hook."""
import os
import sys

import pytest

REPO_ROOT = str(next(p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").exists()))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from aegis_sdk.hot_zones import BoostConfig, HotZoneReport
from aegis_core.defects import (
    proximity_alerts,
    threshold_sanity,
    run_diagnostic,
)


def _report(file_heat=None, pattern_heat=None, active_files=None,
            active_patterns=None, total=5, config=None):
    return HotZoneReport(
        file_heat=file_heat or {},
        pattern_heat=pattern_heat or {},
        active_file_zones=active_files or [],
        active_pattern_zones=active_patterns or [],
        config=config or BoostConfig(),
        total_bugs_analyzed=total,
    )


class TestProximityAlerts:

    def test_active_zone_shows_fire(self):
        report = _report(
            pattern_heat={"path_error": 4},
            active_patterns=["path_error"],
            config=BoostConfig(pattern_heat_threshold=3),
        )
        alerts = proximity_alerts(report)
        assert any("ACTIVE" in a and "path_error" in a for a in alerts)

    def test_approaching_threshold_shows_warning(self):
        report = _report(
            pattern_heat={"path_error": 2},
            config=BoostConfig(pattern_heat_threshold=3),
        )
        alerts = proximity_alerts(report)
        assert any("1 more bug" in a and "path_error" in a for a in alerts)

    def test_far_from_threshold_shows_dot(self):
        report = _report(
            pattern_heat={"path_error": 1},
            config=BoostConfig(pattern_heat_threshold=5),
        )
        alerts = proximity_alerts(report)
        assert any("·" in a and "path_error" in a for a in alerts)

    def test_file_approaching_shows_warning(self):
        report = _report(
            file_heat={"engine.py": 1},
            config=BoostConfig(file_heat_threshold=2),
        )
        alerts = proximity_alerts(report)
        assert any("1 more bug" in a and "engine.py" in a for a in alerts)

    def test_file_active_shows_fire(self):
        report = _report(
            file_heat={"engine.py": 3},
            active_files=["engine.py"],
            config=BoostConfig(file_heat_threshold=2),
        )
        alerts = proximity_alerts(report)
        assert any("ACTIVE" in a and "engine.py" in a for a in alerts)


class TestThresholdSanity:

    def test_insufficient_data_below_10(self):
        report = _report(total=5)
        warnings = threshold_sanity(report)
        assert len(warnings) == 1
        assert "Insufficient data" in warnings[0]

    def test_no_warning_at_10_with_activity(self):
        report = _report(
            total=10,
            active_files=["a.py"],
            file_heat={"a.py": 3, "b.py": 1},
        )
        warnings = threshold_sanity(report)
        assert not any("Insufficient" in w for w in warnings)

    def test_no_activation_warning_at_20(self):
        report = _report(total=20)
        warnings = threshold_sanity(report)
        assert any("zero hot zones" in w for w in warnings)

    def test_too_noisy_file_warning(self):
        report = _report(
            total=15,
            file_heat={"a.py": 3, "b.py": 3, "c.py": 3},
            active_files=["a.py", "b.py", "c.py"],
        )
        warnings = threshold_sanity(report)
        assert any("too low" in w for w in warnings)

    def test_too_noisy_pattern_warning(self):
        report = _report(
            total=15,
            pattern_heat={"path_error": 5, "schema_drift": 4},
            active_patterns=["path_error", "schema_drift"],
        )
        warnings = threshold_sanity(report)
        assert any("pattern_heat_threshold" in w for w in warnings)


class TestRunDiagnostic:

    def test_missing_registry(self, tmp_path):
        result = run_diagnostic(str(tmp_path))
        assert result == {'error': 'BUG_REGISTRY.json not found'}

from pathlib import Path
"""Tests for verify_bug_registry enzyme."""
import json
import os
import sys

import pytest

REPO_ROOT = str(next(p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").exists()))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from aegis_core.enforcement import (
    load_registry,
    verify_regression_tests,
    verify_schema,
    verify_unique_ids,
)


def _make_registry(tmp_path, bugs, categories=None, severities=None):
    """Create a test BUG_REGISTRY.json."""
    registry = {
        "schema_version": "1.0",
        "root_cause_categories": categories or {
            "path_error": "Wrong path",
            "schema_drift": "Schema mismatch",
        },
        "severity_levels": severities or ["critical", "moderate", "low"],
        "bugs": bugs,
    }
    path = tmp_path / "docs" / "project"
    path.mkdir(parents=True, exist_ok=True)
    with open(path / "BUG_REGISTRY.json", "w") as f:
        json.dump(registry, f)
    return registry


class TestVerifySchema:
    """Schema validation tests."""

    def test_valid_bug_passes(self, tmp_path):
        bugs = [{
            "id": "BUG-001", "title": "Test bug", "discovered_in": "v0.1",
            "fixed_in": "v0.2", "root_cause": "path_error", "severity": "critical",
            "affected_files": ["foo.py"], "regression_test": "tests/test_foo.py::test_bar",
            "changelog_ref": "v0.2",
        }]
        registry = _make_registry(tmp_path, bugs)
        errors = verify_schema(registry)
        assert len(errors) == 0

    def test_missing_field_flagged(self, tmp_path):
        bugs = [{"id": "BUG-001", "title": "Incomplete"}]
        registry = _make_registry(tmp_path, bugs)
        errors = verify_schema(registry)
        assert len(errors) > 0
        assert any("missing required field" in e for e in errors)

    def test_invalid_root_cause_flagged(self, tmp_path):
        bugs = [{
            "id": "BUG-001", "title": "Bad cat", "discovered_in": "v0.1",
            "fixed_in": "v0.2", "root_cause": "nonexistent_category",
            "severity": "critical", "affected_files": ["foo.py"],
            "regression_test": "tests/test_foo.py::test", "changelog_ref": "v0.2",
        }]
        registry = _make_registry(tmp_path, bugs)
        errors = verify_schema(registry)
        assert any("unknown root_cause" in e for e in errors)

    def test_invalid_severity_flagged(self, tmp_path):
        bugs = [{
            "id": "BUG-001", "title": "Bad sev", "discovered_in": "v0.1",
            "fixed_in": "v0.2", "root_cause": "path_error",
            "severity": "supercritical", "affected_files": ["foo.py"],
            "regression_test": "tests/test_foo.py::test", "changelog_ref": "v0.2",
        }]
        registry = _make_registry(tmp_path, bugs)
        errors = verify_schema(registry)
        assert any("unknown severity" in e for e in errors)


def _open_bug(**overrides):
    bug = {
        "id": "BUG-010", "title": "Open bug", "status": "open",
        "discovered_in": "v0.3", "root_cause": "path_error",
        "severity": "moderate", "affected_files": ["foo.py"],
    }
    bug.update(overrides)
    return bug


def test_error_report_survives_cp1252_stdout(tmp_path):
    """BUG-012: printing the error report on a cp1252 stdout raised
    UnicodeEncodeError instead of listing the errors."""
    import subprocess

    _make_registry(tmp_path, [_open_bug(), _open_bug()])
    proc = subprocess.run(
        [sys.executable, "-c", "import sys; from aegis_core.enforcement import cli_verify_bug_registry; sys.exit(cli_verify_bug_registry(sys.argv[1:]))",
         "--workspace", str(tmp_path)],
        capture_output=True, encoding="cp1252", errors="replace", timeout=60,
        env=dict(os.environ, PYTHONIOENCODING="cp1252"),
    )
    assert "UnicodeEncodeError" not in proc.stderr, proc.stderr
    assert proc.returncode == 1
    assert "Duplicate bug ID: BUG-010" in proc.stdout


class TestOpenBugs:
    """Open bugs are tracked before a fix exists, so fix fields are not required."""

    def test_open_bug_without_fix_fields_passes(self, tmp_path):
        registry = _make_registry(tmp_path, [_open_bug()])
        assert verify_schema(registry) == []

    def test_open_bug_still_requires_core_fields(self, tmp_path):
        bug = _open_bug()
        del bug["affected_files"]
        registry = _make_registry(tmp_path, [bug])
        errors = verify_schema(registry)
        assert any("BUG-010: missing required field 'affected_files'" == e for e in errors)

    def test_open_bug_claiming_a_fix_is_flagged(self, tmp_path):
        registry = _make_registry(tmp_path, [_open_bug(fixed_in="v0.4")])
        errors = verify_schema(registry)
        assert any("BUG-010" in e and "open" in e and "fixed_in" in e for e in errors)

    def test_invalid_status_flagged(self, tmp_path):
        registry = _make_registry(tmp_path, [_open_bug(status="wontfix")])
        errors = verify_schema(registry)
        assert any("unknown status 'wontfix'" in e for e in errors)

    def test_explicit_fixed_status_still_requires_fix_fields(self, tmp_path):
        bug = _open_bug(status="fixed")
        registry = _make_registry(tmp_path, [bug])
        errors = verify_schema(registry)
        for field in ("fixed_in", "regression_test", "changelog_ref"):
            assert f"BUG-010: missing required field '{field}'" in errors

    def test_regression_check_skips_open_bugs(self, tmp_path):
        registry = _make_registry(tmp_path, [_open_bug()])
        assert verify_regression_tests(registry, str(tmp_path)) == []

    def test_regression_check_still_applies_to_fixed_bugs(self, tmp_path):
        bug = _open_bug(status="fixed", fixed_in="v0.4", changelog_ref="v0.4",
                        regression_test="tests/test_missing.py::test_x")
        registry = _make_registry(tmp_path, [bug])
        errors = verify_regression_tests(registry, str(tmp_path))
        assert errors == ["BUG-010: regression test file not found: tests/test_missing.py"]


class TestVerifyUniqueIds:
    """ID uniqueness tests."""

    def test_unique_ids_pass(self, tmp_path):
        bugs = [
            {"id": "BUG-001", "title": "A"},
            {"id": "BUG-002", "title": "B"},
        ]
        registry = _make_registry(tmp_path, bugs)
        errors = verify_unique_ids(registry)
        assert len(errors) == 0

    def test_duplicate_ids_flagged(self, tmp_path):
        bugs = [
            {"id": "BUG-001", "title": "A"},
            {"id": "BUG-001", "title": "B"},
        ]
        registry = _make_registry(tmp_path, bugs)
        errors = verify_unique_ids(registry)
        assert len(errors) == 1
        assert "Duplicate" in errors[0]


class TestVerifyRealRegistry:
    """Integration test against the actual bug registry."""

    def test_real_registry_schema_valid(self):
        """The actual BUG_REGISTRY.json passes schema validation."""
        registry = load_registry(REPO_ROOT)
        errors = verify_schema(registry)
        assert len(errors) == 0, f"Schema errors: {errors}"

    def test_real_registry_unique_ids(self):
        """The actual BUG_REGISTRY.json has no duplicate IDs."""
        registry = load_registry(REPO_ROOT)
        errors = verify_unique_ids(registry)
        assert len(errors) == 0, f"ID errors: {errors}"

    def test_real_registry_has_bugs(self):
        """The actual BUG_REGISTRY.json has at least the 5 backfilled bugs."""
        registry = load_registry(REPO_ROOT)
        assert len(registry['bugs']) >= 5

    def test_real_registry_regression_tests(self):
        """The actual BUG_REGISTRY.json regression tests all pass."""
        registry = load_registry(REPO_ROOT)
        errors = verify_regression_tests(registry, REPO_ROOT)
        assert len(errors) == 0, f"Regression test errors: {errors}"

class TestRegressionTestExecution:
    """Regression tests must actually be run, not just collected."""
    
    def test_regression_test_failure_is_caught(self, tmp_path):
        # Create a dummy failing test
        test_file = tmp_path / "test_failing.py"
        test_file.write_text("def test_fail():\n    assert False\n", encoding="utf-8")
        
        bug = {
            "id": "BUG-002", "title": "Failing test", "discovered_in": "v1",
            "fixed_in": "v2", "root_cause": "path_error", "severity": "critical",
            "affected_files": ["foo.py"], "regression_test": "test_failing.py::test_fail",
            "changelog_ref": "v2"
        }
        registry = _make_registry(tmp_path, [bug])
        
        errors = verify_regression_tests(registry, str(tmp_path))
        assert any("regression test failed" in str(e).lower() for e in errors), "Should report failure when test fails"
        
    def test_regression_test_pass_is_accepted(self, tmp_path):
        # Create a dummy passing test
        test_file = tmp_path / "test_passing.py"
        test_file.write_text("def test_pass():\n    assert True\n", encoding="utf-8")
        
        bug = {
            "id": "BUG-003", "title": "Passing test", "discovered_in": "v1",
            "fixed_in": "v2", "root_cause": "path_error", "severity": "critical",
            "affected_files": ["foo.py"], "regression_test": "test_passing.py::test_pass",
            "changelog_ref": "v2"
        }
        registry = _make_registry(tmp_path, [bug])
        
        errors = verify_regression_tests(registry, str(tmp_path))
        assert len(errors) == 0, "Should accept passing tests"


def _fixed_bug(bug_id, regression_test):
    return {
        "id": bug_id, "title": "t", "discovered_in": "v1", "fixed_in": "v2",
        "root_cause": "path_error", "severity": "low", "affected_files": ["foo.py"],
        "regression_test": regression_test, "changelog_ref": "v2",
    }


class TestRegressionRunBudget:
    """One 30 s limit covered the whole batch. Git Bash tests made the batch
    take ~28 s on Windows, so a clean registry could time out."""

    def _registry_of(self, tmp_path, count):
        (tmp_path / "test_a.py").write_text(
            "".join(f"def test_{i}():\n    pass\n" for i in range(count)), encoding="utf-8")
        bugs = [_fixed_bug(f"BUG-{i:03d}", f"test_a.py::test_{i}") for i in range(count)]
        return _make_registry(tmp_path, bugs)

    def _batch_taking(self, seconds, monkeypatch):
        import subprocess
        import aegis_core.enforcement as vbr

        def fake_run(cmd, **kwargs):
            if kwargs["timeout"] < seconds:
                raise subprocess.TimeoutExpired(cmd, kwargs["timeout"])
            return subprocess.CompletedProcess(cmd, 0, stdout="3 passed\n", stderr="")
        monkeypatch.setattr(vbr.subprocess, "run", fake_run)

    def test_batch_slower_than_30s_within_budget_passes(self, tmp_path, monkeypatch):
        registry = self._registry_of(tmp_path, 3)
        self._batch_taking(45, monkeypatch)
        assert verify_regression_tests(registry, str(tmp_path)) == []

    def test_budget_grows_with_the_registry(self, tmp_path, monkeypatch):
        # Longer than a 3-test registry is allowed (see the next test).
        registry = self._registry_of(tmp_path, 40)
        self._batch_taking(200, monkeypatch)
        assert verify_regression_tests(registry, str(tmp_path)) == []

    def test_hung_batch_reports_timeout_with_its_limit(self, tmp_path, monkeypatch):
        registry = self._registry_of(tmp_path, 3)
        self._batch_taking(10_000, monkeypatch)
        errors = verify_regression_tests(registry, str(tmp_path))
        assert len(errors) == 1
        assert "Timeout" in errors[0]
        assert "3 regression tests" in errors[0]
        assert "75 s" in errors[0]


class TestRegressionFailureAttribution:
    """A failure was pinned on every bug whose test name appeared anywhere in
    pytest's output, so test_check_more failing also blamed test_check."""

    def test_failure_blames_only_the_failing_bug(self, tmp_path):
        (tmp_path / "test_x.py").write_text(
            "def test_check():\n    pass\n\n"
            "def test_check_more():\n    assert False\n", encoding="utf-8")
        registry = _make_registry(tmp_path, [
            _fixed_bug("BUG-010", "test_x.py::test_check"),
            _fixed_bug("BUG-011", "test_x.py::test_check_more"),
        ])
        errors = verify_regression_tests(registry, str(tmp_path))
        assert "BUG-011: regression test failed: test_x.py::test_check_more" in errors
        assert not any(e.startswith("BUG-010") for e in errors), errors

    def test_failing_parameter_blames_its_bug(self, tmp_path):
        (tmp_path / "test_p.py").write_text(
            "import pytest\n\n"
            "@pytest.mark.parametrize('n', [1, 2])\n"
            "def test_param(n):\n    assert n == 1\n", encoding="utf-8")
        registry = _make_registry(tmp_path, [_fixed_bug("BUG-012", "test_p.py::test_param")])
        errors = verify_regression_tests(registry, str(tmp_path))
        assert "BUG-012: regression test failed: test_p.py::test_param" in errors

    def test_collection_error_blames_bugs_in_that_file(self, tmp_path):
        (tmp_path / "test_ok.py").write_text("def test_ok():\n    pass\n", encoding="utf-8")
        (tmp_path / "test_broken.py").write_text("def test_b(:\n    pass\n", encoding="utf-8")
        registry = _make_registry(tmp_path, [
            _fixed_bug("BUG-013", "test_ok.py::test_ok"),
            _fixed_bug("BUG-014", "test_broken.py::test_b"),
        ])
        errors = verify_regression_tests(registry, str(tmp_path))
        assert "BUG-014: regression test failed: test_broken.py::test_b" in errors
        assert not any(e.startswith("BUG-013") for e in errors), errors

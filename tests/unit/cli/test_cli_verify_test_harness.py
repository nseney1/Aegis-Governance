"""TDD Gate 1 tests for CLI verify test harness auto-wiring (Phase 11).

Tests prove:
1. discover_test_evidence identifies test files, parses test names via AST, and runs tests.
2. aegis check passes test_names and test_results to the Layer 2 pipeline.
3. Graceful degradation when no test files exist for target files.
"""
import argparse
import os
import sys
from unittest.mock import MagicMock, patch
import pytest

from aegis_cli import verify
from aegis_core.verification import ToolEvidence, Verdict


class TestVerifyTestHarnessDiscovery:
    """Verify test discovery and execution for Layer 2 evidence."""

    def test_discover_test_evidence_finds_tests_and_executes(self, tmp_path):
        """Must discover test file, extract test names, and run tests."""
        # Create a source file and corresponding test file
        src_file = tmp_path / "calc.py"
        src_file.write_text("def add(a, b): return a + b\n")

        test_dir = tmp_path / "tests"
        test_dir.mkdir()
        test_file = test_dir / "test_calc.py"
        test_file.write_text(
            "def test_add_positive(): assert 1 + 1 == 2\n"
            "def test_add_zero(): assert 1 + 0 == 1\n"
        )

        test_names, test_results = verify.discover_test_evidence(
            target_files=["calc.py"],
            repo_root=str(tmp_path),
        )

        assert "test_add_positive" in test_names
        assert "test_add_zero" in test_names
        assert "passed" in test_results.lower() or "100%" in test_results or len(test_results) > 0

    def test_discover_test_evidence_graceful_when_no_tests(self, tmp_path):
        """When no tests exist, returns empty list and empty string without crashing."""
        src_file = tmp_path / "untested.py"
        src_file.write_text("def noop(): pass\n")

        test_names, test_results = verify.discover_test_evidence(
            target_files=["untested.py"],
            repo_root=str(tmp_path),
        )

        assert test_names == []
        assert test_results == ""


class TestVerifyCLIWiringWithTestHarness:
    """Verify run_verify wires test evidence into the Layer 2 pipeline."""

    def test_run_verify_passes_test_evidence_to_layer2(self, tmp_path, monkeypatch):
        """run_verify must pass discovered test_names and test_results into VerificationPipeline.run."""
        src_file = tmp_path / "service.py"
        src_file.write_text("def serve(): return True\n")

        test_file = tmp_path / "test_service.py"
        test_file.write_text("def test_serve(): assert True\n")

        captured_kwargs = {}

        def mock_pipeline_run(self, **kwargs):
            captured_kwargs.update(kwargs)
            res = MagicMock()
            res.verdict = Verdict.SHIP
            res.arbitration_result = MagicMock()
            res.arbitration_result.verdict = Verdict.SHIP
            res.arbitration_result.divergences = []
            res.arbitration_result.convergences = []
            return res

        monkeypatch.setattr("aegis_core.verification.pipeline.VerificationPipeline.run", mock_pipeline_run)
        monkeypatch.setattr("aegis_core.verification.runner.run_layer1", lambda *a, **kw: [
            ToolEvidence("call_graph", "service.py", True, "ok")
        ])

        args = argparse.Namespace(
            files=["service.py"],
            repo_root=str(tmp_path),
            workspace=str(tmp_path),
            plan="Implement serve function",
            llm_cmd="unused-llm --never-run",
            layer1_only=False,
            dry_run=False,
            plain=False,
            no_emoji=False,
        )

        exit_code = verify.run_verify(args)
        assert exit_code == 0
        assert "test_names" in captured_kwargs
        assert "test_serve" in captured_kwargs["test_names"]
        assert "test_results" in captured_kwargs

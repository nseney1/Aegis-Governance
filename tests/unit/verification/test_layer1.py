from pathlib import Path
"""Integration tests for the Layer 1 runner + persistence checker.

Validates against the actual Soma codebase (post-fix) and against
synthetic pre-fix scenarios.
"""
import os
import sys
import textwrap
import tempfile

import pytest

# tests/test_verification/ → tests/ → REPO_ROOT
REPO_ROOT = str(next(p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").exists()))
sys.path.insert(0, REPO_ROOT)

from aegis_core.verification import ToolEvidence
from aegis_core.verification import persistence_checker
from aegis_core.verification import call_graph
from aegis_core.verification import runner
from unittest.mock import patch, MagicMock


class TestPersistenceChecker:
    """Test the persistence completeness checker against real and synthetic code."""


    def test_synthetic_gap_detected(self, tmp_path):
        """A file that mutates a key but doesn't serialize it should FAIL."""
        code = textwrap.dedent("""\
            def save(data):
                fitness = data.get('fitness', {})
                fitness['score'] = 0.5
                fitness['secret_key'] = 42  # not serialized!

                for line in lines:
                    if line.startswith('score:'):
                        line = f"score: {fitness['score']}"
                # secret_key never handled in serialization
        """)
        filepath = tmp_path / "test_file.py"
        filepath.write_text(code)

        result = persistence_checker.check(str(filepath), "fitness")
        assert result.verdict is False
        assert "secret_key" in result.detail

    def test_excluded_keys_not_flagged(self, tmp_path):
        """Keys in the exclude list should not be flagged as gaps."""
        code = textwrap.dedent("""\
            def process(data):
                fitness = data.get('fitness', {})
                fitness['cached_value'] = compute()  # intentionally in-memory only

                for line in lines:
                    pass  # no serialization at all
        """)
        filepath = tmp_path / "test_file.py"
        filepath.write_text(code)

        result = persistence_checker.check(str(filepath), "fitness", exclude={"cached_value"})
        assert result.verdict is True

    def test_no_mutations_passes(self, tmp_path):
        """A file with no dict mutations should pass trivially."""
        code = "x = 1\ny = 2\n"
        filepath = tmp_path / "empty.py"
        filepath.write_text(code)

        result = persistence_checker.check(str(filepath), "fitness")
        assert result.verdict is True


class TestCallGraph:
    """Test the call graph completeness checker."""


    def test_synthetic_orphan_detected(self, tmp_path):
        """A function with no call sites should be flagged."""
        code = textwrap.dedent("""\
            def orphan_function():
                pass

            def another_orphan():
                pass
        """)
        filepath = tmp_path / "orphan.py"
        filepath.write_text(code)

        result = call_graph.check(str(filepath), str(tmp_path))
        assert result.verdict is False
        assert "orphan_function" in result.detail or "another_orphan" in result.detail


class TestLayer1Runner:
    """Test the Layer 1 orchestrator."""


    def test_gate_verdict_all_pass(self):
        """Gate should pass when all tools pass."""
        results = [
            ToolEvidence("t1", "f1", True, "ok"),
            ToolEvidence("t2", "f2", True, "ok"),
        ]
        assert runner.gate_verdict(results) is True

    def test_gate_verdict_any_fail(self):
        """Gate should fail when any tool fails."""
        results = [
            ToolEvidence("t1", "f1", True, "ok"),
            ToolEvidence("t2", "f2", False, "gap found"),
        ]
        assert runner.gate_verdict(results) is False

    def test_format_summary_pass(self):
        results = [ToolEvidence("t1", "f1", True, "ok")]
        summary = runner.format_summary(results)
        assert "1/1 PASSED" in summary

    def test_format_summary_fail(self):
        results = [
            ToolEvidence("t1", "f1", True, "ok"),
            ToolEvidence("t2", "f2", False, "gap"),
        ]
        summary = runner.format_summary(results)
        assert "1/2 FAILED" in summary


# ── 2A: Mutation Tester + Branch Coverage in Runner ─────────────────


class TestRunnerMutationTesterIntegration:
    """run_layer1() should wire mutation_tester with auto-discovery."""

    def test_mutation_targets_explicit(self, tmp_path):
        """When mutation_targets is provided, runner calls mutation_tester."""
        # Create a simple source + test pair
        src = tmp_path / "widget.py"
        src.write_text(textwrap.dedent("""\
            def add(a, b):
                return a + b
        """))
        test = tmp_path / "test_widget.py"
        test.write_text(textwrap.dedent("""\
            from widget import add
            def test_add():
                assert add(1, 2) == 3
        """))

        results = runner.run_layer1(
            changed_files=["widget.py"],
            repo_root=str(tmp_path),
            mutation_targets=[("widget.py", "add", "test_widget.py")],
        )
        mutation_results = [r for r in results if r.tool == "mutation_tester"]
        assert len(mutation_results) >= 1
        assert all(isinstance(r, ToolEvidence) for r in mutation_results)

    def test_mutation_respects_max_mutations(self, tmp_path):
        """Runner should pass max_mutations budget to mutation_tester."""
        src = tmp_path / "calc.py"
        src.write_text(textwrap.dedent("""\
            def multiply(a, b):
                return a * b
            def subtract(a, b):
                return a - b
        """))
        test = tmp_path / "test_calc.py"
        test.write_text(textwrap.dedent("""\
            from calc import multiply, subtract
            def test_multiply():
                assert multiply(3, 4) == 12
            def test_subtract():
                assert subtract(5, 2) == 3
        """))

        results = runner.run_layer1(
            changed_files=["calc.py"],
            repo_root=str(tmp_path),
            mutation_targets=[("calc.py", "multiply", "test_calc.py")],
            max_mutations=2,
        )
        mutation_results = [r for r in results if r.tool == "mutation_tester"]
        assert len(mutation_results) >= 1
        # The detail should reflect the bounded mutation count
        for r in mutation_results:
            assert isinstance(r.detail, str)

    def test_mutation_auto_discovery(self, tmp_path):
        """When mutation_targets is None but test files exist, auto-discover."""
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        (src_dir / "foo.py").write_text("def bar(): return 1 + 2\n")

        test_dir = tmp_path / "tests"
        test_dir.mkdir()
        (test_dir / "test_foo.py").write_text(
            "from src.foo import bar\ndef test_bar():\n    assert bar() == 3\n"
        )

        results = runner.run_layer1(
            changed_files=["src/foo.py"],
            repo_root=str(tmp_path),
            # No explicit mutation_targets — should auto-discover
        )
        # Should attempt to find test_foo.py for foo.py
        tool_names = [r.tool for r in results]
        assert "mutation_tester" in tool_names


class TestRunnerBranchCoverageIntegration:
    """run_layer1() should wire branch_coverage with convention-based mapping."""

    def test_coverage_targets_explicit(self, tmp_path):
        """When coverage_targets is provided, runner calls branch_coverage."""
        src = tmp_path / "widget.py"
        src.write_text("def greet(name):\n    return f'hello {name}'\n")
        test = tmp_path / "test_widget.py"
        test.write_text(
            "from widget import greet\n"
            "def test_greet():\n    assert greet('x') == 'hello x'\n"
        )

        results = runner.run_layer1(
            changed_files=["widget.py"],
            repo_root=str(tmp_path),
            coverage_targets=[("widget.py", "test_widget.py")],
        )
        coverage_results = [r for r in results if r.tool == "branch_coverage"]
        assert len(coverage_results) >= 1
        assert all(isinstance(r, ToolEvidence) for r in coverage_results)

    def test_coverage_auto_pairs_by_convention(self, tmp_path):
        """When coverage_targets is None, auto-pair foo.py -> tests/test_foo.py."""
        (tmp_path / "helper.py").write_text("def x(): return 1\n")
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_helper.py").write_text(
            "from helper import x\ndef test_x():\n    assert x() == 1\n"
        )

        results = runner.run_layer1(
            changed_files=["helper.py"],
            repo_root=str(tmp_path),
        )
        tool_names = [r.tool for r in results]
        assert "branch_coverage" in tool_names

    def test_coverage_skipped_when_no_test_file(self, tmp_path):
        """When no test file found for a source file, skip branch_coverage."""
        (tmp_path / "orphan.py").write_text("def y(): return 2\n")

        results = runner.run_layer1(
            changed_files=["orphan.py"],
            repo_root=str(tmp_path),
        )
        coverage_results = [r for r in results if r.tool == "branch_coverage"]
        # Should not crash — either 0 results or a skip-evidence
        assert all(isinstance(r, ToolEvidence) for r in coverage_results)


class TestGetModifiedLines:
    """Test git diff modified line extraction helper."""

    def test_get_modified_lines_parses_hunks(self, monkeypatch):
        from aegis_core.verification.runner import _get_modified_lines
        import subprocess

        fake_diff = "@@ -10,0 +15,5 @@\n+line1\n+line2\n"
        def mock_run(cmd, *args, **kwargs):
            return subprocess.CompletedProcess(cmd, 0, stdout=fake_diff, stderr="")
        monkeypatch.setattr(subprocess, "run", mock_run)

        lines = _get_modified_lines("app.py", "/repo")
        assert lines == {15, 16, 17, 18, 19}

    def test_get_modified_lines_empty_when_no_hunks(self, monkeypatch):
        from aegis_core.verification.runner import _get_modified_lines
        import subprocess

        def mock_run(cmd, *args, **kwargs):
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
        monkeypatch.setattr(subprocess, "run", mock_run)

        assert _get_modified_lines("app.py", "/repo") is None

    def test_get_modified_lines_with_github_base_ref(self, monkeypatch):
        from aegis_core.verification.runner import _get_modified_lines
        import subprocess

        monkeypatch.setenv("GITHUB_BASE_REF", "develop")
        observed_cmds = []

        fake_diff = "@@ -20,0 +25,2 @@\n+line1\n+line2\n"
        def mock_run(cmd, *args, **kwargs):
            observed_cmds.append(cmd)
            if "origin/develop...HEAD" in cmd:
                return subprocess.CompletedProcess(cmd, 0, stdout=fake_diff, stderr="")
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        monkeypatch.setattr(subprocess, "run", mock_run)
        lines = _get_modified_lines("app.py", "/repo")
        assert lines == {25, 26}
        assert any("origin/develop...HEAD" in c for c in observed_cmds)

    def test_get_modified_lines_exception_handled(self, monkeypatch):
        from aegis_core.verification.runner import _get_modified_lines
        import subprocess

        def mock_run(cmd, *args, **kwargs):
            raise OSError("git error")
        monkeypatch.setattr(subprocess, "run", mock_run)

        assert _get_modified_lines("app.py", "/repo") is None


class TestRunnerCoverageEnhancements:
    """Tests for edge cases in runner.py discovery and mapping."""

    def test_find_test_file_runner_mapping(self):
        from aegis_core.verification.runner import _find_test_file
        test_file = _find_test_file("soma_core/verification/runner.py", REPO_ROOT)
        assert test_file is not None
        assert test_file.endswith("test_layer1.py")

        # Test decomposed domain mappings
        mcp_test = _find_test_file("soma_mcp/handlers/governance.py", REPO_ROOT)
        assert mcp_test is not None and mcp_test.endswith("test_mcp_handlers.py")

        harvest_test = _find_test_file("soma_core/outcomes/harvest.py", REPO_ROOT)
        assert harvest_test is not None and harvest_test.endswith("test_git_retro_harvest.py")

        insights_test = _find_test_file("soma_core/outcomes/insights.py", REPO_ROOT)
        assert insights_test is not None and insights_test.endswith("test_outcomes_insights.py")

        telemetry_test = _find_test_file("soma_core/outcomes/telemetry.py", REPO_ROOT)
        assert telemetry_test is not None and telemetry_test.endswith("test_outcomes_telemetry.py")

        engine_test = _find_test_file("soma_core/outcomes/engine.py", REPO_ROOT)
        assert engine_test is not None and engine_test.endswith("test_outcome_engine.py")

        skills_test = _find_test_file("soma_core/skills/graph.py", REPO_ROOT)
        assert skills_test is not None and skills_test.endswith("test_skills_and_handoff.py")

        slots_test = _find_test_file("soma_core/skills/slots.py", REPO_ROOT)
        assert slots_test is not None and slots_test.endswith("test_slots.py")

        artifacts_test = _find_test_file("soma_core/schemas/artifacts.py", REPO_ROOT)
        assert artifacts_test is not None and artifacts_test.endswith("test_skills_and_handoff.py")

    def test_discover_functions_with_target_lines(self, tmp_path):
        from aegis_core.verification.runner import _discover_functions
        code = textwrap.dedent("""\
            def func_a():
                return 1

            def func_b():
                return 2

            def func_c():
                return 3
        """)
        f = tmp_path / "module.py"
        f.write_text(code)

        # Lines 1-2 belong to func_a
        assert _discover_functions(str(f), target_lines={1, 2}) == ["func_a"]
        # Lines 4-5 belong to func_b
        assert _discover_functions(str(f), target_lines={5}) == ["func_b"]
        # No overlap
        assert _discover_functions(str(f), target_lines={100}) == []

    def test_runner_run_layer2_forwarding(self, tmp_path):
        """runner.run_layer2 emits DeprecationWarning and forwards to AdversarialVerifier + Arbiter."""
        import warnings
        from aegis_core.verification import runner, ToolEvidence, Verdict
        f = tmp_path / "mod.py"
        f.write_text("def work(): return 1\n")
        mock_backend = lambda p: "[]"
        with warnings.catch_warnings(record=True) as warns:
            warnings.simplefilter("always")
            res = runner.run_layer2(
                changed_files=["mod.py"],
                repo_root=str(tmp_path),
                task_plan="Plan",
                layer1_evidence=[ToolEvidence("call_graph", "mod.py", True, "ok")],
                llm_backend=mock_backend,
            )
        assert res.verdict == Verdict.SHIP
        assert any(issubclass(w.category, DeprecationWarning) for w in warns)

    def test_runner_run_layer2_empty_files_fallback(self, tmp_path):
        """runner.run_layer2 fallback ArbitrationResult when changed_files is empty."""
        from aegis_core.verification import runner, Verdict, ArbitrationResult
        res = runner.run_layer2(
            changed_files=[],
            repo_root=str(tmp_path),
            task_plan="Empty run",
            layer1_evidence=[],
            llm_backend=lambda p: "[]",
        )
        assert isinstance(res, ArbitrationResult)
        assert res.verdict == Verdict.SHIP

    def test_run_layer1_polyglot_call_graph(self, tmp_path):
        """run_layer1 invokes call_graph on polyglot files if a driver is resolved."""
        from aegis_core.verification import runner
        ts_file = tmp_path / "app.ts"
        ts_file.write_text("export function run() {}\n")

        with patch("aegis_core.ast.runner.ASTDriverRegistry.resolve_driver", return_value="node driver.js"), \
             patch("aegis_core.verification.call_graph.check") as mock_cg:
            mock_cg.return_value = ToolEvidence("call_graph", str(ts_file), True, "0 orphans")
            results = runner.run_layer1(
                changed_files=["app.ts"],
                repo_root=str(tmp_path),
                fast_mode=True,
            )
            assert mock_cg.called
            assert any(r.target == str(ts_file) for r in results)

    def test_get_modified_lines_uses_diff_base_and_head_fallback(self, tmp_path):
        """_get_modified_lines prioritizes explicit diff_base and falls back to HEAD~1."""
        from aegis_core.verification import runner
        import subprocess

        called_cmds = []
        def fake_run(cmd, *args, **kwargs):
            called_cmds.append(cmd)
            # Return hunk when HEAD~1 is queried
            if "HEAD~1" in cmd:
                return subprocess.CompletedProcess(cmd, 0, stdout="@@ -10,0 +11,5 @@\n", stderr="")
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        with patch("subprocess.run", side_effect=fake_run):
            lines = runner._get_modified_lines("foo.py", str(tmp_path))
            assert lines == {11, 12, 13, 14, 15}
            assert any("HEAD~1" in c for c in called_cmds)

        called_cmds.clear()
        def fake_run_diff_base(cmd, *args, **kwargs):
            called_cmds.append(cmd)
            if "origin/feat...HEAD" in cmd:
                return subprocess.CompletedProcess(cmd, 0, stdout="@@ -5,0 +6,2 @@\n", stderr="")
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        with patch("subprocess.run", side_effect=fake_run_diff_base):
            lines = runner._get_modified_lines("foo.py", str(tmp_path), diff_base="origin/feat")
            assert lines == {6, 7}
            assert called_cmds[0] == ["git", "diff", "-U0", "origin/feat", "--", "foo.py"]



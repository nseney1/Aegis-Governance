from pathlib import Path
"""TDD tests for branch_coverage.py — AUDITED ground truth.

Audit findings applied:
- test_returns_tool_evidence: strengthened with verdict + target + empty lines
- test_dead_branch_detected: asserts specific uncovered line ranges
- test_reports_uncovered_lines: asserts exact line 3, not just >= 2
- test_full_coverage_passes: asserts empty lines list
"""
import json
import os
import sys
import textwrap

import pytest

REPO_ROOT = str(next(p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").exists()))
sys.path.insert(0, REPO_ROOT)

from aegis_core.verification import ToolEvidence


class TestBranchCoverageContract:
    """Behavioral contract for branch_coverage.check()."""

    def test_returns_tool_evidence(self, tmp_path):
        """check() must return passing ToolEvidence for fully covered code."""
        from aegis_core.verification import branch_coverage

        src = tmp_path / "target.py"
        src.write_text(textwrap.dedent("""\
            def classify(x):
                if x > 0:
                    return "positive"
                else:
                    return "non-positive"
        """))

        test = tmp_path / "test_target.py"
        test.write_text(textwrap.dedent(f"""\
            import sys
            sys.path.insert(0, {str(tmp_path)!r})
            from target import classify
            def test_positive():
                assert classify(5) == "positive"
            def test_negative():
                assert classify(-1) == "non-positive"
        """))

        result = branch_coverage.check(
            target_file=str(src),
            test_file=str(test),
        )
        assert isinstance(result, ToolEvidence)
        assert result.tool == "branch_coverage"
        assert "target.py" in result.target
        assert result.verdict is True
        assert result.lines == []

    def test_full_coverage_passes(self, tmp_path):
        """When all branches are covered, verdict=True and no uncovered lines."""
        from aegis_core.verification import branch_coverage

        src = tmp_path / "target.py"
        src.write_text(textwrap.dedent("""\
            def classify(x):
                if x > 0:
                    return "positive"
                else:
                    return "non-positive"
        """))

        test = tmp_path / "test_target.py"
        test.write_text(textwrap.dedent(f"""\
            import sys
            sys.path.insert(0, {str(tmp_path)!r})
            from target import classify
            def test_positive():
                assert classify(5) == "positive"
            def test_negative():
                assert classify(-1) == "non-positive"
        """))

        result = branch_coverage.check(
            target_file=str(src),
            test_file=str(test),
        )
        assert result.verdict is True
        assert result.lines == []

    def test_dead_branch_detected(self, tmp_path):
        """Uncovered branches must produce verdict=False with specific lines."""
        from aegis_core.verification import branch_coverage

        src = tmp_path / "target.py"
        src.write_text(textwrap.dedent("""\
            def classify(x):
                if x > 0:
                    return "positive"
                elif x == 0:
                    return "zero"
                else:
                    return "negative"
        """))

        # Only tests positive — misses zero and negative branches
        test = tmp_path / "test_target.py"
        test.write_text(textwrap.dedent(f"""\
            import sys
            sys.path.insert(0, {str(tmp_path)!r})
            from target import classify
            def test_positive():
                assert classify(5) == "positive"
        """))

        result = branch_coverage.check(
            target_file=str(src),
            test_file=str(test),
        )
        assert result.verdict is False
        # Lines 4-7 (elif/else branches) should be uncovered
        assert any(line in (4, 5, 6, 7) for line in result.lines), \
            f"Expected uncovered branch lines 4-7, got {result.lines}"
        # Line 3 (return "positive") was executed and must NOT be flagged
        assert 3 not in result.lines, \
            f"Covered line 3 was incorrectly flagged: {result.lines}"

    def test_reports_uncovered_lines(self, tmp_path):
        """Result must include the specific uncovered line number."""
        from aegis_core.verification import branch_coverage

        src = tmp_path / "target.py"
        src.write_text(textwrap.dedent("""\
            def process(x):
                if x > 10:
                    return "big"
                return "small"
        """))

        # Only tests small path
        test = tmp_path / "test_target.py"
        test.write_text(textwrap.dedent(f"""\
            import sys
            sys.path.insert(0, {str(tmp_path)!r})
            from target import process
            def test_small():
                assert process(5) == "small"
        """))

        result = branch_coverage.check(
            target_file=str(src),
            test_file=str(test),
        )
        assert result.verdict is False
        # Line 3 (return "big") should be uncovered
        assert 3 in result.lines, \
            f"Expected line 3 (return 'big') in uncovered lines, got {result.lines}"
        # Line 4 (return "small") was executed
        assert 4 not in result.lines, \
            f"Line 4 was executed and must not be in uncovered lines: {result.lines}"


class TestParseCoverageMissingBranches:
    """Fix 2.1a: _parse_coverage must merge missing_branches into results."""

    def test_parse_coverage_includes_missing_branches(self, tmp_path):
        """missing_branches entries should appear in the returned line list."""
        from aegis_core.verification.branch_coverage import _parse_coverage

        # Build a mock coverage JSON with both missing_lines and missing_branches
        report = tmp_path / "coverage.json"
        report.write_text(json.dumps({
            "files": {
                "/src/target.py": {
                    "missing_lines": [10, 15],
                    "missing_branches": [
                        [8, 12],   # branch from line 8 to 12
                        [14, 20],  # branch from line 14 to 20
                        [3, 15],   # to_line 15 already in missing_lines — no dup
                    ],
                }
            }
        }))

        result = _parse_coverage(str(report), "/src/target.py", "target.py")

        # Original missing_lines must be present
        assert 10 in result
        assert 15 in result
        # Branch targets must be merged in
        assert 12 in result, f"Branch target 12 missing from {result}"
        assert 20 in result, f"Branch target 20 missing from {result}"
        # No duplicates for line 15
        assert result.count(15) == 1, f"Duplicate line 15 in {result}"

    def test_parse_coverage_branches_only(self, tmp_path):
        """When missing_lines is empty, branches alone should populate result."""
        from aegis_core.verification.branch_coverage import _parse_coverage

        report = tmp_path / "coverage.json"
        report.write_text(json.dumps({
            "files": {
                "/src/foo.py": {
                    "missing_lines": [],
                    "missing_branches": [[5, 7]],
                }
            }
        }))

        result = _parse_coverage(str(report), "/src/foo.py", "foo.py")
        assert 7 in result
        assert len(result) == 1


class TestSubprocessTimeout:
    """Fix 2.1b: TimeoutExpired must be caught, not crash."""

    def test_subprocess_timeout_returns_false(self, monkeypatch):
        """_try_pytest_cov must return False on TimeoutExpired, not raise."""
        import subprocess as sp
        from aegis_core.verification.branch_coverage import _try_pytest_cov

        def mock_run(*args, **kwargs):
            raise sp.TimeoutExpired(cmd="pytest", timeout=120)

        monkeypatch.setattr(sp, "run", mock_run)

        result = _try_pytest_cov("test.py", "/src", "/tmp/report.json")
        assert result is False

    def test_coverage_module_timeout_returns_false(self, monkeypatch):
        """_try_coverage_module must return False on TimeoutExpired."""
        import subprocess as sp
        from aegis_core.verification.branch_coverage import _try_coverage_module

        def mock_run(*args, **kwargs):
            raise sp.TimeoutExpired(cmd="coverage", timeout=120)

        monkeypatch.setattr(sp, "run", mock_run)

        result = _try_coverage_module("test.py", "/src", "/tmp/report.json", "/tmp")
        assert result is False


class TestBranchCoverageTargetLines:
    """Test target_lines parameter on branch_coverage.check()."""

    def test_target_lines_filters_uncovered_lines(self, tmp_path):
        from aegis_core.verification import branch_coverage

        src = tmp_path / "mod.py"
        src.write_text("def a():\n    return 1\ndef b():\n    return 2\n")

        test = tmp_path / "test_mod.py"
        test.write_text("from mod import a\ndef test_a(): assert a() == 1\n")

        # When target_lines only specifies lines 1-2 (def a), b is ignored
        res = branch_coverage.check(str(src), str(test), target_lines={1, 2})
        assert res.verdict is True
        assert res.lines == []

        # When target_lines specifies line 4 (return 2 in b), it fails
        res_b = branch_coverage.check(str(src), str(test), target_lines={4})
        assert res_b.verdict is False
        assert 4 in res_b.lines


class TestBranchCoverageFilteringAndFallback:
    """Test branch target filtering and stdlib trace fallback."""

    def test_parse_coverage_filters_negative_and_backward_branches(self, tmp_path):
        from aegis_core.verification.branch_coverage import _parse_coverage

        report = tmp_path / "coverage.json"
        report.write_text(json.dumps({
            "files": {
                "/src/target.py": {
                    "missing_lines": [],
                    "executed_lines": [32],
                    "missing_branches": [
                        [10, -5],  # Negative exit line -> filtered
                        [20, 15],  # Backward loop jump (15 <= 20) -> filtered
                        [25, 25],  # Same line jump -> filtered
                        [28, 32],  # Forward branch target that already executed -> filtered
                        [30, 35],  # Valid forward jump to unexecuted statement -> kept
                    ],
                }
            }
        }))

        missing = _parse_coverage(str(report), "/src/target.py", "target.py")
        assert missing == [35]

    def test_run_trace_fallback_execution(self, tmp_path):
        from aegis_core.verification.branch_coverage import _run_trace_fallback

        src = tmp_path / "calc.py"
        src.write_text("def add(a, b):\n    return a + b\n")

        test = tmp_path / "test_calc.py"
        test.write_text(f"import sys\nsys.path.insert(0, {str(tmp_path)!r})\nfrom calc import add\ndef test_add(): assert add(1, 2) == 3\n")

        missing = _run_trace_fallback(str(test), str(src), str(tmp_path), str(tmp_path))
        assert missing == []

    def test_parse_coverage_filters_jump_tokens_and_handles_walk(self, tmp_path, monkeypatch):
        from aegis_core.verification.branch_coverage import _parse_coverage

        sub = tmp_path / "sub"
        sub.mkdir(parents=True)
        src = sub / "worker.py"
        src.write_text("a = 1\nbreak\ncontinue\npass\nb = 2\n")

        report = tmp_path / "coverage.json"
        report.write_text(json.dumps({
            "files": {
                "worker.py": {
                    "missing_lines": [2, 3, 5],  # 2 (break), 3 (continue), 5 (b=2)
                    "missing_branches": [
                        [1, 4],  # jump to line 4 (pass) -> filtered
                    ],
                }
            }
        }))

        monkeypatch.chdir(tmp_path)
        missing = _parse_coverage(str(report), "not_found/worker.py", "worker.py")
        assert missing == [5]

    def test_parse_coverage_open_exception_handled(self, tmp_path, monkeypatch):
        from aegis_core.verification.branch_coverage import _parse_coverage

        src = tmp_path / "unreadable.py"
        src.write_text("x = 1\n")
        report = tmp_path / "coverage.json"
        report.write_text(json.dumps({
            "files": {
                str(src): {
                    "missing_lines": [1],
                    "missing_branches": [],
                }
            }
        }))

        orig_open = open
        def mock_open(file, *args, **kwargs):
            if str(file) == str(src):
                raise OSError("unreadable")
            return orig_open(file, *args, **kwargs)

        monkeypatch.setattr("builtins.open", mock_open)
        missing = _parse_coverage(str(report), str(src), "unreadable.py")
        assert missing == [1]




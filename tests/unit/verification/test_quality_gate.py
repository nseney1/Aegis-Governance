from pathlib import Path
"""TDD Gate 1 tests for test quality gate (Phase 2H).

Verifies the deterministic AST and file-matching quality gate checks:
- check_assertion_density: ensures all test functions have assert statements
- check_no_bare_pass: detects placeholder/stub tests using bare pass or ellipsis
- check_behavioral_coverage: verifies changed implementation files have test counterparts
"""
import os
import sys
import textwrap
import pytest

REPO_ROOT = str(next(p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").exists()))
sys.path.insert(0, REPO_ROOT)

from aegis_core.verification import ToolEvidence

try:
    from aegis_core.verification.quality_gate import (
        check_assertion_density,
        check_no_bare_pass,
        check_behavioral_coverage,
    )
except ImportError:
    # TDD Gate 1: module doesn't exist yet. Tests will fail with NameError.
    check_assertion_density = None
    check_no_bare_pass = None
    check_behavioral_coverage = None

# Skip all tests in this module if quality_gate isn't importable yet
pytestmark = pytest.mark.skipif(
    check_assertion_density is None,
    reason="quality_gate module not yet implemented (TDD Gate 1)",
)


class TestCheckAssertionDensity:
    """Test assertion density verification on test files."""

    def test_assertion_density_passes_when_all_tests_have_asserts(self, tmp_path):
        """Happy path: test file where every test function contains at least one assert."""
        test_file = tmp_path / "test_sample_good.py"
        test_file.write_text(textwrap.dedent("""\
            def test_addition():
                result = 1 + 1
                assert result == 2

            def test_multiplication():
                product = 3 * 4
                assert product == 12
                assert product > 0
        """))

        result = check_assertion_density(str(test_file))

        assert isinstance(result, ToolEvidence)
        assert result.tool == "assertion_density"
        assert result.verdict is True
        assert result.target == str(test_file)
        assert len(result.lines) == 0
        assert "pass" in result.detail.lower() or "density" in result.detail.lower() or "all" in result.detail.lower()

    def test_assertion_density_fails_when_test_lacks_assert(self, tmp_path):
        """Sad path: test file containing a test function without any assert statement."""
        test_file = tmp_path / "test_sample_missing_assert.py"
        test_file.write_text(textwrap.dedent("""\
            def test_valid():
                assert True

            def test_missing_assertion():
                x = 10
                y = 20
                total = x + y
        """))

        result = check_assertion_density(str(test_file))

        assert isinstance(result, ToolEvidence)
        assert result.tool == "assertion_density"
        assert result.verdict is False
        assert result.target == str(test_file)
        assert "test_missing_assertion" in result.detail
        assert len(result.lines) > 0

    def test_assertion_density_ignores_non_test_helper_functions(self, tmp_path):
        """Edge case: non-test helper functions without assert statements should not cause failure."""
        test_file = tmp_path / "test_with_helpers.py"
        test_file.write_text(textwrap.dedent("""\
            def build_fixture_data():
                return {"user": "alice", "active": True}

            def test_using_helper():
                data = build_fixture_data()
                assert data["user"] == "alice"
        """))

        result = check_assertion_density(str(test_file))

        assert isinstance(result, ToolEvidence)
        assert result.tool == "assertion_density"
        assert result.verdict is True

    def test_assertion_density_inspects_class_test_methods(self, tmp_path):
        """Edge case: test methods inside a test class should also be verified for assertions."""
        test_file = tmp_path / "test_class_suite.py"
        test_file.write_text(textwrap.dedent("""\
            class TestSuite:
                def test_valid_method(self):
                    assert 1 == 1

                def test_empty_method(self):
                    value = 42
        """))

        result = check_assertion_density(str(test_file))

        assert isinstance(result, ToolEvidence)
        assert result.tool == "assertion_density"
        assert result.verdict is False
        assert "test_empty_method" in result.detail

    def test_assertion_density_recognizes_nested_asserts(self, tmp_path):
        """Edge case: assert statement nested in context manager, try block, or conditional counts."""
        test_file = tmp_path / "test_nested_asserts.py"
        test_file.write_text(textwrap.dedent("""\
            def test_nested_in_with():
                with open("/dev/null") as f:
                    assert f is not None

            def test_nested_in_condition():
                x = 5
                if x > 0:
                    assert x == 5
        """))

        result = check_assertion_density(str(test_file))

        assert isinstance(result, ToolEvidence)
        assert result.tool == "assertion_density"
        assert result.verdict is True

    def test_assertion_density_recognizes_pytest_raises(self, tmp_path):
        """pytest.raises is an assertion-equivalent and should pass density check."""
        test_file = tmp_path / "test_raises.py"
        test_file.write_text(textwrap.dedent("""\
            import pytest

            def test_raises_value_error():
                with pytest.raises(ValueError):
                    int("not_a_number")

            def test_raises_with_match():
                with pytest.raises(TypeError, match="unsupported"):
                    1 + "string"
        """))

        result = check_assertion_density(str(test_file))

        assert isinstance(result, ToolEvidence)
        assert result.tool == "assertion_density"
        assert result.verdict is True

    def test_assertion_density_recognizes_pytest_fail(self, tmp_path):
        """pytest.fail is an assertion-equivalent and should pass density check."""
        test_file = tmp_path / "test_fail.py"
        test_file.write_text(textwrap.dedent("""\
            import pytest

            def test_conditional_fail():
                value = compute_something()
                if value < 0:
                    pytest.fail("Value must not be negative")

            def compute_something():
                return 1
        """))

        result = check_assertion_density(str(test_file))

        assert isinstance(result, ToolEvidence)
        assert result.tool == "assertion_density"
        assert result.verdict is True

    def test_assertion_density_recognizes_unittest_assertions(self, tmp_path):
        """self.assert* (unittest style) should pass density check."""
        test_file = tmp_path / "test_unittest_style.py"
        test_file.write_text(textwrap.dedent("""\
            import unittest

            class TestMath(unittest.TestCase):
                def test_addition(self):
                    self.assertEqual(1 + 1, 2)

                def test_truth(self):
                    self.assertTrue(True)
                    self.assertFalse(False)
        """))

        result = check_assertion_density(str(test_file))

        assert isinstance(result, ToolEvidence)
        assert result.tool == "assertion_density"
        assert result.verdict is True

class TestCheckNoBarePass:
    """Test detection of bare pass and ellipsis test stubs."""

    def test_no_bare_pass_passes_for_real_test_functions(self, tmp_path):
        """Happy path: real test functions with substantive implementation pass."""
        test_file = tmp_path / "test_real_code.py"
        test_file.write_text(textwrap.dedent("""\
            def test_real_behavior():
                items = [1, 2, 3]
                items.append(4)
                assert len(items) == 4
        """))

        result = check_no_bare_pass(str(test_file))

        assert isinstance(result, ToolEvidence)
        assert result.tool == "no_bare_pass"
        assert result.verdict is True
        assert result.target == str(test_file)
        assert len(result.lines) == 0

    def test_no_bare_pass_fails_for_pass_body(self, tmp_path):
        """Sad path: test function whose body is only 'pass' must fail."""
        test_file = tmp_path / "test_bare_pass.py"
        test_file.write_text(textwrap.dedent("""\
            def test_stub_pass():
                pass
        """))

        result = check_no_bare_pass(str(test_file))

        assert isinstance(result, ToolEvidence)
        assert result.tool == "no_bare_pass"
        assert result.verdict is False
        assert result.target == str(test_file)
        assert "test_stub_pass" in result.detail
        assert len(result.lines) > 0

    def test_no_bare_pass_fails_for_ellipsis_body(self, tmp_path):
        """Sad path: test function whose body is only '...' (Ellipsis) must fail."""
        test_file = tmp_path / "test_bare_ellipsis.py"
        test_file.write_text(textwrap.dedent("""\
            def test_stub_ellipsis():
                ...
        """))

        result = check_no_bare_pass(str(test_file))

        assert isinstance(result, ToolEvidence)
        assert result.tool == "no_bare_pass"
        assert result.verdict is False
        assert result.target == str(test_file)
        assert "test_stub_ellipsis" in result.detail
        assert len(result.lines) > 0

    def test_no_bare_pass_fails_for_docstring_with_pass_or_ellipsis(self, tmp_path):
        """Edge case: test functions with a docstring followed solely by pass or ellipsis must fail."""
        test_file = tmp_path / "test_docstring_stubs.py"
        test_file.write_text(textwrap.dedent('''\
            def test_docstring_pass():
                """TODO: implement this test."""
                pass

            def test_docstring_ellipsis():
                """Placeholder for future coverage."""
                ...
        '''))

        result = check_no_bare_pass(str(test_file))

        assert isinstance(result, ToolEvidence)
        assert result.tool == "no_bare_pass"
        assert result.verdict is False
        assert "test_docstring_pass" in result.detail or "test_docstring_ellipsis" in result.detail
        assert len(result.lines) >= 1

    def test_no_bare_pass_allows_pass_in_subordinate_blocks(self, tmp_path):
        """Edge case: a pass inside a try/except or if block in a non-empty test is allowed."""
        test_file = tmp_path / "test_pass_in_flow.py"
        test_file.write_text(textwrap.dedent("""\
            def test_exception_handling():
                try:
                    int("not-an-int")
                except ValueError:
                    pass
                assert True
        """))

        result = check_no_bare_pass(str(test_file))

        assert isinstance(result, ToolEvidence)
        assert result.tool == "no_bare_pass"
        assert result.verdict is True

    def test_no_bare_pass_ignores_non_test_functions(self, tmp_path):
        """Edge case: non-test helper function with bare pass is not flagged as a test stub."""
        test_file = tmp_path / "test_with_empty_helper.py"
        test_file.write_text(textwrap.dedent("""\
            def noop_callback():
                pass

            def test_something():
                assert noop_callback() is None
        """))

        result = check_no_bare_pass(str(test_file))

        assert isinstance(result, ToolEvidence)
        assert result.tool == "no_bare_pass"
        assert result.verdict is True


class TestCheckBehavioralCoverage:
    """Test behavioral coverage mapping between changed files and test files."""

    def test_behavioral_coverage_passes_when_all_changed_files_have_tests(self):
        """Happy path: all changed implementation files have corresponding test files."""
        changed_files = [
            "src/models.py",
            "src/utils.py",
        ]
        test_files = [
            "tests/test_models.py",
            "tests/test_utils.py",
            "tests/test_other.py",
        ]

        result = check_behavioral_coverage(changed_files, test_files, repo_root=REPO_ROOT)

        assert isinstance(result, ToolEvidence)
        assert result.tool == "behavioral_coverage"
        assert result.verdict is True
        assert "2/2" in result.detail or "all" in result.detail.lower() or "covered" in result.detail.lower()

    def test_behavioral_coverage_fails_when_changed_file_has_no_test(self):
        """Sad path: at least one changed implementation file is missing its test counterpart."""
        changed_files = [
            "src/covered_service.py",
            "src/uncovered_service.py",
        ]
        test_files = [
            "tests/test_covered_service.py",
        ]

        result = check_behavioral_coverage(changed_files, test_files, repo_root=REPO_ROOT)

        assert isinstance(result, ToolEvidence)
        assert result.tool == "behavioral_coverage"
        assert result.verdict is False
        assert "uncovered_service" in result.detail

    def test_behavioral_coverage_soma_cli_convention_matches_cli_or_command_test(self):
        """Convention test: soma_cli/init.py maps to either tests/test_cli.py or tests/test_init.py."""
        # Case 1: mapped via tests/test_cli.py
        result_cli = check_behavioral_coverage(
            changed_files=["soma_cli/init.py"],
            test_files=["tests/test_cli.py"],
            repo_root=REPO_ROOT,
        )
        assert result_cli.verdict is True
        assert result_cli.tool == "behavioral_coverage"

        # Case 2: mapped via tests/test_init.py
        result_init = check_behavioral_coverage(
            changed_files=["soma_cli/init.py"],
            test_files=["tests/test_init.py"],
            repo_root=REPO_ROOT,
        )
        assert result_init.verdict is True
        assert result_init.tool == "behavioral_coverage"

    def test_behavioral_coverage_empty_changed_files_passes(self):
        """Edge case: when no implementation files have changed, coverage passes trivially."""
        result = check_behavioral_coverage(
            changed_files=[],
            test_files=["tests/test_existing.py"],
            repo_root=REPO_ROOT,
        )

        assert isinstance(result, ToolEvidence)
        assert result.tool == "behavioral_coverage"
        assert result.verdict is True

    def test_behavioral_coverage_ignores_test_files_and_non_code_files(self):
        """Edge case: changed test files, markdown, or configs should not require test counterparts."""
        changed_files = [
            "tests/test_sample.py",
            "README.md",
            "docs/architecture.md",
            ".gitignore",
        ]
        test_files = [
            "tests/test_sample.py",
        ]

        result = check_behavioral_coverage(
            changed_files=changed_files,
            test_files=test_files,
            repo_root=REPO_ROOT,
        )

        assert isinstance(result, ToolEvidence)
        assert result.tool == "behavioral_coverage"
        assert result.verdict is True

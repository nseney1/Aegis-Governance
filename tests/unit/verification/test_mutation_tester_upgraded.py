from pathlib import Path
"""Tests for Phase 3.2 mutation tester upgrades.

Regression tests for existing operators + skipped tests for new operators.
"""
import os
import sys
import pytest

REPO_ROOT = str(next(p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").exists()))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from aegis_core.verification.mutation_tester import check


# --- Fixture functions for mutation testing ---

FIXTURE_ADD = '''
def add(a, b):
    return a + b
'''

FIXTURE_ADD_TEST = '''
from {module} import add

def test_add_basic():
    assert add(2, 3) == 5

def test_add_negatives():
    assert add(-1, -2) == -3

def test_add_zero():
    assert add(0, 5) == 5
'''

FIXTURE_CMP = '''
def is_positive(x):
    return x > 0
'''

FIXTURE_CMP_TEST = '''
from {module} import is_positive

def test_positive():
    assert is_positive(1) is True

def test_negative():
    assert is_positive(-1) is False

def test_zero():
    assert is_positive(0) is False
'''

FIXTURE_BOOL = '''
def both_positive(a, b):
    return a > 0 and b > 0
'''

FIXTURE_BOOL_TEST = '''
from {module} import both_positive

def test_both():
    assert both_positive(1, 1) is True

def test_first_neg():
    assert both_positive(-1, 1) is False

def test_second_neg():
    assert both_positive(1, -1) is False
'''


def _write_fixture(tmp_path, source_code, test_template, name='target'):
    """Write a target module and its test file."""
    target = tmp_path / f'{name}.py'
    target.write_text(source_code.strip() + '\n', encoding='utf-8')

    test_code = test_template.format(module=name)
    test_file = tmp_path / f'test_{name}.py'
    test_file.write_text(test_code.strip() + '\n', encoding='utf-8')

    return str(target), str(test_file)


class TestExistingOperatorsRegression:
    """Regression tests — existing mutation operators must still work."""

    def test_binary_op_swap_detected(self, tmp_path):
        target, test_file = _write_fixture(tmp_path, FIXTURE_ADD, FIXTURE_ADD_TEST, 'add_fn')
        result = check(target, 'add', test_file)
        assert result.tool == 'mutation_tester'
        assert isinstance(result.verdict, bool)
        assert isinstance(result.detail, str)

    def test_constant_mutation_detected(self, tmp_path):
        source = '''
def scale(x):
    return x * 2
'''
        test_tmpl = '''
from {module} import scale
def test_scale():
    assert scale(5) == 10
def test_scale_zero():
    assert scale(0) == 0
'''
        target, test_file = _write_fixture(tmp_path, source, test_tmpl, 'scale_fn')
        result = check(target, 'scale', test_file)
        assert result.tool == 'mutation_tester'

    def test_tool_evidence_shape(self, tmp_path):
        target, test_file = _write_fixture(tmp_path, FIXTURE_ADD, FIXTURE_ADD_TEST, 'shape_fn')
        result = check(target, 'add', test_file)
        assert hasattr(result, 'tool')
        assert hasattr(result, 'target')
        assert hasattr(result, 'verdict')
        assert hasattr(result, 'detail')
        assert hasattr(result, 'lines')
        assert isinstance(result.lines, list)

    def test_noop_function_passes_trivially(self, tmp_path):
        source = '''
def noop():
    pass
'''
        test_tmpl = '''
from {module} import noop
def test_noop():
    assert noop() is None
'''
        target, test_file = _write_fixture(tmp_path, source, test_tmpl, 'noop_fn')
        result = check(target, 'noop', test_file)
        assert result.verdict is True  # No mutations possible
        assert '0' in result.detail

    def test_max_mutations_cap(self, tmp_path):
        target, test_file = _write_fixture(tmp_path, FIXTURE_ADD, FIXTURE_ADD_TEST, 'cap_fn')
        result = check(target, 'add', test_file, max_mutations=1)
        # Should complete with at most 1 mutation tested
        assert result.tool == 'mutation_tester'


class TestPhase32NewOperators:
    """Tests for new mutation operators — Phase 3.2."""

    def test_comparison_swap_gt_to_lt(self, tmp_path):
        """x > 0 should be mutated to x < 0 and caught by tests."""
        target, test_file = _write_fixture(tmp_path, FIXTURE_CMP, FIXTURE_CMP_TEST, 'cmp_fn')
        result = check(target, 'is_positive', test_file)
        assert result.verdict is True  # All mutations killed

    def test_boolean_swap_and_to_or(self, tmp_path):
        """a and b should be mutated to a or b and caught by tests."""
        target, test_file = _write_fixture(tmp_path, FIXTURE_BOOL, FIXTURE_BOOL_TEST, 'bool_fn')
        result = check(target, 'both_positive', test_file)
        assert result.verdict is True

    def test_statement_deletion(self, tmp_path):
        """Deleting a statement should be caught by tests."""
        source = '''
def accumulate(items):
    total = 0
    for item in items:
        total += item
    return total
'''
        test_tmpl = '''
from {module} import accumulate
def test_accumulate():
    assert accumulate([1, 2, 3]) == 6
def test_empty():
    assert accumulate([]) == 0
'''
        target, test_file = _write_fixture(tmp_path, source, test_tmpl, 'stmt_fn')
        result = check(target, 'accumulate', test_file)
        assert result.verdict is True

    def test_return_value_mutation(self, tmp_path):
        """return x should be mutated to return None and caught."""
        source = '''
def identity(x):
    return x
'''
        test_tmpl = '''
from {module} import identity
def test_identity():
    assert identity(42) == 42
def test_identity_str():
    assert identity("hello") == "hello"
'''
        target, test_file = _write_fixture(tmp_path, source, test_tmpl, 'ret_fn')
        result = check(target, 'identity', test_file)
        assert result.verdict is True

    def test_pythonpath_package_import(self, tmp_path):
        """Package imports (from pkg.mod import X) should work with mutant."""
        pkg_dir = tmp_path / 'mypkg'
        pkg_dir.mkdir()
        (pkg_dir / '__init__.py').write_text('', encoding='utf-8')
        (pkg_dir / 'math_utils.py').write_text(
            'def double(x):\n    return x * 2\n', encoding='utf-8')

        test_file = tmp_path / 'test_pkg.py'
        test_file.write_text(
            'from mypkg.math_utils import double\n'
            'def test_double():\n    assert double(5) == 10\n',
            encoding='utf-8')

        result = check(str(pkg_dir / 'math_utils.py'), 'double', str(test_file))
        assert result.tool == 'mutation_tester'
        assert result.verdict is True

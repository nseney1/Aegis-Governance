from pathlib import Path
"""Behavioral tests for typed exception hierarchy in aegis_sdk.errors.

Verifies that all soma error types follow the correct inheritance chain
and that public APIs raise the correct exception types.
"""
import os
import sys
import pytest

REPO_ROOT = str(next(p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").exists()))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from aegis_sdk.errors import (
    AegisError,
    RuleParseError,
    RuleNotFoundError,
    RulePathTraversalError,
    FitnessError,
    ScoringError,
)
from aegis_sdk.rules import parse_rule_file, load_rule, _sanitize_cell_id


class TestErrorHierarchy:
    """Verify exception inheritance chain."""

    def test_cell_parse_error_is_soma_error(self):
        assert issubclass(RuleParseError, AegisError)

    def test_cell_not_found_error_is_soma_error(self):
        assert issubclass(RuleNotFoundError, AegisError)

    def test_cell_path_traversal_error_is_soma_error(self):
        assert issubclass(RulePathTraversalError, AegisError)

    def test_fitness_error_is_soma_error(self):
        assert issubclass(FitnessError, AegisError)

    def test_scoring_error_is_soma_error(self):
        assert issubclass(ScoringError, AegisError)

    def test_soma_error_is_exception(self):
        assert issubclass(AegisError, Exception)


class TestParseErrors:
    """Verify parse_rule_file raises RuleParseError on invalid input."""

    def test_truncated_yaml_raises_cell_parse_error(self, tmp_path):
        bad_file = tmp_path / 'truncated.md'
        bad_file.write_text('---\nid: test\ntype:', encoding='utf-8')
        with pytest.raises(RuleParseError):
            parse_rule_file(str(bad_file))

    def test_missing_frontmatter_raises_cell_parse_error(self, tmp_path):
        bad_file = tmp_path / 'no_frontmatter.md'
        bad_file.write_text('Just plain text, no YAML', encoding='utf-8')
        with pytest.raises(RuleParseError):
            parse_rule_file(str(bad_file))

    def test_invalid_yaml_raises_cell_parse_error(self, tmp_path):
        bad_file = tmp_path / 'invalid.md'
        bad_file.write_text('---\n: : invalid: [yaml\n---\nBody', encoding='utf-8')
        with pytest.raises(RuleParseError):
            parse_rule_file(str(bad_file))


class TestPathTraversal:
    """Verify path traversal attacks are caught."""

    def test_load_cell_traversal_raises(self, tmp_path):
        cells_dir = str(tmp_path / '.aegis' / 'rules')
        with pytest.raises(RulePathTraversalError):
            load_rule('../../etc/passwd', cells_dir=cells_dir)

    def test_sanitize_cell_id_traversal_raises(self):
        with pytest.raises(RulePathTraversalError):
            _sanitize_cell_id('../etc/passwd')

    def test_sanitize_cell_id_double_dot_raises(self):
        with pytest.raises(RulePathTraversalError):
            _sanitize_cell_id('..\\etc\\passwd')

    def test_valid_cell_id_passes_sanitize(self):
        # Should not raise
        result = _sanitize_cell_id('my-valid-cell-id')
        assert result == 'my-valid-cell-id'

"""Rule-file errors: parse_rule_file raises typed AegisError subclasses (aegis_core.errors)."""
from __future__ import annotations

import pytest

from aegis_core.errors import AegisError, RuleNotFoundError, RuleParseError
from aegis_core.yaml_engine.frontmatter import parse_rule_file


class TestErrorHierarchy:
    @pytest.mark.parametrize("error", [RuleParseError, RuleNotFoundError])
    def test_rule_errors_are_aegis_errors(self, error):
        assert issubclass(error, AegisError)
        assert issubclass(AegisError, Exception)


class TestParseErrors:
    """parse_rule_file raises RuleParseError on invalid input."""

    def test_truncated_yaml_raises_rule_parse_error(self, tmp_path):
        bad_file = tmp_path / 'truncated.md'
        bad_file.write_text('---\nid: test\ntype:', encoding='utf-8')
        with pytest.raises(RuleParseError):
            parse_rule_file(str(bad_file))

    def test_missing_frontmatter_raises_rule_parse_error(self, tmp_path):
        bad_file = tmp_path / 'no_frontmatter.md'
        bad_file.write_text('Just plain text, no YAML', encoding='utf-8')
        with pytest.raises(RuleParseError, match="No frontmatter delimiter"):
            parse_rule_file(str(bad_file))

    def test_invalid_yaml_raises_rule_parse_error(self, tmp_path):
        bad_file = tmp_path / 'invalid.md'
        bad_file.write_text('---\n: : invalid: [yaml\n---\nBody', encoding='utf-8')
        with pytest.raises(RuleParseError):
            parse_rule_file(str(bad_file))

    def test_missing_file_raises_rule_not_found(self, tmp_path):
        with pytest.raises(RuleNotFoundError, match="Rule file not found"):
            parse_rule_file(str(tmp_path / "absent.md"))

    def test_a_directory_is_not_a_rule_file(self, tmp_path):
        with pytest.raises(RuleNotFoundError):
            parse_rule_file(str(tmp_path))

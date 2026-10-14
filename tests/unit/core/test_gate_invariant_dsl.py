"""Phase 4.2a — Gate invariant DSL behavioral tests.

Tests verify that cells can declare invariants in frontmatter and that the
invariant checker correctly evaluates them against source files.
"""
import ast
import os
import pytest
from textwrap import dedent


# ---------------------------------------------------------------------------
# Phase 4.2a: import_banned invariant
# ---------------------------------------------------------------------------

class TestImportBanned:
    """The import_banned invariant detects banned import patterns via AST."""

    def test_catches_violation(self, tmp_path):
        """A file with a banned import triggers a violation."""
        source = tmp_path / 'bad.py'
        source.write_text('from aegis_sdk.cells import *\n', encoding='utf-8')
        from aegis_sdk.invariants import check_import_banned
        violation = check_import_banned(
            pattern='from aegis_sdk.* import *',
            file_path=str(source)
        )
        assert violation is not None
        assert 'aegis_sdk' in violation.message

    def test_allows_compliant(self, tmp_path):
        """A file with a specific named import (not wildcard *) passes clean."""
        source = tmp_path / 'good.py'
        source.write_text('from aegis_sdk.cells import parse_cell_file\n',
                          encoding='utf-8')
        from aegis_sdk.invariants import check_import_banned
        violation = check_import_banned(
            pattern='from os.* import *',
            file_path=str(source)
        )
        assert violation is None

    def test_non_python_file_skipped(self, tmp_path):
        """Non-Python files are silently skipped."""
        source = tmp_path / 'data.json'
        source.write_text('{"key": "value"}', encoding='utf-8')
        from aegis_sdk.invariants import check_import_banned
        violation = check_import_banned(
            pattern='from aegis_sdk.* import *',
            file_path=str(source)
        )
        assert violation is None

    def test_syntax_error_file_skipped(self, tmp_path):
        """Files with syntax errors don't crash the checker."""
        source = tmp_path / 'broken.py'
        source.write_text('def foo(\n', encoding='utf-8')
        from aegis_sdk.invariants import check_import_banned
        violation = check_import_banned(
            pattern='from aegis_sdk.* import *',
            file_path=str(source)
        )
        assert violation is None


# ---------------------------------------------------------------------------
# Phase 4.2b: file_must_exist invariant
# ---------------------------------------------------------------------------

class TestFileMustExist:
    """The file_must_exist invariant checks that required companion files exist."""

    def test_catches_missing(self, tmp_path):
        """Missing test file triggers violation."""
        from aegis_sdk.invariants import check_file_must_exist
        violation = check_file_must_exist(
            path_pattern='tests/test_foo.py',
            workspace=str(tmp_path)
        )
        assert violation is not None
        assert 'test_foo.py' in violation.message

    def test_allows_existing(self, tmp_path):
        """Existing file passes clean."""
        (tmp_path / 'tests').mkdir()
        (tmp_path / 'tests' / 'test_foo.py').write_text('# test\n',
                                                         encoding='utf-8')
        from aegis_sdk.invariants import check_file_must_exist
        violation = check_file_must_exist(
            path_pattern='tests/test_foo.py',
            workspace=str(tmp_path)
        )
        assert violation is None


# ---------------------------------------------------------------------------
# Phase 4.2c: check_invariants aggregate
# ---------------------------------------------------------------------------

class TestCheckInvariants:
    """The aggregate check_invariants function evaluates all invariants."""

    def test_no_invariants_passes(self):
        """Cell without invariants always passes."""
        from aegis_sdk.invariants import check_invariants
        violations = check_invariants(invariant_specs=[], target_files=[], workspace='/tmp')
        assert violations == []

    def test_unknown_type_ignored(self, tmp_path):
        """Unknown invariant types are silently skipped, not errors."""
        from aegis_sdk.invariants import check_invariants
        specs = [{'type': 'nonexistent_check', 'value': 'foo'}]
        violations = check_invariants(
            invariant_specs=specs,
            target_files=[],
            workspace=str(tmp_path)
        )
        assert violations == []

    def test_mixed_invariants(self, tmp_path):
        """Multiple invariant types are evaluated together."""
        # Create a file with a banned import
        source = tmp_path / 'bad.py'
        source.write_text('from os import *\n', encoding='utf-8')
        from aegis_sdk.invariants import check_invariants
        specs = [
            {'type': 'import_banned', 'pattern': 'from os import *'},
            {'type': 'file_must_exist', 'path': 'missing_file.py'},
        ]
        violations = check_invariants(
            invariant_specs=specs,
            target_files=[str(source)],
            workspace=str(tmp_path)
        )
        assert len(violations) == 2

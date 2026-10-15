"""Tests for Syntactic AST Triggers (Phase 22 / v0.119.0).

Validates:
1. AST visitor identifies import triggers (import x, from x import y).
2. AST visitor identifies call triggers (func(), obj.method()).
3. AST visitor identifies decorator triggers (@dec, @mod.dec, @dec(args)).
4. Fast diff token pre-filter skips unnecessary AST parsing.
5. Non-Python files and unparseable syntax fall back gracefully with zero errors.
"""
from __future__ import annotations

import tempfile
from pathlib import Path
import pytest

from aegis_core.ast.match import match_ast_triggers, prefilter_ast_tokens


class TestASTTriggers:
    """Verifies AST syntactic trigger matching."""

    def test_import_trigger_matching(self):
        code = "import subprocess\nfrom pathlib import Path\n"
        matched, details = match_ast_triggers(
            ast_triggers={"imports": ["subprocess"]},
            code=code,
            file_path="worker.py",
        )
        assert matched
        assert "subprocess" in details.get("imports", [])

        # Non-matching import
        not_matched, _ = match_ast_triggers(
            ast_triggers={"imports": ["torch"]},
            code=code,
            file_path="worker.py",
        )
        assert not not_matched

    def test_call_trigger_matching(self):
        code = "def dangerous():\n    eval('2 + 2')\n    os.system('ls')\n"
        matched, details = match_ast_triggers(
            ast_triggers={"calls": ["eval", "system"]},
            code=code,
            file_path="app.py",
        )
        assert matched
        assert "eval" in details.get("calls", [])
        assert "system" in details.get("calls", [])

    def test_decorator_trigger_matching(self):
        code = "@dataclass\nclass User:\n    @pytest.mark.skip(reason='flaky')\n    def run(self):\n        pass\n"
        matched, details = match_ast_triggers(
            ast_triggers={"decorators": ["dataclass", "skip"]},
            code=code,
            file_path="models.py",
        )
        assert matched
        assert "dataclass" in details.get("decorators", [])
        assert "skip" in details.get("decorators", [])

    def test_diff_token_prefilter(self):
        diff_text = "+ import os\n+ x = 1\n"
        # 'subprocess' does not appear in diff_text
        assert not prefilter_ast_tokens(diff_text, {"imports": ["subprocess"]})
        # 'os' does appear in diff_text
        assert prefilter_ast_tokens(diff_text, {"imports": ["os"]})

    def test_non_python_graceful_fallback(self):
        # Markdown file
        matched, _ = match_ast_triggers(
            ast_triggers={"imports": ["subprocess"]},
            code="# Just markdown\nimport subprocess\n",
            file_path="README.md",
        )
        assert not matched

        # Invalid Python syntax
        matched, _ = match_ast_triggers(
            ast_triggers={"imports": ["subprocess"]},
            code="def broken(:\n",
            file_path="broken.py",
        )
        assert not matched

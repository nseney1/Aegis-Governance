"""Unit and behavioral tests for AST-based call graph completeness checker."""
from __future__ import annotations

import os
import textwrap
import pytest

from aegis_core.verification import call_graph


class TestCallGraphAST:
    """Test AST-based call graph construction and orphan detection."""

    def test_ast_ignores_comment_mentions(self, tmp_path):
        """A function mentioned only in a comment must be flagged as an orphan."""
        code = textwrap.dedent("""\
            def compute_tax(amount: float) -> float:
                return amount * 0.15

            # Note: compute_tax(100.0) should be integrated later
            def main():
                return 0
        """)
        target = tmp_path / "tax.py"
        target.write_text(code, encoding="utf-8")

        result = call_graph.check(str(target), str(tmp_path), exclude_names={"main"})
        assert result.verdict is False, f"Expected FAIL but got: {result.detail}"
        assert "compute_tax" in result.detail

    def test_ast_ignores_docstring_mentions(self, tmp_path):
        """A function mentioned only in a docstring must be flagged as an orphan."""
        code = textwrap.dedent("""\
            def calculate_discount():
                \"\"\"Example: calculate_discount() returns 0.2\"\"\"
                return 0.2

            def main():
                return 0
        """)
        target = tmp_path / "discount.py"
        target.write_text(code, encoding="utf-8")

        result = call_graph.check(str(target), str(tmp_path), exclude_names={"main"})
        assert result.verdict is False, f"Expected FAIL but got: {result.detail}"
        assert "calculate_discount" in result.detail

    def test_ast_ignores_string_literals(self, tmp_path):
        """A function name in a string literal does not count as a call."""
        code = textwrap.dedent("""\
            def execute_pipeline():
                return True

            LOG_MESSAGE = "Do not execute_pipeline() without authorization"

            def main():
                return LOG_MESSAGE
        """)
        target = tmp_path / "pipeline.py"
        target.write_text(code, encoding="utf-8")

        result = call_graph.check(str(target), str(tmp_path), exclude_names={"main"})
        assert result.verdict is False, f"Expected FAIL but got: {result.detail}"
        assert "execute_pipeline" in result.detail

    def test_ast_common_identifier_no_collision_with_external_module(self, tmp_path):
        """External calls like subprocess.run() must not satisfy a local def run()."""
        # Local file defines 'run'
        target_code = textwrap.dedent("""\
            def run():
                return "local runner"
        """)
        target = tmp_path / "local_runner.py"
        target.write_text(target_code, encoding="utf-8")

        # Other file in repo calls subprocess.run()
        other_code = textwrap.dedent("""\
            import subprocess

            def execute():
                return subprocess.run(["echo", "hello"])
        """)
        other = tmp_path / "other.py"
        other.write_text(other_code, encoding="utf-8")

        result = call_graph.check(str(target), str(tmp_path), exclude_names={"execute"})
        assert result.verdict is False, (
            f"Expected FAIL (subprocess.run collided with local def run): {result.detail}"
        )
        assert "run" in result.detail

    def test_ast_tracks_direct_internal_calls(self, tmp_path):
        """A function called internally by another function passes."""
        code = textwrap.dedent("""\
            def internal_helper(x: int) -> int:
                return x * 2

            def main():
                return internal_helper(21)
        """)
        target = tmp_path / "worker.py"
        target.write_text(code, encoding="utf-8")

        result = call_graph.check(str(target), str(tmp_path), exclude_names={"main"})
        assert result.verdict is True, f"Expected PASS but got: {result.detail}"

    def test_ast_tracks_class_method_calls(self, tmp_path):
        """Class methods called via self.method() or instance.method() pass."""
        code = textwrap.dedent("""\
            class Engine:
                def calibrate(self):
                    return True

                def start(self):
                    return self.calibrate()

            def main():
                e = Engine()
                return e.start()
        """)
        target = tmp_path / "engine.py"
        target.write_text(code, encoding="utf-8")

        result = call_graph.check(str(target), str(tmp_path), exclude_names={"main"})
        assert result.verdict is True, f"Expected PASS but got: {result.detail}"

    def test_ast_respects_dunder_all_exports(self, tmp_path):
        """Functions exported in __all__ are library APIs and must not be flagged as orphans."""
        code = textwrap.dedent("""\
            __all__ = ["public_api", "ExportedClass"]

            def public_api():
                return 42

            class ExportedClass:
                pass
        """)
        target = tmp_path / "public_lib.py"
        target.write_text(code, encoding="utf-8")

        result = call_graph.check(str(target), str(tmp_path))
        assert result.verdict is True, (
            f"Expected PASS (__all__ export should not be flagged as orphan): {result.detail}"
        )

    def test_ast_cross_module_import_and_call(self, tmp_path):
        """A function imported and called in another file passes."""
        target_code = textwrap.dedent("""\
            def process_order(order_id: str) -> bool:
                return True
        """)
        target = tmp_path / "orders.py"
        target.write_text(target_code, encoding="utf-8")

        consumer_code = textwrap.dedent("""\
            from orders import process_order

            def handle_request():
                return process_order("123")
        """)
        consumer = tmp_path / "api.py"
        consumer.write_text(consumer_code, encoding="utf-8")

        result = call_graph.check(str(target), str(tmp_path))
        assert result.verdict is True, f"Expected PASS: {result.detail}"

    def test_ast_handles_syntax_errors_in_other_files_gracefully(self, tmp_path):
        """Unparseable syntax in unrelated files does not crash the check."""
        target_code = textwrap.dedent("""\
            def compute():
                return 1

            def main():
                return compute()
        """)
        target = tmp_path / "valid.py"
        target.write_text(target_code, encoding="utf-8")

        broken = tmp_path / "broken_syntax.py"
        broken.write_text("def broken_func(\n  invalid syntax here !!!\n", encoding="utf-8")

        result = call_graph.check(str(target), str(tmp_path), exclude_names={"main"})
        assert result.verdict is True, f"Expected PASS despite broken sibling file: {result.detail}"

    def test_ast_handles_async_functions(self, tmp_path):
        """Async functions and await calls are accurately analyzed."""
        code = textwrap.dedent("""\
            async def fetch_record():
                return {"id": 1}

            async def main():
                return await fetch_record()
        """)
        target = tmp_path / "async_service.py"
        target.write_text(code, encoding="utf-8")

        result = call_graph.check(str(target), str(tmp_path), exclude_names={"main"})
        assert result.verdict is True, f"Expected PASS: {result.detail}"

    def test_call_graph_fast_mode_skips_external_walk(self, tmp_path, monkeypatch):
        """When fast_mode=True, call_graph.check performs intra-module checks and skips os.walk."""
        code = textwrap.dedent("""\
            def exported():
                return 1

            __all__ = ['exported']
        """)
        target = tmp_path / "module.py"
        target.write_text(code, encoding="utf-8")

        walk_called = []
        import os
        orig_walk = os.walk
        def mock_walk(*args, **kwargs):
            walk_called.append(args)
            return orig_walk(*args, **kwargs)
        monkeypatch.setattr(os, "walk", mock_walk)

        result = call_graph.check(str(target), str(tmp_path), fast_mode=True)
        assert result.verdict is True
        assert len(walk_called) == 0, "fast_mode=True must not execute repo-wide os.walk"



class TestCrossModuleReferences:
    """A function another module passes by reference (a callback) is used, as it is within its own module."""

    _TARGET = textwrap.dedent("""\
        def _call_target(item):
            return str(item)

        def unused_helper():
            return 0
    """)

    def _check(self, tmp_path, consumer: str):
        (tmp_path / "pkg").mkdir()
        (tmp_path / "pkg" / "__init__.py").write_text("", encoding="utf-8")
        target = tmp_path / "pkg" / "schema.py"
        target.write_text(self._TARGET, encoding="utf-8")
        (tmp_path / "pkg" / "policy.py").write_text(textwrap.dedent(consumer), encoding="utf-8")
        return call_graph.check(str(target), str(tmp_path))

    def test_imported_function_passed_to_map_is_used(self, tmp_path):
        result = self._check(tmp_path, """\
            from pkg.schema import _call_target

            def targets(items):
                return list(map(_call_target, items))
        """)
        assert result.verdict is False
        assert result.detail == "ORPHAN FUNCTIONS: unused_helper (L4) — defined but never called"

    def test_imported_function_passed_as_keyword_is_used(self, tmp_path):
        result = self._check(tmp_path, """\
            from pkg.schema import _call_target as key_of

            def ordered(items):
                return sorted(items, key=key_of)
        """)
        assert "_call_target" not in result.detail
        assert "unused_helper (L4)" in result.detail

    def test_function_called_under_an_import_alias_is_used(self, tmp_path):
        result = self._check(tmp_path, """\
            from pkg.schema import _call_target as target_of

            def first(items):
                return target_of(items[0])
        """)
        assert "_call_target" not in result.detail
        assert "unused_helper (L4)" in result.detail

    def test_function_passed_through_a_module_alias_is_used(self, tmp_path):
        result = self._check(tmp_path, """\
            from pkg import schema as sc

            def targets(items):
                return [*map(sc._call_target, items)]
        """)
        assert "_call_target" not in result.detail
        assert "unused_helper (L4)" in result.detail

    def test_function_stored_in_a_dispatch_table_is_used(self, tmp_path):
        result = self._check(tmp_path, """\
            from pkg.schema import _call_target, unused_helper

            HANDLERS = {"call": _call_target}
            ORDER = [unused_helper]
        """)
        assert result.verdict is True, result.detail

    def test_same_name_from_another_module_does_not_count(self, tmp_path):
        result = self._check(tmp_path, """\
            from elsewhere import _call_target

            def targets(items):
                return list(map(_call_target, items))
        """)
        assert result.verdict is False
        assert "_call_target (L1)" in result.detail

    def test_unimported_name_passed_by_reference_does_not_count(self, tmp_path):
        result = self._check(tmp_path, """\
            def _call_target(item):
                return item

            def targets(items):
                return list(map(_call_target, items))
        """)
        assert result.verdict is False
        assert "_call_target (L1)" in result.detail

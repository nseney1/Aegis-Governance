"""Deterministic AST-based quality gate checks (Phase 2H).

Layer 1 verification tools that parse test files and check for quality signals
without any LLM involvement — pure AST walking and file-matching logic.
"""
import ast
import os
from pathlib import Path

from . import ToolEvidence


# ── Helpers ────────────────────────────────────────────────────────────────


def _collect_test_functions(tree: ast.Module) -> list[ast.FunctionDef]:
    """Return all ``test_*`` functions, both top-level and inside classes."""
    funcs: list[ast.FunctionDef] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name.startswith("test_"):
                funcs.append(node)
    return funcs


def _has_assert(func: ast.FunctionDef) -> bool:
    """Return True if *func*'s body contains an assertion or assertion-equivalent.

    Recognized patterns:
    - ``assert`` statements
    - ``with pytest.raises(...)`` context managers
    - ``pytest.fail(...)`` calls
    - ``self.assert*(...)`` calls (unittest style)
    """
    for node in ast.walk(func):
        # Standard assert statement
        if isinstance(node, ast.Assert):
            return True
        # pytest.raises used as context manager: with pytest.raises(...)
        if isinstance(node, ast.With):
            for item in node.items:
                ctx = item.context_expr
                if isinstance(ctx, ast.Call) and _is_pytest_raises(ctx):
                    return True
        # pytest.fail(...) call
        if isinstance(node, ast.Call) and _is_pytest_fail(node):
            return True
        # self.assert*(...) unittest-style call
        if isinstance(node, ast.Call) and _is_unittest_assert(node):
            return True
    return False


def _is_pytest_raises(call: ast.Call) -> bool:
    """Check if a Call node is ``pytest.raises(...)``."""
    func = call.func
    return (
        isinstance(func, ast.Attribute)
        and func.attr == "raises"
        and isinstance(func.value, ast.Name)
        and func.value.id == "pytest"
    )


def _is_pytest_fail(call: ast.Call) -> bool:
    """Check if a Call node is ``pytest.fail(...)``."""
    func = call.func
    return (
        isinstance(func, ast.Attribute)
        and func.attr == "fail"
        and isinstance(func.value, ast.Name)
        and func.value.id == "pytest"
    )


def _is_unittest_assert(call: ast.Call) -> bool:
    """Check if a Call node is ``self.assert*(...)``."""
    func = call.func
    return (
        isinstance(func, ast.Attribute)
        and func.attr.startswith("assert")
        and isinstance(func.value, ast.Name)
        and func.value.id == "self"
    )


def _is_docstring_node(node: ast.stmt) -> bool:
    """Return True if *node* is a standalone string-expression (docstring)."""
    return (
        isinstance(node, ast.Expr)
        # ast.Str was removed in Python 3.14; ast.Constant covers it since 3.8.
        and isinstance(node.value, ast.Constant)
        and isinstance(getattr(node.value, "value", None), str)
    )


def _is_pass_node(node: ast.stmt) -> bool:
    return isinstance(node, ast.Pass)


def _is_ellipsis_node(node: ast.stmt) -> bool:
    return (
        isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Constant)
        and node.value.value is ...
    )


def _is_bare_pass_func(func: ast.FunctionDef) -> bool:
    """True if the function body (ignoring a leading docstring) is only pass/ellipsis."""
    body = list(func.body)
    # Strip leading docstring if present
    if body and _is_docstring_node(body[0]):
        body = body[1:]
    if not body:
        return True
    # Body must be exactly one statement that is pass or ellipsis
    if len(body) != 1:
        return False
    return _is_pass_node(body[0]) or _is_ellipsis_node(body[0])


def _is_skippable_changed_file(filepath: str) -> bool:
    """Return True if *filepath* should be excluded from coverage checks."""
    basename = os.path.basename(filepath)
    # Non-Python files
    if not basename.endswith(".py"):
        return True
    # Test files
    if basename.startswith("test_") or basename == "conftest.py":
        return True
    # Init and config
    if basename == "__init__.py":
        return True
    return False


# ── Public API ─────────────────────────────────────────────────────────────


def check_assertion_density(test_file: str) -> ToolEvidence:
    """Check that every ``test_*`` function in *test_file* has ≥1 assert."""
    source = Path(test_file).read_text()
    tree = ast.parse(source, filename=test_file)
    test_funcs = _collect_test_functions(tree)

    missing: list[tuple[str, int]] = []
    for func in test_funcs:
        if not _has_assert(func):
            missing.append((func.name, func.lineno))

    if missing:
        names = ", ".join(name for name, _ in missing)
        detail = f"Tests lacking assertions: {names}"
        verdict = False
        lines = [lineno for _, lineno in missing]
    else:
        detail = "All tests have assertions"
        verdict = True
        lines = []

    return ToolEvidence(
        tool="assertion_density",
        target=test_file,
        verdict=verdict,
        detail=detail,
        lines=lines,
    )


def check_no_bare_pass(test_file: str) -> ToolEvidence:
    """Check that no ``test_*`` function is a bare pass/ellipsis stub."""
    source = Path(test_file).read_text()
    tree = ast.parse(source, filename=test_file)
    test_funcs = _collect_test_functions(tree)

    stubs: list[tuple[str, int]] = []
    for func in test_funcs:
        if _is_bare_pass_func(func):
            stubs.append((func.name, func.lineno))

    if stubs:
        names = ", ".join(name for name, _ in stubs)
        detail = f"Bare pass/ellipsis stubs: {names}"
        verdict = False
        lines = [lineno for _, lineno in stubs]
    else:
        detail = "No bare pass stubs found"
        verdict = True
        lines = []

    return ToolEvidence(
        tool="no_bare_pass",
        target=test_file,
        verdict=verdict,
        detail=detail,
        lines=lines,
    )


def check_behavioral_coverage(
    changed_files: list[str],
    test_files: list[str],
    repo_root: str,
) -> ToolEvidence:
    """Check that every changed implementation file has a ``test_*.py`` counterpart."""
    # Build set of test basenames for fast lookup
    test_basenames: set[str] = set()
    for tf in test_files:
        test_basenames.add(os.path.basename(tf))

    impl_files = [f for f in changed_files if not _is_skippable_changed_file(f)]
    uncovered: list[str] = []

    for filepath in impl_files:
        stem = Path(filepath).stem  # e.g. "models" from "src/models.py"
        expected = f"test_{stem}.py"

        # Also check parent-dir convention: aegis_cli/init.py → test_cli.py
        # Try the full parent dir name and each underscore-split part
        parent_dir = Path(filepath).parent.name
        parent_candidates: set[str] = set()
        if parent_dir:
            parent_candidates.add(f"test_{parent_dir}.py")
            for part in parent_dir.split("_"):
                if part:
                    parent_candidates.add(f"test_{part}.py")

        if expected in test_basenames:
            continue
        if parent_candidates & test_basenames:
            continue
        uncovered.append(filepath)

    covered_count = len(impl_files) - len(uncovered)
    total_count = len(impl_files)

    if uncovered:
        files_str = ", ".join(uncovered)
        detail = f"{covered_count}/{total_count} covered. Uncovered: {files_str}"
        verdict = False
    else:
        detail = f"{covered_count}/{total_count} covered" if total_count else "No implementation files changed"
        verdict = True

    return ToolEvidence(
        tool="behavioral_coverage",
        target=repo_root,
        verdict=verdict,
        detail=detail,
        lines=[],
    )

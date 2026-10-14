"""Syntactic AST Trigger Matching Engine (Phase 22 / v0.119.0).

Enables governance cells to trigger on syntactic code constructs:
- imports: modules or imported symbols (e.g. `subprocess`, `pickle`, `os`)
- calls: function or method invocations (e.g. `eval`, `exec`, `os.system`)
- decorators: applied decorators (e.g. `@pytest.fixture`, `@dataclass`, `@flaky`)

Combines fast diff hunk token pre-filtering with AST visitor traversal.
Strictly zero-dependency: uses only Python standard library.
"""
from __future__ import annotations

import ast
import os
import re
from typing import Any, Dict, List, Set, Tuple


def _normalize_token(token: str) -> str:
    """Normalize trigger identifier by stripping leading decorators and whitespace."""
    t = token.strip()
    if t.startswith("@"):
        t = t[1:].strip()
    return t


def prefilter_ast_tokens(text: str | None, ast_triggers: Dict[str, Any] | None) -> bool:
    """Fast pre-filter checking if any trigger token appears in the code/diff text.

    Returns False if trigger tokens are specified and none exist in text.
    Returns True if triggers are empty, text is empty, or at least one token matches.
    """
    if not ast_triggers or not isinstance(ast_triggers, dict):
        return True
    if not text:
        return True

    tokens: Set[str] = set()
    for category in ("imports", "calls", "decorators"):
        items = ast_triggers.get(category)
        if isinstance(items, list):
            for item in items:
                if isinstance(item, str):
                    norm = _normalize_token(item)
                    if norm:
                        tokens.add(norm)
                        # Also add leaf part (e.g., 'system' from 'os.system')
                        if "." in norm:
                            tokens.update(norm.split("."))

    if not tokens:
        return True

    # Check substring occurrence for each token
    for tok in tokens:
        if tok in text:
            return True
    return False


class ASTTriggerVisitor(ast.NodeVisitor):
    """AST visitor extracting imports, calls, and decorators."""

    def __init__(
        self,
        target_imports: Set[str],
        target_calls: Set[str],
        target_decorators: Set[str],
    ):
        self.target_imports = target_imports
        self.target_calls = target_calls
        self.target_decorators = target_decorators

        self.matched_imports: Set[str] = set()
        self.matched_calls: Set[str] = set()
        self.matched_decorators: Set[str] = set()

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            name = alias.name
            if name in self.target_imports:
                self.matched_imports.add(name)
            for part in name.split("."):
                if part in self.target_imports:
                    self.matched_imports.add(part)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        mod = node.module or ""
        if mod in self.target_imports:
            self.matched_imports.add(mod)
        for part in mod.split("."):
            if part in self.target_imports:
                self.matched_imports.add(part)

        for alias in node.names:
            if alias.name in self.target_imports:
                self.matched_imports.add(alias.name)
            full = f"{mod}.{alias.name}" if mod else alias.name
            if full in self.target_imports:
                self.matched_imports.add(full)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        call_name = self._resolve_call_name(node.func)
        if call_name:
            if call_name in self.target_calls:
                self.matched_calls.add(call_name)
            # Check leaf attribute name (e.g. 'system' in 'os.system')
            leaf = call_name.split(".")[-1]
            if leaf in self.target_calls:
                self.matched_calls.add(leaf)
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._check_decorators(node.decorator_list)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._check_decorators(node.decorator_list)
        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._check_decorators(node.decorator_list)
        self.generic_visit(node)

    def _resolve_call_name(self, node: ast.AST) -> str | None:
        if isinstance(node, ast.Name):
            return node.id
        elif isinstance(node, ast.Attribute):
            val_name = self._resolve_call_name(node.value)
            if val_name:
                return f"{val_name}.{node.attr}"
            return node.attr
        return None

    def _check_decorators(self, decorator_list: List[ast.expr]) -> None:
        for dec in decorator_list:
            dec_node = dec.func if isinstance(dec, ast.Call) else dec
            dec_name = self._resolve_call_name(dec_node)
            if dec_name:
                norm = _normalize_token(dec_name)
                if norm in self.target_decorators:
                    self.matched_decorators.add(norm)
                leaf = norm.split(".")[-1]
                if leaf in self.target_decorators:
                    self.matched_decorators.add(leaf)


def match_ast_triggers(
    ast_triggers: Dict[str, Any] | None,
    code: str = "",
    file_path: str = "",
    diff_text: str = "",
) -> Tuple[bool, Dict[str, List[str]]]:
    """Evaluate whether code or file_path matches any AST syntactic triggers.

    Args:
        ast_triggers: Dict with optional 'imports', 'calls', 'decorators' lists.
        code: Optional raw Python code string.
        file_path: Optional path to Python source file.
        diff_text: Optional diff hunk text for fast token pre-filtering.

    Returns:
        Tuple of (matched: bool, details: dict[category, list[matches]])
    """
    if not ast_triggers or not isinstance(ast_triggers, dict):
        return False, {}

    # File path filter: if path is provided, must be a Python file
    if file_path:
        basename = os.path.basename(file_path)
        if not basename.endswith(".py"):
            return False, {}

    # Diff pre-filter optimization
    if diff_text and not prefilter_ast_tokens(diff_text, ast_triggers):
        return False, {}

    # Obtain source code
    source_code = code
    if not source_code and file_path and os.path.isfile(file_path):
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                source_code = f.read()
        except OSError:
            return False, {}

    if not source_code.strip():
        return False, {}

    # Parse AST safely
    try:
        tree = ast.parse(source_code, filename=file_path or "<string>")
    except (SyntaxError, ValueError, MemoryError):
        return False, {}

    target_imports = {_normalize_token(x) for x in ast_triggers.get("imports", []) if isinstance(x, str)}
    target_calls = {_normalize_token(x) for x in ast_triggers.get("calls", []) if isinstance(x, str)}
    target_decorators = {_normalize_token(x) for x in ast_triggers.get("decorators", []) if isinstance(x, str)}

    visitor = ASTTriggerVisitor(target_imports, target_calls, target_decorators)
    visitor.visit(tree)

    details: Dict[str, List[str]] = {}
    if visitor.matched_imports:
        details["imports"] = sorted(visitor.matched_imports)
    if visitor.matched_calls:
        details["calls"] = sorted(visitor.matched_calls)
    if visitor.matched_decorators:
        details["decorators"] = sorted(visitor.matched_decorators)

    matched = bool(details)
    return matched, details


__all__ = [
    "ASTTriggerVisitor",
    "match_ast_triggers",
    "prefilter_ast_tokens",
]

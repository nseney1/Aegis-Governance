"""Built-in Python Native AST Driver.

Extracts language-agnostic NormalizedAST representation using Python's standard library
ast module. Operates purely in-process with zero external dependencies.
"""
from __future__ import annotations

import ast
from pathlib import Path
from typing import Any, List, Optional, Set, Tuple, Union

from aegis_core.ast.schema import (
    CallSiteNode,
    DefinitionNode,
    ImportNode,
    MutationPoint,
    NormalizedAST,
)


def _resolve_attribute_chain(node: ast.AST) -> Optional[str]:
    """Recursively resolve dot-separated attribute chain (e.g. os.path.join)."""
    parts = []
    current = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if isinstance(current, ast.Name):
        parts.append(current.id)
        return ".".join(reversed(parts))
    return None


class _PythonASTVisitor(ast.NodeVisitor):
    def __init__(self, file_path: str):
        self.file_path = file_path
        self.dunder_all: Optional[Set[str]] = None
        self.scope_stack: List[str] = []
        self.class_stack: List[str] = []

        self.definitions: List[DefinitionNode] = []
        self.call_sites: List[CallSiteNode] = []
        self.imports: List[ImportNode] = []
        self.mutation_points: List[MutationPoint] = []

    def visit_Assign(self, node: ast.Assign):
        # Extract __all__ = ["func1", "func2"]
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == "__all__":
                if isinstance(node.value, (ast.List, ast.Tuple, ast.Set)):
                    self.dunder_all = set()
                    for elt in node.value.elts:
                        if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                            self.dunder_all.add(elt.value)
        self.generic_visit(node)

    def visit_Import(self, node: ast.Import):
        for alias in node.names:
            imported = (alias.asname or alias.name,)
            self.imports.append(
                ImportNode(
                    source=alias.name,
                    imported_symbols=imported,
                    line=node.lineno,
                )
            )
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom):
        source = node.module or ""
        symbols = tuple(alias.asname or alias.name for alias in node.names)
        self.imports.append(
            ImportNode(
                source=source,
                imported_symbols=symbols,
                line=node.lineno,
            )
        )
        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef):
        class_name = node.name
        is_exported = (
            class_name in self.dunder_all
            if self.dunder_all is not None
            else not class_name.startswith("_")
        )
        self.definitions.append(
            DefinitionNode(
                name=class_name,
                kind="class",
                line=node.lineno,
                is_exported=is_exported,
            )
        )
        self.class_stack.append(class_name)
        self.scope_stack.append(class_name)
        self.generic_visit(node)
        self.scope_stack.pop()
        self.class_stack.pop()

    def _visit_func(self, node: Union[ast.FunctionDef, ast.AsyncFunctionDef]):
        func_name = node.name
        class_name = self.class_stack[-1] if self.class_stack else None
        is_method = class_name is not None
        kind = "method" if is_method else "function"

        if self.dunder_all is not None:
            is_exported = func_name in self.dunder_all
        else:
            is_exported = not func_name.startswith("_")

        self.definitions.append(
            DefinitionNode(
                name=func_name,
                kind=kind,
                line=node.lineno,
                is_exported=is_exported,
                class_name=class_name,
            )
        )

        self.scope_stack.append(func_name)
        self.generic_visit(node)
        self.scope_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef):
        self._visit_func(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
        self._visit_func(node)

    def visit_Call(self, node: ast.Call):
        target = None
        if isinstance(node.func, ast.Name):
            target = node.func.id
        elif isinstance(node.func, ast.Attribute):
            target = _resolve_attribute_chain(node.func)

        if target:
            caller_scope = self.scope_stack[-1] if self.scope_stack else None
            self.call_sites.append(
                CallSiteNode(
                    target=target,
                    line=node.lineno,
                    caller_scope=caller_scope,
                )
            )
        self.generic_visit(node)

    def visit_Compare(self, node: ast.Compare):
        # Extract comparison mutation points
        op_map = {
            ast.Eq: ("==", "!="),
            ast.NotEq: ("!=", "=="),
            ast.Lt: ("<", ">="),
            ast.Gt: (">", "<="),
            ast.LtE: ("<=", ">"),
            ast.GtE: (">=", "<"),
        }
        for op in node.ops:
            op_type = type(op)
            if op_type in op_map:
                orig, repl = op_map[op_type]
                self.mutation_points.append(
                    MutationPoint(
                        line=node.lineno,
                        col=getattr(node, "col_offset", 0),
                        original_op=orig,
                        replacement_op=repl,
                        mutation_type="comparison",
                    )
                )
        self.generic_visit(node)

    def visit_BinOp(self, node: ast.BinOp):
        bin_map = {
            ast.Add: ("+", "-"),
            ast.Sub: ("-", "+"),
            ast.Mult: ("*", "/"),
            ast.Div: ("/", "*"),
        }
        op_type = type(node.op)
        if op_type in bin_map:
            orig, repl = bin_map[op_type]
            self.mutation_points.append(
                MutationPoint(
                    line=node.lineno,
                    col=getattr(node, "col_offset", 0),
                    original_op=orig,
                    replacement_op=repl,
                    mutation_type="binary_op",
                )
            )
        self.generic_visit(node)


def parse_python_ast(
    source_or_path: Union[str, Path],
    file_path: Optional[str] = None,
) -> NormalizedAST:
    """Parse Python source code or file into a NormalizedAST instance."""
    resolved_path = str(file_path or source_or_path)
    if isinstance(source_or_path, Path) or (
        isinstance(source_or_path, str) and not "\n" in source_or_path and Path(source_or_path).is_file()
    ):
        content = Path(source_or_path).read_text(encoding="utf-8")
        resolved_path = str(source_or_path)
    else:
        content = str(source_or_path)

    try:
        tree = ast.parse(content, filename=resolved_path)
    except SyntaxError as exc:
        raise ValueError(f"Failed to parse Python AST for {resolved_path}: {exc}") from exc

    visitor = _PythonASTVisitor(file_path=resolved_path)
    visitor.visit(tree)

    return NormalizedAST(
        file_path=resolved_path,
        language="python",
        definitions=tuple(visitor.definitions),
        call_sites=tuple(visitor.call_sites),
        imports=tuple(visitor.imports),
        mutation_points=tuple(visitor.mutation_points),
        metadata={"parser": "stdlib_ast"},
    )

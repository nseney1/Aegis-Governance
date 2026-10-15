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
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple, Union

from aegis_core.ast.schema import (
    CallSiteNode,
    DefinitionNode,
    ImportNode,
    NormalizedAST,
)


def _normalize_token(token: str) -> str:
    """Normalize trigger identifier by stripping leading decorators, call parens, and whitespace."""
    t = token.strip()
    if t.startswith("@"):
        t = t[1:].strip()
    if t.endswith("()"):
        t = t[:-2].strip()
    return t


def _extract_python_decorators_from_tree(tree: ast.AST) -> Tuple[str, ...]:
    """Extract normalized decorator names from a parsed Python AST."""
    decorators: List[str] = []

    def _resolve_name(node: ast.AST) -> Optional[str]:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            parent = _resolve_name(node.value)
            return f"{parent}.{node.attr}" if parent else node.attr
        return None

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            for dec in node.decorator_list:
                target = dec.func if isinstance(dec, ast.Call) else dec
                dec_name = _resolve_name(target)
                if dec_name:
                    norm = _normalize_token(dec_name)
                    if norm and norm not in decorators:
                        decorators.append(norm)
    return tuple(decorators)


def _extract_python_decorators_from_file(file_path: str) -> Tuple[str, ...]:
    """Extract decorator names from a Python file on disk if readable and valid."""
    if not file_path or not file_path.endswith(".py") or not os.path.isfile(file_path):
        return ()
    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            source = f.read()
        if not source.strip():
            return ()
        tree = ast.parse(source, filename=file_path)
        return _extract_python_decorators_from_tree(tree)
    except Exception:
        return ()


# Ensure NormalizedAST supports convenient .calls and .decorators access and construction
_ORIG_NORM_AST_INIT = NormalizedAST.__init__


def _enhanced_norm_ast_init(self: NormalizedAST, *args: Any, **kwargs: Any) -> None:
    calls_arg = kwargs.pop("calls", None)
    decorators_arg = kwargs.pop("decorators", None)

    if not args and "file_path" not in kwargs:
        kwargs["file_path"] = "<virtual>"
    if len(args) < 2 and "language" not in kwargs:
        kwargs["language"] = "python"

    # Coerce string imports if passed directly in kwargs["imports"] or args[4]
    if "imports" in kwargs and kwargs["imports"]:
        coerced_imports = []
        for imp in kwargs["imports"]:
            if isinstance(imp, str):
                norm = _normalize_token(imp)
                coerced_imports.append(
                    ImportNode(source=norm, imported_symbols=(norm.split(".")[-1],) if norm else ())
                )
            elif isinstance(imp, dict):
                coerced_imports.append(ImportNode.from_dict(imp))
            else:
                coerced_imports.append(imp)
        kwargs["imports"] = tuple(coerced_imports)

    if calls_arg is not None and "call_sites" not in kwargs and len(args) < 4:
        coerced_calls = []
        for c in calls_arg:
            if isinstance(c, str):
                coerced_calls.append(CallSiteNode(target=_normalize_token(c)))
            elif isinstance(c, dict):
                coerced_calls.append(CallSiteNode.from_dict(c))
            else:
                coerced_calls.append(c)
        kwargs["call_sites"] = tuple(coerced_calls)

    if decorators_arg is not None:
        meta = dict(kwargs.get("metadata") or {})
        meta["decorators"] = [
            _normalize_token(d) if isinstance(d, str) else str(d)
            for d in decorators_arg
        ]
        kwargs["metadata"] = meta

    _ORIG_NORM_AST_INIT(self, *args, **kwargs)


if getattr(NormalizedAST.__init__, "__name__", "") != "_enhanced_norm_ast_init":
    NormalizedAST.__init__ = _enhanced_norm_ast_init  # type: ignore[method-assign]

if not hasattr(NormalizedAST, "calls"):
    NormalizedAST.calls = property(  # type: ignore[attr-defined]
        lambda self: tuple(
            c.target if hasattr(c, "target") else str(c)
            for c in self.call_sites
        )
    )

if not hasattr(NormalizedAST, "decorators"):
    def _get_norm_ast_decorators(self: NormalizedAST) -> Tuple[str, ...]:
        meta_decs = self.metadata.get("decorators") if isinstance(self.metadata, dict) else None
        if meta_decs is not None:
            return tuple(_normalize_token(str(d)) for d in meta_decs if d)
        return _extract_python_decorators_from_file(self.file_path)

    NormalizedAST.decorators = property(_get_norm_ast_decorators)  # type: ignore[attr-defined]


def evaluate_forbid_ast(
    normalized_ast: NormalizedAST,
    forbid_spec: dict[str, Any],
) -> list[str]:
    """Evaluate a NormalizedAST against declarative forbid_ast constraints.

    Supports forbid_spec keys:
      - imports: list of forbidden import modules/prefixes (e.g., ["pickle", "subprocess"]).
      - calls: list of forbidden function/method calls (e.g., ["eval", "exec", "os.system"]).
      - decorators: list of forbidden decorators (e.g., ["pytest.mark.xfail"]).

    Returns:
      List of human-readable violation strings, or [] if clean.
    """
    if normalized_ast is None or not forbid_spec or not isinstance(forbid_spec, dict):
        return []

    violations: list[str] = []

    # 1. Extract imports and build symbol qualification map
    raw_ast_imports = getattr(normalized_ast, "imports", ()) or ()
    parsed_imports: list[tuple[str, tuple[str, ...]]] = []
    imported_qual_map: dict[str, str] = {}

    for imp in raw_ast_imports:
        if isinstance(imp, str):
            src = _normalize_token(imp)
            syms: tuple[str, ...] = ()
        elif isinstance(imp, dict):
            src = _normalize_token(str(imp.get("source") or imp.get("module") or ""))
            raw_syms = imp.get("imported_symbols") or imp.get("imported_names") or ()
            syms = tuple(_normalize_token(str(s)) for s in raw_syms if s)
        else:
            src = _normalize_token(str(getattr(imp, "source", "") or getattr(imp, "module", "") or ""))
            raw_syms = getattr(imp, "imported_symbols", ()) or getattr(imp, "imported_names", ()) or ()
            syms = tuple(_normalize_token(str(s)) for s in raw_syms if s)

        parsed_imports.append((src, syms))
        if src:
            for sym in syms:
                if sym and sym != src:
                    imported_qual_map[sym] = f"{src}.{sym}"

    forbidden_imports = forbid_spec.get("imports")
    if isinstance(forbidden_imports, (list, tuple, set)):
        for raw_mod in forbidden_imports:
            if not isinstance(raw_mod, str):
                continue
            mod = _normalize_token(raw_mod)
            if not mod:
                continue
            matched_imp = False
            for src, syms in parsed_imports:
                if src and (src == mod or src.startswith(f"{mod}.")):
                    matched_imp = True
                    break
                for sym in syms:
                    if sym == mod or sym.startswith(f"{mod}."):
                        matched_imp = True
                        break
                    if src:
                        full = f"{src}.{sym}"
                        if full == mod or full.startswith(f"{mod}."):
                            matched_imp = True
                            break
                if matched_imp:
                    break
            if matched_imp:
                violations.append(f"Forbidden import '{mod}' matched rule forbid_ast.imports")

    # 2. Extract calls
    call_candidates: list[str] = []
    raw_call_sites = getattr(normalized_ast, "call_sites", ()) or ()
    raw_calls_attr = getattr(normalized_ast, "calls", ()) or ()
    for item in list(raw_call_sites) + list(raw_calls_attr):
        if isinstance(item, str):
            target = _normalize_token(item)
        elif isinstance(item, dict):
            target = _normalize_token(str(item.get("target") or item.get("name") or ""))
        else:
            target = _normalize_token(str(getattr(item, "target", "") or getattr(item, "name", "") or ""))
        if target:
            if target not in call_candidates:
                call_candidates.append(target)
            if target in imported_qual_map:
                qual = imported_qual_map[target]
                if qual not in call_candidates:
                    call_candidates.append(qual)
            elif "." in target:
                head, tail = target.split(".", 1)
                if head in imported_qual_map:
                    qual = f"{imported_qual_map[head]}.{tail}"
                    if qual not in call_candidates:
                        call_candidates.append(qual)

    forbidden_calls = forbid_spec.get("calls")
    if isinstance(forbidden_calls, (list, tuple, set)):
        for raw_call in forbidden_calls:
            if not isinstance(raw_call, str):
                continue
            call = _normalize_token(raw_call)
            if not call:
                continue
            matched_call = False
            for cand in call_candidates:
                if cand == call or cand.endswith(f".{call}"):
                    matched_call = True
                    break
            if matched_call:
                violations.append(f"Forbidden call '{call}' matched rule forbid_ast.calls")

    # 3. Extract decorators
    dec_candidates: list[str] = []
    raw_decs_sources: list[Any] = []
    if hasattr(normalized_ast, "decorators"):
        try:
            raw_decs_sources.extend(getattr(normalized_ast, "decorators") or ())
        except Exception:
            pass
    meta = getattr(normalized_ast, "metadata", None)
    if isinstance(meta, dict) and isinstance(meta.get("decorators"), (list, tuple, set)):
        raw_decs_sources.extend(meta["decorators"])
    for defn in getattr(normalized_ast, "definitions", ()) or ():
        defn_decs = getattr(defn, "decorators", None)
        if isinstance(defn_decs, (list, tuple, set)):
            raw_decs_sources.extend(defn_decs)
        elif isinstance(defn, dict) and isinstance(defn.get("decorators"), (list, tuple, set)):
            raw_decs_sources.extend(defn["decorators"])

    if not raw_decs_sources:
        fp = getattr(normalized_ast, "file_path", "")
        if isinstance(fp, str) and fp.endswith(".py") and os.path.isfile(fp):
            raw_decs_sources.extend(_extract_python_decorators_from_file(fp))

    for d in raw_decs_sources:
        if isinstance(d, str):
            norm_d = _normalize_token(d).split("(", 1)[0].strip()
        elif isinstance(d, dict):
            norm_d = _normalize_token(str(d.get("name") or d.get("target") or "")).split("(", 1)[0].strip()
        else:
            norm_d = _normalize_token(str(getattr(d, "name", "") or getattr(d, "target", "") or d)).split("(", 1)[0].strip()
        if norm_d:
            if norm_d not in dec_candidates:
                dec_candidates.append(norm_d)
            if norm_d in imported_qual_map:
                qual_d = imported_qual_map[norm_d]
                if qual_d not in dec_candidates:
                    dec_candidates.append(qual_d)

    forbidden_decs = forbid_spec.get("decorators")
    if isinstance(forbidden_decs, (list, tuple, set)):
        for raw_dec in forbidden_decs:
            if not isinstance(raw_dec, str):
                continue
            dec = _normalize_token(raw_dec).split("(", 1)[0].strip()
            if not dec:
                continue
            matched_dec = False
            for cand in dec_candidates:
                if cand == dec or cand.endswith(f".{dec}"):
                    matched_dec = True
                    break
            if matched_dec:
                violations.append(f"Forbidden decorator '{dec}' matched rule forbid_ast.decorators")

    return violations


def synthesize_planned_ast(planned_symbols: Iterable[str]) -> NormalizedAST:
    """Synthesize a virtual NormalizedAST from pre-edit planned symbols."""
    imports: list[ImportNode] = []
    call_sites: list[CallSiteNode] = []
    decorators: list[str] = []

    for raw in planned_symbols or ():
        if not isinstance(raw, str):
            continue
        sym = _normalize_token(raw).split("(", 1)[0].strip()
        if not sym:
            continue
        imports.append(ImportNode(source=sym, imported_symbols=(sym.split(".")[-1],)))
        if "." in sym:
            head, tail = sym.split(".", 1)
            imports.append(ImportNode(source=head, imported_symbols=(tail,)))
        call_sites.append(CallSiteNode(target=sym))
        decorators.append(sym)

    return NormalizedAST(
        file_path="<planned_symbols>",
        language="python",
        definitions=(),
        call_sites=tuple(call_sites),
        imports=tuple(imports),
        mutation_points=(),
        metadata={"parser": "planned_symbols", "decorators": decorators},
    )


def extract_normalized_ast(
    file_path: Union[str, Path],
    workspace_root: Optional[Union[str, Path]] = None,
    code: Optional[str] = None,
    ast_runner: Any = None,
) -> Optional[NormalizedAST]:
    """Extract a NormalizedAST (including Python decorators) from a source file or code string."""
    from aegis_core.ast.drivers.python import parse_python_ast

    path_str = str(file_path)
    ext = os.path.splitext(path_str)[1].lower()

    if code is not None or ext == ".py":
        try:
            source_text = code if code is not None else Path(path_str).read_text(encoding="utf-8")
            norm_ast = parse_python_ast(source_text, file_path=path_str)
            tree = ast.parse(source_text, filename=path_str)
            decs = _extract_python_decorators_from_tree(tree)
            if decs:
                meta = dict(norm_ast.metadata)
                meta["decorators"] = list(decs)
                object.__setattr__(norm_ast, "metadata", meta)
            return norm_ast
        except Exception:
            return None

    try:
        if ast_runner is None:
            from aegis_core.ast.runner import ASTDriverRunner
            ast_runner = ASTDriverRunner()
        if ast_runner.registry.resolve_driver(ext, workspace_root=workspace_root):
            return ast_runner.parse_file(path_str, workspace_root=workspace_root)
    except Exception:
        return None
    return None



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
    "evaluate_forbid_ast",
    "extract_normalized_ast",
    "match_ast_triggers",
    "prefilter_ast_tokens",
    "synthesize_planned_ast",
]

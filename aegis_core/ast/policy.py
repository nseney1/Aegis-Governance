"""AST policy evaluation, extraction, and planned-symbol synthesis."""
from __future__ import annotations

import ast
import os
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional, Tuple, Union

from aegis_core.ast.schema import (
    CallSiteNode,
    ImportNode,
    NormalizedAST,
    _extract_python_decorators_from_file,
    _extract_python_decorators_from_tree,
    _normalize_ast_token,
)

__all__ = [
    "_match_ImportNode_against_pattern",
    "_match_call_against_pattern",
    "_match_decorator_against_pattern",
    "evaluate_forbid_ast",
    "extract_normalized_ast",
    "synthesize_planned_ast",
]


def _extract_import_tuple(imp: Any) -> Tuple[str, Tuple[str, ...]]:
    if isinstance(imp, tuple) and len(imp) == 2 and isinstance(imp[0], str):
        return imp[0], tuple(imp[1])
    if isinstance(imp, str):
        return _normalize_ast_token(imp), ()
    if isinstance(imp, Mapping):
        src = _normalize_ast_token(str(imp.get("source") or imp.get("module") or ""))
        raw_syms = imp.get("imported_symbols") or imp.get("imported_names") or ()
        syms = tuple(_normalize_ast_token(str(s)) for s in raw_syms if s)
        return src, syms
    src = _normalize_ast_token(str(getattr(imp, "source", "") or getattr(imp, "module", "") or ""))
    raw_syms = getattr(imp, "imported_symbols", ()) or getattr(imp, "imported_names", ()) or ()
    syms = tuple(_normalize_ast_token(str(s)) for s in raw_syms if s)
    return src, syms


def _match_ImportNode_against_pattern(imp: Any, pattern: str) -> bool:
    """Return True if an ImportNode (or raw import item) matches a forbidden module/symbol pattern."""
    mod = _normalize_ast_token(pattern)
    if not mod:
        return False
    src, syms = _extract_import_tuple(imp)
    if src and (src == mod or src.startswith(f"{mod}.")):
        return True
    for sym in syms:
        if sym == mod or sym.startswith(f"{mod}."):
            return True
        if src:
            full = f"{src}.{sym}"
            if full == mod or full.startswith(f"{mod}."):
                return True
    return False


def _match_call_against_pattern(
    call_item: Any,
    pattern: str,
    imported_qual_map: Optional[Mapping[str, str]] = None,
) -> bool:
    """Return True if a CallSiteNode or call target matches a forbidden call pattern."""
    call = _normalize_ast_token(pattern)
    if not call:
        return False
    if isinstance(call_item, str):
        target = _normalize_ast_token(call_item)
    elif isinstance(call_item, Mapping):
        target = _normalize_ast_token(str(call_item.get("target") or call_item.get("name") or ""))
    else:
        target = _normalize_ast_token(str(getattr(call_item, "target", "") or getattr(call_item, "name", "") or ""))
    if not target:
        return False

    candidates = [target]
    if imported_qual_map:
        if target in imported_qual_map:
            candidates.append(imported_qual_map[target])
        elif "." in target:
            head, tail = target.split(".", 1)
            if head in imported_qual_map:
                candidates.append(f"{imported_qual_map[head]}.{tail}")

    return any(cand == call or cand.endswith(f".{call}") for cand in candidates)


def _match_decorator_against_pattern(
    decorator_item: Any,
    pattern: str,
    imported_qual_map: Optional[Mapping[str, str]] = None,
) -> bool:
    """Return True if a decorator matches a forbidden decorator pattern."""
    dec = _normalize_ast_token(pattern).split("(", 1)[0].strip()
    if not dec:
        return False
    if isinstance(decorator_item, str):
        norm_d = _normalize_ast_token(decorator_item).split("(", 1)[0].strip()
    elif isinstance(decorator_item, Mapping):
        norm_d = _normalize_ast_token(str(decorator_item.get("name") or decorator_item.get("target") or "")).split("(", 1)[0].strip()
    else:
        norm_d = _normalize_ast_token(
            str(getattr(decorator_item, "name", "") or getattr(decorator_item, "target", "") or decorator_item)
        ).split("(", 1)[0].strip()
    if not norm_d:
        return False

    candidates = [norm_d]
    if imported_qual_map and norm_d in imported_qual_map:
        candidates.append(imported_qual_map[norm_d])

    return any(cand == dec or cand.endswith(f".{dec}") for cand in candidates)


def evaluate_forbid_ast(
    normalized_ast: NormalizedAST,
    forbid_spec: dict[str, Any],
) -> list[str]:
    """Evaluate a NormalizedAST against declarative forbid_ast constraints."""
    if normalized_ast is None or not forbid_spec or not isinstance(forbid_spec, dict):
        return []

    violations: list[str] = []

    raw_ast_imports = getattr(normalized_ast, "imports", ()) or ()
    parsed_imports: list[tuple[str, tuple[str, ...]]] = []
    imported_qual_map: dict[str, str] = {}

    for imp in raw_ast_imports:
        src, syms = _extract_import_tuple(imp)
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
            mod = _normalize_ast_token(raw_mod)
            if not mod:
                continue
            if any(_match_ImportNode_against_pattern(imp_tuple, mod) for imp_tuple in parsed_imports):
                violations.append(f"Forbidden import '{mod}' matched rule forbid_ast.imports")

    raw_call_sites = getattr(normalized_ast, "call_sites", ()) or ()
    raw_calls_attr = getattr(normalized_ast, "calls", ()) or ()
    all_call_items = list(raw_call_sites) + list(raw_calls_attr)

    forbidden_calls = forbid_spec.get("calls")
    if isinstance(forbidden_calls, (list, tuple, set)):
        for raw_call in forbidden_calls:
            if not isinstance(raw_call, str):
                continue
            call = _normalize_ast_token(raw_call)
            if not call:
                continue
            if any(_match_call_against_pattern(item, call, imported_qual_map) for item in all_call_items):
                violations.append(f"Forbidden call '{call}' matched rule forbid_ast.calls")

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

    forbidden_decs = forbid_spec.get("decorators")
    if isinstance(forbidden_decs, (list, tuple, set)):
        for raw_dec in forbidden_decs:
            if not isinstance(raw_dec, str):
                continue
            dec = _normalize_ast_token(raw_dec).split("(", 1)[0].strip()
            if not dec:
                continue
            if any(_match_decorator_against_pattern(d, dec, imported_qual_map) for d in raw_decs_sources):
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
        sym = _normalize_ast_token(raw).split("(", 1)[0].strip()
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

"""AST policy evaluation, extraction, and planned-symbol synthesis."""
from __future__ import annotations
import ast, io, os, re, tokenize
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple, Union
from aegis_core.errors import AegisError
from aegis_core.ast.schema import (
    NormalizedAST, _SpellingIndex, _add_binding, _call_target, _decorator_name,
    _decorator_pattern, _extract_import_tuple, _extract_python_decorators_from_file,
    _extract_python_decorators_from_tree, _import_aliases, _normalize_ast_token,
)

__all__ = ["ASTExtractionError", "_match_ImportNode_against_pattern", "evaluate_forbid_ast", "evaluate_forbid_ast_with_overrides", "extract_normalized_ast", "parse_allow_comments"]
_ALLOW_COMMENT_RE = re.compile(r"#\s*aegis:\s*allow(?:\[([^\]]+)\])?(?:\s*[:\-]?\s*(.*))?$", re.IGNORECASE)


def _add_allow(by_line: Dict[int, List[Dict[str, Any]]], line_no: int, text: str) -> None:
    m = _ALLOW_COMMENT_RE.search(text)
    if m:
        rules = {r.strip() for r in m.group(1).split(",") if r.strip()} if m.group(1) else None
        by_line.setdefault(int(line_no), []).append({"rules": rules, "reason": (m.group(2) or "").strip()})


def parse_allow_comments(source: str) -> Dict[int, List[Dict[str, Any]]]:
    if not source or "aegis" not in source.lower():
        return {}
    by_line: Dict[int, List[Dict[str, Any]]] = {}
    try:
        for tok_type, tok_str, (srow, _), _, _ in tokenize.generate_tokens(io.StringIO(source).readline):
            if tok_type == tokenize.COMMENT:
                _add_allow(by_line, srow, tok_str)
    except (tokenize.TokenError, IndentationError, SyntaxError):
        for idx, line in enumerate(source.splitlines(), start=1):
            _add_allow(by_line, idx, line)
    return by_line


def _line_of(item: Any) -> Optional[int]:
    val = item.get("line") if isinstance(item, Mapping) else getattr(item, "line", None)
    return int(val) if isinstance(val, int) and val > 0 else None


def _allow_reason_for_line(allow_map: Mapping[int, List[Dict[str, Any]]], line: Optional[int], rule_id: Optional[str]) -> Optional[str]:
    for entry in (allow_map.get(line) or ()) if line else ():
        if entry.get("rules") is None or not rule_id or rule_id in entry["rules"]:
            return str(entry.get("reason") or "")
    return None


def _resolve_allow_map(normalized_ast: NormalizedAST, source: Optional[str] = None) -> Dict[int, List[Dict[str, Any]]]:
    meta = getattr(normalized_ast, "metadata", None)
    if isinstance(meta, Mapping) and isinstance(meta.get("allow_comments"), dict):
        return meta["allow_comments"]
    if isinstance(source, str):
        return parse_allow_comments(source)
    fp = getattr(normalized_ast, "file_path", "")
    if isinstance(fp, str) and os.path.isfile(fp):
        try:
            from aegis_core.ast.drivers.python import read_python_source
            return parse_allow_comments(read_python_source(fp) if fp.endswith(".py") else Path(fp).read_text(encoding="utf-8", errors="replace"))
        except Exception:
            return {}
    return {}


class ASTExtractionError(AegisError):
    def __init__(self, path: str, reason: str):
        super().__init__(f"cannot verify {path}: {reason}", code="AST_UNVERIFIABLE", path=path, reason=reason)


def _match_ImportNode_against_pattern(imp: Any, pattern: str) -> bool:
    mod = _normalize_ast_token(pattern)
    if not mod:
        return False
    src, syms = _extract_import_tuple(imp)
    if src and (src == mod or src.startswith(f"{mod}.")):
        return True
    return any(s == mod or s.startswith(f"{mod}.") or (src and (f"{src}.{s}" == mod or f"{src}.{s}".startswith(f"{mod}."))) for s in syms)


def _evaluate_forbid_ast_core(normalized_ast: NormalizedAST, forbid_spec: dict[str, Any], *, rule_id: Optional[str] = None, allow_map: Optional[Mapping[int, List[Dict[str, Any]]]] = None) -> Tuple[list[str], list[dict[str, Any]]]:
    if normalized_ast is None or not forbid_spec or not isinstance(forbid_spec, dict):
        return [], []
    violations, overrides, allows = [], [], allow_map or {}
    fp = str(getattr(normalized_ast, "file_path", "") or "")
    parsed_imports, imported_qual_map, aliases = [], {}, {}
    for imp in getattr(normalized_ast, "imports", ()) or ():
        src, syms = _extract_import_tuple(imp)
        for name, originals in _import_aliases(imp).items():
            for orig in originals:
                _add_binding(aliases, name, orig)
        parsed_imports.append((imp, (src, syms)))
        for sym in syms if src else ():
            if sym and sym != src:
                _add_binding(imported_qual_map, sym, f"{src}.{sym}")

    def _record_hits(items: list[Any], kind: str, pat: str, label: str) -> None:
        if not items:
            return
        unoverridden = False
        for item in items:
            ln = _line_of(item)
            reason = _allow_reason_for_line(allows, ln, rule_id)
            if reason is not None and ln is not None:
                overrides.append({"rule": rule_id or "", "file": fp, "line": ln, "kind": kind, "pattern": pat, "reason": reason, "status": "contested"})
            else:
                unoverridden = True
        if unoverridden:
            violations.append(f"Forbidden {label} '{pat}' matched rule forbid_ast.{kind}")

    for raw_mod in forbid_spec["imports"] if isinstance(forbid_spec.get("imports"), (list, tuple, set)) else ():
        mod = _normalize_ast_token(raw_mod) if isinstance(raw_mod, str) else ""
        if mod:
            _record_hits([r for r, t in parsed_imports if _match_ImportNode_against_pattern(t, mod)], "imports", mod, "import")

    raw_call_sites, call_index = getattr(normalized_ast, "call_sites", ()) or (), _SpellingIndex(imported_qual_map, aliases, qualify_heads=True)
    for raw_call in forbid_spec["calls"] if isinstance(forbid_spec.get("calls"), (list, tuple, set)) else ():
        call = _normalize_ast_token(raw_call) if isinstance(raw_call, str) else ""
        if call:
            _record_hits([s for s in raw_call_sites if _call_target(s) and call_index.matches(_call_target(s), _normalize_ast_token(call))], "calls", call, "call")

    forbidden_decs = forbid_spec.get("decorators")
    if not isinstance(forbidden_decs, (list, tuple, set)) or not forbidden_decs:
        return violations, overrides
    try:
        raw_decs: list[Any] = list(getattr(normalized_ast, "decorators", None) or ())
    except Exception as exc:
        raise ASTExtractionError(str(fp), f"{type(exc).__name__}: {exc}") from exc
    meta = getattr(normalized_ast, "metadata", None)
    if isinstance(meta, dict) and isinstance(meta.get("decorators"), (list, tuple, set)):
        raw_decs.extend(meta["decorators"])
    for defn in getattr(normalized_ast, "definitions", ()) or ():
        d_decs = getattr(defn, "decorators", None) if not isinstance(defn, dict) else defn.get("decorators")
        if isinstance(d_decs, (list, tuple, set)):
            raw_decs.extend(d_decs)
    if not raw_decs and isinstance(fp, str) and fp.endswith(".py") and os.path.isfile(fp):
        try:
            raw_decs.extend(_extract_python_decorators_from_file(fp))
        except Exception as exc:
            raise ASTExtractionError(fp, f"{type(exc).__name__}: {exc}") from exc
    decorator_names = list(dict.fromkeys(n for n in map(_decorator_name, raw_decs) if n))
    decorator_index = _SpellingIndex(imported_qual_map, aliases, qualify_heads=False)
    for raw_dec in forbidden_decs:
        dec = _decorator_pattern(raw_dec) if isinstance(raw_dec, str) else ""
        if dec and any(decorator_index.matches(name, _decorator_pattern(dec)) for name in decorator_names):
            violations.append(f"Forbidden decorator '{dec}' matched rule forbid_ast.decorators")
    return violations, overrides


def evaluate_forbid_ast(normalized_ast: NormalizedAST, forbid_spec: dict[str, Any]) -> list[str]:
    """Evaluate a NormalizedAST against declarative forbid_ast constraints (syntactic only, no regex).
    Aliased imports are judged as their plain form plus literal alias text; literal strings passed
    to ``__import__`` or ``importlib.import_module`` count as imports. Syntactic only, so out of
    scope: computed module names, ``getattr``/``globals`` and subscript access, ``f = subprocess.run``
    rebinding by assignment, functions as values, ``from x import *``, and relative ``__import__``.
    """
    return _evaluate_forbid_ast_core(normalized_ast, forbid_spec)[0]


def evaluate_forbid_ast_with_overrides(normalized_ast: NormalizedAST, forbid_spec: dict[str, Any], *, rule_id: Optional[str] = None, source: Optional[str] = None) -> Tuple[list[str], list[dict[str, Any]]]:
    allow_map = _resolve_allow_map(normalized_ast, source=source) if normalized_ast is not None else {}
    return (evaluate_forbid_ast(normalized_ast, forbid_spec), []) if not allow_map else _evaluate_forbid_ast_core(normalized_ast, forbid_spec, rule_id=rule_id, allow_map=allow_map)


def extract_normalized_ast(file_path: Union[str, Path], workspace_root: Optional[Union[str, Path]] = None, code: Optional[str] = None, ast_runner: Any = None, confine_root: Optional[Union[str, Path]] = None) -> Optional[NormalizedAST]:
    from aegis_core.ast.drivers.python import parse_python_ast, read_python_source
    path_str, ext = str(file_path), os.path.splitext(str(file_path))[1].lower()
    try:
        if code is not None or ext == ".py":
            source_text = code if code is not None else read_python_source(path_str)
            tree, norm_ast = ast.parse(source_text, filename=path_str), parse_python_ast(source_text, file_path=path_str)
            decs, allows = _extract_python_decorators_from_tree(tree), parse_allow_comments(source_text)
            if decs or allows:
                meta = {**norm_ast.metadata, **({"decorators": list(decs)} if decs else {}), **({"allow_comments": allows} if allows else {})}
                object.__setattr__(norm_ast, "metadata", meta)
            return norm_ast
        if ast_runner is None:
            from aegis_core.ast.runner import ASTDriverRunner
            ast_runner = ASTDriverRunner()
        if not ast_runner.registry.resolve_driver(ext, workspace_root=workspace_root):
            return None
        return ast_runner.parse_file(path_str, workspace_root=workspace_root, **({"confine_root": confine_root} if confine_root is not None else {}))
    except Exception as exc:
        raise ASTExtractionError(path_str, f"{type(exc).__name__}: {exc}") from exc

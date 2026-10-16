"""AST policy evaluation, extraction, and planned-symbol synthesis."""
from __future__ import annotations

import ast
import io
import os
from pathlib import Path
import re
import tokenize
from typing import Any, Dict, List, Mapping, Optional, Tuple, Union

from aegis_core.errors import AegisError
from aegis_core.ast.schema import (
    NormalizedAST,
    _SpellingIndex,
    _add_binding,
    _call_target,
    _decorator_name,
    _decorator_pattern,
    _extract_import_tuple,
    _extract_python_decorators_from_file,
    _extract_python_decorators_from_tree,
    _import_aliases,
    _normalize_ast_token,
)

__all__ = [
    "ASTExtractionError",
    "_match_ImportNode_against_pattern",
    "evaluate_forbid_ast",
    "evaluate_forbid_ast_with_overrides",
    "extract_normalized_ast",
    "parse_allow_comments",
]

_ALLOW_COMMENT_RE = re.compile(
    r"#\s*aegis:\s*allow(?:\[([^\]]+)\])?(?:\s*[:\-]?\s*(.*))?$",
    re.IGNORECASE,
)


def parse_allow_comments(source: str) -> Dict[int, List[Dict[str, Any]]]:
    """Extract inline ``# aegis: allow`` comments keyed by 1-based line number."""
    if not source or "aegis" not in source.lower():
        return {}
    by_line: Dict[int, List[Dict[str, Any]]] = {}
    try:
        for tok_type, tok_str, (srow, _scol), _end, _line in tokenize.generate_tokens(
            io.StringIO(source).readline
        ):
            if tok_type != tokenize.COMMENT:
                continue
            match = _ALLOW_COMMENT_RE.search(tok_str)
            if not match:
                continue
            raw_rules, raw_reason = match.group(1), match.group(2)
            rules = (
                {r.strip() for r in raw_rules.split(",") if r.strip()}
                if raw_rules
                else None
            )
            by_line.setdefault(int(srow), []).append(
                {"rules": rules, "reason": (raw_reason or "").strip()}
            )
    except (tokenize.TokenError, IndentationError, SyntaxError):
        for idx, line in enumerate(source.splitlines(), start=1):
            match = _ALLOW_COMMENT_RE.search(line)
            if match:
                raw_rules, raw_reason = match.group(1), match.group(2)
                rules = (
                    {r.strip() for r in raw_rules.split(",") if r.strip()}
                    if raw_rules
                    else None
                )
                by_line.setdefault(idx, []).append(
                    {"rules": rules, "reason": (raw_reason or "").strip()}
                )
    return by_line


def _line_of(item: Any) -> Optional[int]:
    if isinstance(item, Mapping):
        val = item.get("line")
    else:
        val = getattr(item, "line", None)
    return int(val) if isinstance(val, int) and val > 0 else None


def _allow_reason_for_line(
    allow_map: Mapping[int, List[Dict[str, Any]]],
    line: Optional[int],
    rule_id: Optional[str],
) -> Optional[str]:
    if not line or line not in allow_map:
        return None
    for entry in allow_map[line]:
        rules = entry.get("rules")
        if rules is None or not rule_id or rule_id in rules:
            return str(entry.get("reason") or "")
    return None


def _resolve_allow_map(
    normalized_ast: NormalizedAST, source: Optional[str] = None
) -> Dict[int, List[Dict[str, Any]]]:
    meta = getattr(normalized_ast, "metadata", None)
    if isinstance(meta, Mapping) and isinstance(meta.get("allow_comments"), dict):
        return meta["allow_comments"]
    if isinstance(source, str):
        return parse_allow_comments(source)
    fp = getattr(normalized_ast, "file_path", "")
    if isinstance(fp, str) and os.path.isfile(fp):
        try:
            from aegis_core.ast.drivers.python import read_python_source

            text = (
                read_python_source(fp)
                if fp.endswith(".py")
                else Path(fp).read_text(encoding="utf-8", errors="replace")
            )
            return parse_allow_comments(text)
        except Exception:
            return {}
    return {}


class ASTExtractionError(AegisError):
    """A source file could not be parsed, so a forbid_ast rule cannot verify it."""

    def __init__(self, path: str, reason: str):
        super().__init__(f"cannot verify {path}: {reason}", code="AST_UNVERIFIABLE", path=path, reason=reason)


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


def _evaluate_forbid_ast_core(
    normalized_ast: NormalizedAST,
    forbid_spec: dict[str, Any],
    *,
    rule_id: Optional[str] = None,
    allow_map: Optional[Mapping[int, List[Dict[str, Any]]]] = None,
) -> Tuple[list[str], list[dict[str, Any]]]:
    if normalized_ast is None or not forbid_spec or not isinstance(forbid_spec, dict):
        return [], []

    violations: list[str] = []
    overrides: list[dict[str, Any]] = []
    allows = allow_map or {}
    fp = str(getattr(normalized_ast, "file_path", "") or "")

    raw_ast_imports = getattr(normalized_ast, "imports", ()) or ()
    parsed_imports: list[tuple[Any, tuple[str, tuple[str, ...]]]] = []
    # File-global and multi-valued: every binding of a name counts, whatever its scope or
    # order, so rebinding a name (``import json as sp`` after ``import subprocess as sp``)
    # can only add candidates, never hide one.
    imported_qual_map: dict[str, list[str]] = {}
    aliases: dict[str, list[str]] = {}

    for imp in raw_ast_imports:
        src, syms = _extract_import_tuple(imp)
        for name, originals in _import_aliases(imp).items():
            for orig in originals:
                _add_binding(aliases, name, orig)
        parsed_imports.append((imp, (src, syms)))
        if src:
            for sym in syms:
                if sym and sym != src:
                    _add_binding(imported_qual_map, sym, f"{src}.{sym}")

    forbidden_imports = forbid_spec.get("imports")
    if isinstance(forbidden_imports, (list, tuple, set)):
        for raw_mod in forbidden_imports:
            if not isinstance(raw_mod, str):
                continue
            mod = _normalize_ast_token(raw_mod)
            if not mod:
                continue
            matching_imps = [
                raw_imp
                for raw_imp, imp_tuple in parsed_imports
                if _match_ImportNode_against_pattern(imp_tuple, mod)
            ]
            if not matching_imps:
                continue
            unoverridden = False
            for raw_imp in matching_imps:
                line = _line_of(raw_imp)
                reason = _allow_reason_for_line(allows, line, rule_id)
                if reason is not None and line is not None:
                    overrides.append(
                        {
                            "rule": rule_id or "",
                            "file": fp,
                            "line": line,
                            "kind": "imports",
                            "pattern": mod,
                            "reason": reason,
                            "status": "contested",
                        }
                    )
                else:
                    unoverridden = True
            if unoverridden:
                violations.append(f"Forbidden import '{mod}' matched rule forbid_ast.imports")

    # NormalizedAST.calls is derived from call_sites: the targets are read from the field alone.
    raw_call_sites = getattr(normalized_ast, "call_sites", ()) or ()
    call_index = _SpellingIndex(imported_qual_map, aliases, qualify_heads=True)

    forbidden_calls = forbid_spec.get("calls")
    if isinstance(forbidden_calls, (list, tuple, set)):
        for raw_call in forbidden_calls:
            if not isinstance(raw_call, str):
                continue
            call = _normalize_ast_token(raw_call)
            if not call:
                continue
            norm_call = _normalize_ast_token(call)
            matching_sites = [
                site
                for site in raw_call_sites
                if _call_target(site) and call_index.matches(_call_target(site), norm_call)
            ]
            if not matching_sites:
                continue
            unoverridden = False
            for site in matching_sites:
                line = _line_of(site)
                reason = _allow_reason_for_line(allows, line, rule_id)
                if reason is not None and line is not None:
                    overrides.append(
                        {
                            "rule": rule_id or "",
                            "file": fp,
                            "line": line,
                            "kind": "calls",
                            "pattern": call,
                            "reason": reason,
                            "status": "contested",
                        }
                    )
                else:
                    unoverridden = True
            if unoverridden:
                violations.append(f"Forbidden call '{call}' matched rule forbid_ast.calls")

    forbidden_decs = forbid_spec.get("decorators")
    if not isinstance(forbidden_decs, (list, tuple, set)) or not forbidden_decs:
        return violations, overrides

    # NormalizedAST.decorators, and the fallback below for other AST objects, read file_path
    # when the AST carries no decorators: an unreadable file is not "no decorators".
    try:
        raw_decs_sources: list[Any] = list(getattr(normalized_ast, "decorators", None) or ())
    except Exception as exc:
        raise ASTExtractionError(str(fp), f"{type(exc).__name__}: {exc}") from exc
    meta = getattr(normalized_ast, "metadata", None)
    if isinstance(meta, dict) and isinstance(meta.get("decorators"), (list, tuple, set)):
        raw_decs_sources.extend(meta["decorators"])
    for defn in getattr(normalized_ast, "definitions", ()) or ():
        defn_decs = getattr(defn, "decorators", None)
        if isinstance(defn_decs, (list, tuple, set)):
            raw_decs_sources.extend(defn_decs)
        elif isinstance(defn, dict) and isinstance(defn.get("decorators"), (list, tuple, set)):
            raw_decs_sources.extend(defn["decorators"])
    if not raw_decs_sources and isinstance(fp, str) and fp.endswith(".py") and os.path.isfile(fp):
        try:
            raw_decs_sources.extend(_extract_python_decorators_from_file(fp))
        except Exception as exc:
            raise ASTExtractionError(fp, f"{type(exc).__name__}: {exc}") from exc

    decorator_names = list(dict.fromkeys(n for n in map(_decorator_name, raw_decs_sources) if n))
    decorator_index = _SpellingIndex(imported_qual_map, aliases, qualify_heads=False)
    for raw_dec in forbidden_decs:
        if not isinstance(raw_dec, str):
            continue
        dec = _decorator_pattern(raw_dec)
        if not dec:
            continue
        if any(decorator_index.matches(name, _decorator_pattern(dec)) for name in decorator_names):
            violations.append(f"Forbidden decorator '{dec}' matched rule forbid_ast.decorators")

    return violations, overrides


def evaluate_forbid_ast(
    normalized_ast: NormalizedAST,
    forbid_spec: dict[str, Any],
) -> list[str]:
    """Evaluate a NormalizedAST against declarative forbid_ast constraints.

    Aliased imports are judged as their plain form (``sp.run()`` after ``import subprocess as
    sp`` as ``subprocess.run()``; Rust ``Cmd::new`` after ``use std::process::Command as Cmd``
    as ``Command::new``) plus the literal alias text, against every binding of a name in the
    file. A module named by literal strings (``'subprocess'``, ``'sub' + 'process'``,
    ``f'subprocess'``, or a relative name with a literal package) passed to ``__import__``,
    ``builtins.__import__``, ``__builtins__.__import__`` or ``importlib.import_module``
    (however imported, positional or by keyword) is an import, and
    ``__import__("os").system()`` a call.

    Syntactic only, so out of scope: computed module names (a variable or an f-string field),
    ``getattr``/``globals`` access and subscript access (``__builtins__['__import__']``),
    ``f = subprocess.run`` rebinding by assignment, a function passed as a value
    (``map(subprocess.run, ...)``), ``from x import *``, and the package a relative
    ``__import__(name, ..., level)`` resolves against (its literal name is reported as written).

    Raises ASTExtractionError when decorator patterns must be checked against ``file_path``
    on disk (the AST carries no decorators) and that file cannot be read or parsed.
    """
    violations, _overrides = _evaluate_forbid_ast_core(normalized_ast, forbid_spec)
    return violations


def evaluate_forbid_ast_with_overrides(
    normalized_ast: NormalizedAST,
    forbid_spec: dict[str, Any],
    *,
    rule_id: Optional[str] = None,
    source: Optional[str] = None,
) -> Tuple[list[str], list[dict[str, Any]]]:
    """Evaluate a NormalizedAST against declarative ``forbid_ast`` constraints, returning
    ``(unoverridden_violations, contested_overrides)``."""
    allow_map = _resolve_allow_map(normalized_ast, source=source) if normalized_ast is not None else {}
    if not allow_map:
        return evaluate_forbid_ast(normalized_ast, forbid_spec), []
    return _evaluate_forbid_ast_core(
        normalized_ast, forbid_spec, rule_id=rule_id, allow_map=allow_map
    )


def extract_normalized_ast(
    file_path: Union[str, Path],
    workspace_root: Optional[Union[str, Path]] = None,
    code: Optional[str] = None,
    ast_runner: Any = None,
    confine_root: Optional[Union[str, Path]] = None,
) -> Optional[NormalizedAST]:
    """Extract a NormalizedAST (including Python decorators) from a source file or code string.

    Returns None only when no AST driver handles the file type (forbid_ast does not apply);
    any read, decode, parse or driver failure raises ASTExtractionError so callers fail closed.
    """
    from aegis_core.ast.drivers.python import parse_python_ast, read_python_source

    path_str = str(file_path)
    ext = os.path.splitext(path_str)[1].lower()

    try:
        if code is not None or ext == ".py":
            source_text = code if code is not None else read_python_source(path_str)
            # Parse here first so a syntax error surfaces as itself, not the driver's wrapper.
            tree = ast.parse(source_text, filename=path_str)
            norm_ast = parse_python_ast(source_text, file_path=path_str)
            decs = _extract_python_decorators_from_tree(tree)
            allows = parse_allow_comments(source_text)
            if decs or allows:
                meta = dict(norm_ast.metadata)
                if decs:
                    meta["decorators"] = list(decs)
                if allows:
                    meta["allow_comments"] = allows
                object.__setattr__(norm_ast, "metadata", meta)
            return norm_ast

        if ast_runner is None:
            from aegis_core.ast.runner import ASTDriverRunner
            ast_runner = ASTDriverRunner()
        if not ast_runner.registry.resolve_driver(ext, workspace_root=workspace_root):
            return None
        # Only the index snapshot needs confine_root; other runners keep the two-argument call.
        extra = {"confine_root": confine_root} if confine_root is not None else {}
        return ast_runner.parse_file(path_str, workspace_root=workspace_root, **extra)
    except Exception as exc:
        raise ASTExtractionError(path_str, f"{type(exc).__name__}: {exc}") from exc

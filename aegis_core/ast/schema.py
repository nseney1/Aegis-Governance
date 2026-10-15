"""Normalized AST data contracts and serialization schemas."""
from __future__ import annotations

from dataclasses import dataclass, field
import ast
import json
import os
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

__all__ = [
    "DefinitionNode",
    "SymbolDef",
    "CallSiteNode",
    "ImportNode",
    "MutationPoint",
    "NormalizedAST",
]


def _normalize_ast_token(token: str) -> str:
    """Normalize trigger/symbol identifier by stripping leading '@', trailing '()', and whitespace."""
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
                    norm = _normalize_ast_token(dec_name)
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
        return _extract_python_decorators_from_tree(ast.parse(source, filename=file_path))
    except Exception:
        return ()


@dataclass(frozen=True)
class DefinitionNode:
    """Represents a declared symbol (function, method, class, or constant)."""

    name: str
    kind: str = "function"
    line: int = 1
    is_exported: bool = False
    class_name: Optional[str] = None
    decorators: Tuple[str, ...] = ()

    @property
    def is_method(self) -> bool:
        return self.kind == "method" or bool(self.class_name)

    def to_dict(self) -> Dict[str, Any]:
        res: Dict[str, Any] = {
            "name": self.name,
            "kind": self.kind,
            "line": self.line,
            "is_exported": self.is_exported,
            "class_name": self.class_name,
        }
        if self.decorators:
            res["decorators"] = list(self.decorators)
        return res

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> DefinitionNode:
        raw_decs = data.get("decorators") or ()
        return cls(
            name=str(data["name"]),
            kind=str(data.get("kind", "function")),
            line=int(data.get("line", 1)),
            is_exported=bool(data.get("is_exported", False)),
            class_name=str(data["class_name"]) if data.get("class_name") else None,
            decorators=tuple(str(d) for d in raw_decs),
        )


SymbolDef = DefinitionNode


@dataclass(frozen=True)
class CallSiteNode:
    """Represents an invocation of a target identifier or member expression."""
    target: str
    line: int = 1
    caller_scope: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {"target": self.target, "line": self.line, "caller_scope": self.caller_scope}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> CallSiteNode:
        return cls(
            target=str(data["target"]),
            line=int(data.get("line", 1)),
            caller_scope=str(data["caller_scope"]) if data.get("caller_scope") else None,
        )


@dataclass(frozen=True)
class ImportNode:
    """Represents an external or sibling module dependency.

    ``imported_symbols`` holds the names the import binds in the importing scope.
    ``aliases`` holds one ``(bound_name, original_name)`` pair per ``as`` rebinding:
    ``import os.path as osp`` -> ``("osp", "os.path")``; ``from os import path as p``
    -> ``("p", "path")``. Policy checks use it to judge the aliased form exactly like
    the plain form, so renaming an import cannot hide a forbidden API.
    """

    source: str
    imported_symbols: Tuple[str, ...] = ()
    line: int = 1
    is_type_only: bool = False
    aliases: Tuple[Tuple[str, str], ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        res: Dict[str, Any] = {
            "source": self.source,
            "imported_symbols": list(self.imported_symbols),
            "line": self.line,
            "is_type_only": self.is_type_only,
        }
        # Omitted when empty so plain imports serialize exactly as before aliases existed.
        if self.aliases:
            res["aliases"] = [list(pair) for pair in self.aliases]
        return res

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ImportNode:
        source_val = data.get("source") if "source" in data else data.get("module", "")
        symbols = data.get("imported_symbols") if "imported_symbols" in data else data.get("imported_names", ())
        raw_aliases = data.get("aliases") or ()
        if isinstance(raw_aliases, Mapping):
            raw_aliases = raw_aliases.items()
        return cls(
            source=str(source_val),
            imported_symbols=tuple(str(s) for s in symbols),
            line=int(data.get("line", 1)),
            is_type_only=bool(data.get("is_type_only", False)),
            aliases=tuple((str(bound), str(orig)) for bound, orig in raw_aliases),
        )


@dataclass(frozen=True)
class MutationPoint:
    """Location and replacement candidate for mutation testing."""

    line: int
    col: int
    original_op: str
    replacement_op: str
    mutation_type: str = "operator"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "line": self.line,
            "col": self.col,
            "original_op": self.original_op,
            "replacement_op": self.replacement_op,
            "mutation_type": self.mutation_type,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> MutationPoint:
        orig = data.get("original_op") if "original_op" in data else data.get("original", "")
        rep = data.get("replacement_op") if "replacement_op" in data else data.get("mutated", "")
        col = data.get("col", data.get("column", 0))
        m_type = data.get("mutation_type") if "mutation_type" in data else data.get("kind", "operator")
        return cls(
            line=int(data["line"]),
            col=int(col),
            original_op=str(orig),
            replacement_op=str(rep),
            mutation_type=str(m_type),
        )


@dataclass(frozen=True, init=False)
class NormalizedAST:
    """Language-agnostic Normalized AST representation."""

    file_path: str = "<unknown>"
    language: str = "python"
    definitions: Tuple[DefinitionNode, ...] = ()
    call_sites: Tuple[CallSiteNode, ...] = ()
    imports: Tuple[ImportNode, ...] = ()
    mutation_points: Tuple[MutationPoint, ...] = ()
    version: str = "1.0"
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __init__(
        self,
        file_path: str = "<unknown>",
        language: str = "python",
        definitions: Sequence[Any] = (),
        call_sites: Sequence[Any] = (),
        imports: Sequence[Any] = (),
        mutation_points: Sequence[Any] = (),
        version: str = "1.0",
        metadata: Optional[Mapping[str, Any]] = None,
        *,
        symbols: Optional[Sequence[Any]] = None,
        calls: Optional[Sequence[Any]] = None,
        decorators: Optional[Sequence[Any]] = None,
    ) -> None:
        if not file_path:
            raise ValueError("file_path cannot be empty")
        if not language:
            raise ValueError("language cannot be empty")

        raw_defs = symbols if (symbols is not None and not definitions) else definitions
        coerced_defs: List[DefinitionNode] = []
        for d in raw_defs or ():
            if isinstance(d, DefinitionNode):
                coerced_defs.append(d)
            elif isinstance(d, Mapping):
                coerced_defs.append(DefinitionNode.from_dict(d))
            elif isinstance(d, str):
                coerced_defs.append(DefinitionNode(name=_normalize_ast_token(d)))
            else:
                coerced_defs.append(d)

        raw_calls = calls if (calls is not None and not call_sites) else call_sites
        coerced_calls: List[CallSiteNode] = []
        for c in raw_calls or ():
            if isinstance(c, CallSiteNode):
                coerced_calls.append(c)
            elif isinstance(c, str):
                coerced_calls.append(CallSiteNode(target=_normalize_ast_token(c)))
            elif isinstance(c, Mapping):
                coerced_calls.append(CallSiteNode.from_dict(c))
            else:
                coerced_calls.append(c)

        coerced_imports: List[ImportNode] = []
        for imp in imports or ():
            if isinstance(imp, ImportNode):
                coerced_imports.append(imp)
            elif isinstance(imp, str):
                norm = _normalize_ast_token(imp)
                coerced_imports.append(ImportNode(source=norm, imported_symbols=(norm.split(".")[-1],) if norm else ()))
            elif isinstance(imp, Mapping):
                coerced_imports.append(ImportNode.from_dict(imp))
            else:
                coerced_imports.append(imp)

        coerced_mutations: List[MutationPoint] = []
        for m in mutation_points or ():
            if isinstance(m, MutationPoint):
                coerced_mutations.append(m)
            elif isinstance(m, Mapping):
                coerced_mutations.append(MutationPoint.from_dict(m))
            else:
                coerced_mutations.append(m)

        meta_dict: Dict[str, Any] = dict(metadata) if metadata else {}
        if decorators is not None:
            meta_dict["decorators"] = [_normalize_ast_token(d) if isinstance(d, str) else str(d) for d in decorators]

        object.__setattr__(self, "file_path", file_path)
        object.__setattr__(self, "language", language)
        object.__setattr__(self, "definitions", tuple(coerced_defs))
        object.__setattr__(self, "call_sites", tuple(coerced_calls))
        object.__setattr__(self, "imports", tuple(coerced_imports))
        object.__setattr__(self, "mutation_points", tuple(coerced_mutations))
        object.__setattr__(self, "version", version)
        object.__setattr__(self, "metadata", meta_dict)

    @property
    def symbols(self) -> Tuple[DefinitionNode, ...]:
        return self.definitions

    @property
    def calls(self) -> Tuple[str, ...]:
        return tuple(c.target if hasattr(c, "target") else str(c) for c in self.call_sites)

    @property
    def decorators(self) -> Tuple[str, ...]:
        meta_decs = self.metadata.get("decorators") if isinstance(self.metadata, dict) else None
        if meta_decs is not None:
            return tuple(_normalize_ast_token(str(d)) for d in meta_decs if d)
        def_decs: List[str] = []
        for d in self.definitions:
            for dec in getattr(d, "decorators", ()) or ():
                norm = _normalize_ast_token(str(dec))
                if norm and norm not in def_decs:
                    def_decs.append(norm)
        return tuple(def_decs) if def_decs else _extract_python_decorators_from_file(self.file_path)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "file_path": self.file_path,
            "language": self.language,
            "definitions": [d.to_dict() for d in self.definitions],
            "call_sites": [c.to_dict() for c in self.call_sites],
            "imports": [i.to_dict() for i in self.imports],
            "mutation_points": [m.to_dict() for m in self.mutation_points],
            "metadata": dict(self.metadata),
        }

    def to_json(self, indent: Optional[int] = None) -> str:
        return json.dumps(self.to_dict(), indent=indent)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> NormalizedAST:
        return cls(
            file_path=str(data["file_path"]),
            language=str(data["language"]),
            definitions=tuple(DefinitionNode.from_dict(d) for d in data.get("definitions", ())),
            call_sites=tuple(CallSiteNode.from_dict(c) for c in data.get("call_sites", ())),
            imports=tuple(ImportNode.from_dict(i) for i in data.get("imports", ())),
            mutation_points=tuple(
                MutationPoint.from_dict(m)
                for m in (data.get("mutation_points") if "mutation_points" in data else data.get("mutations", ()))
            ),
            version=str(data.get("version", "1.0")),
            metadata=dict(data.get("metadata", {})),
        )

    @classmethod
    def from_json(cls, json_str: str) -> NormalizedAST:
        return cls.from_dict(json.loads(json_str))

    def find_definition(self, name: str) -> Optional[DefinitionNode]:
        for d in self.definitions:
            if d.name == name:
                return d
        return None

    def get_exported_definitions(self) -> List[DefinitionNode]:
        return [d for d in self.definitions if d.is_exported]

    def get_calls_in_scope(self, caller_scope: str) -> List[CallSiteNode]:
        return [c for c in self.call_sites if c.caller_scope == caller_scope]

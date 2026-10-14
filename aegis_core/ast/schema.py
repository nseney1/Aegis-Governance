"""Normalized AST data contracts and serialization schemas.

Defines the language-agnostic Intermediate Representation (IR) for Layer 1 static
analysis, decoupling checkers (call graph, import guard, mutation testing) from
Python-specific AST traversal.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

__all__ = [
    "DefinitionNode",
    "CallSiteNode",
    "ImportNode",
    "MutationPoint",
    "NormalizedAST",
]


@dataclass(frozen=True)
class DefinitionNode:
    """Represents a declared symbol (function, method, class, or constant)."""

    name: str
    kind: str = "function"  # "function", "method", "class", "constant"
    line: int = 1
    is_exported: bool = False
    class_name: Optional[str] = None

    @property
    def is_method(self) -> bool:
        return self.kind == "method" or bool(self.class_name)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "line": self.line,
            "is_exported": self.is_exported,
            "class_name": self.class_name,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> DefinitionNode:
        return cls(
            name=str(data["name"]),
            kind=str(data.get("kind", "function")),
            line=int(data.get("line", 1)),
            is_exported=bool(data.get("is_exported", False)),
            class_name=str(data["class_name"]) if data.get("class_name") else None,
        )


@dataclass(frozen=True)
class CallSiteNode:
    """Represents an invocation of a target identifier or member expression."""

    target: str
    line: int = 1
    caller_scope: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "target": self.target,
            "line": self.line,
            "caller_scope": self.caller_scope,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> CallSiteNode:
        return cls(
            target=str(data["target"]),
            line=int(data.get("line", 1)),
            caller_scope=str(data["caller_scope"]) if data.get("caller_scope") else None,
        )


@dataclass(frozen=True)
class ImportNode:
    """Represents an external or sibling module dependency."""

    source: str
    imported_symbols: Tuple[str, ...] = ()
    line: int = 1
    is_type_only: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source": self.source,
            "imported_symbols": list(self.imported_symbols),
            "line": self.line,
            "is_type_only": self.is_type_only,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ImportNode:
        source_val = data.get("source") if "source" in data else data.get("module", "")
        symbols = data.get("imported_symbols") if "imported_symbols" in data else data.get("imported_names", ())
        return cls(
            source=str(source_val),
            imported_symbols=tuple(str(s) for s in symbols),
            line=int(data.get("line", 1)),
            is_type_only=bool(data.get("is_type_only", False)),
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


@dataclass(frozen=True)
class NormalizedAST:
    """Language-agnostic Normalized AST representation."""

    file_path: str
    language: str
    definitions: Tuple[DefinitionNode, ...] = ()
    call_sites: Tuple[CallSiteNode, ...] = ()
    imports: Tuple[ImportNode, ...] = ()
    mutation_points: Tuple[MutationPoint, ...] = ()
    version: str = "1.0"
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.file_path:
            raise ValueError("file_path cannot be empty")
        if not self.language:
            raise ValueError("language cannot be empty")

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

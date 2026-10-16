"""Unified polymorphic document model representing Aegis Rules or Skills."""
from __future__ import annotations

import collections.abc
from typing import Any, Dict, Iterator, List, Optional


class AegisDocument(collections.abc.Mapping):
    """Unified polymorphic document model representing Rules or Skills.

    Implements collections.abc.Mapping for transparent dictionary drop-in compatibility.
    """

    def __init__(
        self,
        metadata: Dict[str, Any],
        body: str = "",
        kind: Optional[str] = None,
        source_path: Optional[str] = None,
    ) -> None:
        self._metadata: Dict[str, Any] = dict(metadata)
        self._body: str = body
        self._source_path: Optional[str] = source_path
        self._kind: str = self._resolve_kind(kind)
        self._apply_defaults()

    @property
    def _data(self) -> Dict[str, Any]:
        return self._metadata

    def _resolve_kind(self, explicit_kind: Optional[str]) -> str:
        """The kind passed in, else the frontmatter's ``kind`` (``kind: skill`` marks a
        skill), else ``rule``. No other key makes a skill."""
        if explicit_kind:
            return explicit_kind.strip().lower()
        kind = self._metadata.get("kind")
        if kind:
            return str(kind).strip().lower()
        return "rule"

    def _apply_defaults(self) -> None:
        if self._kind == "rule":
            if "type" not in self._metadata:
                self._metadata["type"] = "advisory"
            if "target_paths" not in self._metadata:
                self._metadata["target_paths"] = []
            if "decay" not in self._metadata:
                self._metadata["decay"] = True

    def __getitem__(self, key: str) -> Any:
        return self._metadata[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._metadata)

    def __len__(self) -> int:
        return len(self._metadata)

    def __contains__(self, key: object) -> bool:
        return key in self._metadata

    def get(self, key: str, default: Any = None) -> Any:
        return self._metadata.get(key, default)

    def keys(self):
        return self._metadata.keys()

    def values(self):
        return self._metadata.values()

    def items(self):
        return self._metadata.items()

    @property
    def metadata(self) -> Dict[str, Any]:
        return self._metadata

    @property
    def body(self) -> str:
        return self._body

    @property
    def kind(self) -> str:
        return self._kind

    @property
    def id(self) -> Optional[str]:
        val = self._metadata.get("id") or self._metadata.get("name")
        return str(val) if val is not None else None

    @property
    def name(self) -> Optional[str]:
        return self.id

    @property
    def type(self) -> Optional[str]:
        val = self._metadata.get("type")
        return str(val) if val is not None else None

    @property
    def enforcement(self) -> Optional[str]:
        val = self._metadata.get("enforcement")
        return str(val) if val is not None else None

    @property
    def target_paths(self) -> List[str]:
        paths = self._metadata.get("target_paths", [])
        return list(paths) if isinstance(paths, (list, tuple)) else []

    @property
    def decay(self) -> bool:
        return bool(self._metadata.get("decay", False))

    @property
    def source_path(self) -> Optional[str]:
        return self._source_path

    def to_dict(self) -> Dict[str, Any]:
        return dict(self._metadata)

    def __repr__(self) -> str:
        return f"AegisDocument(kind={self._kind!r}, id={self.id!r}, keys={list(self._metadata.keys())!r})"


__all__ = ["AegisDocument"]

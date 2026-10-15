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
        if explicit_kind:
            return explicit_kind.strip().lower()
        if str(self._data.get("kind", "")).lower() == "skill":
            return "skill"
        if "kind" in self._metadata and self._metadata["kind"]:
            return str(self._metadata["kind"]).strip().lower()

        cell_types = {
            "wall", "membrane",
            "invariant", "boundary", "trap", "persona", "contract", "gate",
        }
        m_type = str(self._metadata.get("type", "")).lower()
        if m_type in cell_types:
            return "rule"

        if any(k in self._metadata for k in ("tier", "consumes", "produces", "handoff_targets")):
            return "skill"

        return "rule"

    def _apply_defaults(self) -> None:
        if self._kind == "rule":
            if "type" not in self._metadata:
                self._metadata["type"] = "advisory"
            if "target_paths" not in self._metadata:
                self._metadata["target_paths"] = []
            if "decay" not in self._metadata:
                self._metadata["decay"] = True
        elif self._kind == "skill":
            if "tier" not in self._metadata:
                self._metadata["tier"] = "method"
            if "consumes" not in self._metadata:
                self._metadata["consumes"] = []
            if "produces" not in self._metadata:
                self._metadata["produces"] = []
            if "handoff_targets" not in self._metadata:
                self._metadata["handoff_targets"] = []

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
    def tier(self) -> Optional[str]:
        val = self._metadata.get("tier")
        return str(val) if val is not None else None

    @property
    def consumes(self) -> List[str]:
        c = self._metadata.get("consumes", [])
        return list(c) if isinstance(c, (list, tuple)) else []

    @property
    def produces(self) -> List[str]:
        p = self._metadata.get("produces", [])
        return list(p) if isinstance(p, (list, tuple)) else []

    @property
    def handoff_targets(self) -> List[str]:
        h = self._metadata.get("handoff_targets", [])
        return list(h) if isinstance(h, (list, tuple)) else []

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

"""Immutable cell frontmatter metadata schema."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class CellMetadata:
    """Strongly-typed immutable frontmatter model for governance cells."""

    id: str
    type: str
    domain: str
    enforcement: str = "advisory"
    hypothesis: str = ""
    prediction: str = ""
    falsification: str = ""
    tags: tuple[str, ...] = ()
    impact_weight: float = 1.0
    expiry_days: int | None = None
    expiry_sessions: int | None = None
    created: str = ""
    fitness: Mapping[str, Any] | None = None

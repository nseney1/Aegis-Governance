"""Immutable rule frontmatter metadata schema."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from aegis_core.taxonomy import REVIEW_MODES, ReviewMode, normalize_review_mode


@dataclass(frozen=True)
class RuleMetadata:
    """Strongly-typed immutable frontmatter model for governance rules."""

    id: str
    type: str
    domain: str
    enforcement: str = "advisory"
    minimum_mode: str = str(ReviewMode.PATROL)
    hypothesis: str = ""
    prediction: str = ""
    falsification: str = ""
    tags: tuple[str, ...] = ()
    impact_weight: float = 1.0
    expiry_days: int | None = None
    expiry_sessions: int | None = None
    created: str = ""
    fitness: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        normalized = normalize_review_mode(self.minimum_mode, default="")
        if normalized not in REVIEW_MODES:
            raise ValueError(
                f"Invalid minimum_mode '{self.minimum_mode}'. Must be one of {REVIEW_MODES}."
            )
        object.__setattr__(self, "minimum_mode", normalized)


CellMetadata = RuleMetadata

__all__ = ["RuleMetadata", "CellMetadata"]


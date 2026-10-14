"""Immutable lifecycle transition result schema."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TransitionResult:
    """Strongly-typed outcome of a cell state transition (promotion/demotion/adaptation)."""

    cell_id: str
    from_type: str
    to_type: str
    success: bool
    reason: str
    timestamp: str

"""Immutable telemetry signal event schema."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class SignalEvent:
    """Strongly-typed canonical event model for signals.jsonl records."""

    event_id: str
    cell_id: str
    signal_type: str
    score: float
    timestamp: str
    session_id: str = ""
    details: Mapping[str, Any] | None = None

"""Immutable receipt value object schema."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Receipt:
    """Strongly-typed immutable receipt model."""

    receipt_id: str
    session_id: str
    workspace: str
    operation: str
    args_hash: str
    file_digest: str
    cell_digest: str
    created_at: float
    expires_at: float

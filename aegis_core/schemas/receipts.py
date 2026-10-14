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
    cell_digest: str = ""
    created_at: float = 0.0
    expires_at: float = 0.0
    rule_digest: str = ""

    def __post_init__(self) -> None:
        effective = self.rule_digest or self.cell_digest
        object.__setattr__(self, "rule_digest", effective)
        object.__setattr__(self, "cell_digest", effective)


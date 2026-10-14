"""Soma error hierarchy.

All soma-specific exceptions inherit from SomaError.
Engine/pipeline code that cannot raise uses Result[T] instead.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, Optional, TypeVar

T = TypeVar('T')


from aegis_core.errors import AegisError, SomaError


__all__ = [
    "AegisError",
    "SomaError",
    "RuleParseError",
    "CellParseError",
    "RuleNotFoundError",
    "CellNotFoundError",
    "RulePathTraversalError",
    "CellPathTraversalError",
    "FitnessError",
    "ScoringError",
    "Result",
]


class RuleParseError(AegisError):
    """Raised when a rule file cannot be parsed (missing/malformed frontmatter)."""


CellParseError = RuleParseError


class RuleNotFoundError(AegisError):
    """Raised when a rule file does not exist."""


CellNotFoundError = RuleNotFoundError


class RulePathTraversalError(AegisError):
    """Raised when a rule_id or path attempts directory traversal."""


CellPathTraversalError = RulePathTraversalError


class FitnessError(SomaError):
    """Raised when fitness computation encounters invalid data."""


class ScoringError(SomaError):
    """Raised when scoring computation encounters invalid inputs."""


@dataclass
class Result(Generic[T]):
    """Structured result for engine/pipeline functions that cannot raise.

    Usage:
        result = some_engine_fn(...)
        if result.ok:
            use(result.value)
        else:
            log(result.error)
    """
    value: Optional[T]
    error: Optional[SomaError] = None

    @property
    def ok(self) -> bool:
        return self.error is None

"""Aegis error hierarchy.

All Aegis-specific exceptions inherit from AegisError.
Engine/pipeline code that cannot raise uses Result[T] instead.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, Optional, TypeVar

T = TypeVar('T')


from aegis_core.errors import AegisError


__all__ = [
    "AegisError",
    "RuleParseError",
    "RuleNotFoundError",
    "RulePathTraversalError",
    "FitnessError",
    "ScoringError",
    "Result",
]


class RuleParseError(AegisError):
    """Raised when a rule file cannot be parsed (missing/malformed frontmatter)."""


class RuleNotFoundError(AegisError):
    """Raised when a rule file does not exist."""


class RulePathTraversalError(AegisError):
    """Raised when a rule_id or path attempts directory traversal."""


class FitnessError(AegisError):
    """Raised when fitness computation encounters invalid data."""


class ScoringError(AegisError):
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
    error: Optional[AegisError] = None

    @property
    def ok(self) -> bool:
        return self.error is None

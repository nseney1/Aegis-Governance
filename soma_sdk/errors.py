"""Soma error hierarchy.

All soma-specific exceptions inherit from SomaError.
Engine/pipeline code that cannot raise uses Result[T] instead.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, Optional, TypeVar

T = TypeVar('T')


from soma_core.errors import SomaError


__all__ = [
    "SomaError",
    "AegisError",
    "CellParseError",
    "RuleParseError",
    "CellNotFoundError",
    "RuleNotFoundError",
    "CellPathTraversalError",
    "RulePathTraversalError",
    "FitnessError",
    "ScoringError",
    "Result",
]


class CellParseError(SomaError):
    """Raised when a cell file cannot be parsed (missing/malformed frontmatter)."""


RuleParseError = CellParseError


class CellNotFoundError(SomaError):
    """Raised when a cell file does not exist."""


RuleNotFoundError = CellNotFoundError


class CellPathTraversalError(SomaError):
    """Raised when a cell_id or path attempts directory traversal."""


RulePathTraversalError = CellPathTraversalError
AegisError = SomaError


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

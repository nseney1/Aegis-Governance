"""Standardized typed exception hierarchy for Aegis-Governance."""
from __future__ import annotations

from typing import Any


class AegisError(Exception):
    """Root domain exception for all Aegis operations."""

    def __init__(self, message: str = "", code: str = "ERR_AEGIS", **kwargs: Any) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        for k, v in kwargs.items():
            setattr(self, k, v)

    def __str__(self) -> str:
        return self.message if self.message else super().__str__()


class AegisValidationError(AegisError, ValueError):
    """Raised when data validation fails against Aegis contracts or schemas."""

    def __init__(self, message: str = "", code: str = "VALIDATION_ERROR", **kwargs: Any) -> None:
        super().__init__(message, code=code, **kwargs)


class RuleCorruptError(AegisError):
    """Raised when a rule frontmatter or body is malformed or unparseable."""

    def __init__(
        self,
        message: str = "",
        cell_id: str | None = None,
        rule_id: str | None = None,
        code: str = "RULE_CORRUPT",
        **kwargs: Any,
    ) -> None:
        actual_id = rule_id or cell_id
        super().__init__(message, code=code, cell_id=actual_id, rule_id=actual_id, **kwargs)
        self.cell_id = actual_id
        self.rule_id = actual_id


class RuleNotFoundError(AegisError):
    """Raised when a rule file does not exist."""


class RuleParseError(AegisError):
    """Raised when a rule file cannot be parsed (missing or malformed frontmatter)."""


class LockTimeoutError(AegisError, TimeoutError):
    """Raised when a workspace lock cannot be acquired within the timeout period."""

    def __init__(
        self,
        message: str = "",
        resource: str | None = None,
        code: str = "LOCK_TIMEOUT",
        **kwargs: Any,
    ) -> None:
        super().__init__(message, code=code, resource=resource, **kwargs)
        self.resource = resource


class WorkspaceError(AegisValidationError):
    """Raised when workspace resolution, confinement, or structure fails."""

    def __init__(self, message: str = "", code: str = "ERR_WORKSPACE", **kwargs: Any) -> None:
        super().__init__(message, code=code, **kwargs)


class WorkspaceNotFoundError(WorkspaceError):
    """Raised when no valid aegis workspace root can be located."""

    def __init__(
        self,
        message: str = "",
        code: str = "ERR_WORKSPACE_NOT_FOUND",
        **kwargs: Any,
    ) -> None:
        super().__init__(message, code=code, **kwargs)


class PathTraversalError(WorkspaceError):
    """Raised when an untrusted path attempts to escape the confined workspace root."""

    def __init__(
        self,
        message: str = "",
        code: str = "ERR_PATH_TRAVERSAL",
        **kwargs: Any,
    ) -> None:
        super().__init__(message, code=code, **kwargs)


class WorkspaceBareRepoError(WorkspaceError):
    """Raised when attempting to scaffold or initialize in a bare git repository."""

    def __init__(
        self,
        message: str = "",
        code: str = "ERR_WORKSPACE_BARE_REPO",
        **kwargs: Any,
    ) -> None:
        super().__init__(message, code=code, **kwargs)


class NoTestRunnerFoundError(AegisError, RuntimeError):
    """Raised when tests are required but no pytest test runner can be discovered."""

    def __init__(
        self,
        message: str = "No suitable pytest runner found in virtualenv or PATH",
        code: str = "NO_TEST_RUNNER_FOUND",
        **kwargs: Any,
    ) -> None:
        super().__init__(message, code=code, **kwargs)


__all__ = [
    "AegisError",
    "AegisValidationError",
    "LockTimeoutError",
    "NoTestRunnerFoundError",
    "PathTraversalError",
    "RuleCorruptError",
    "WorkspaceBareRepoError",
    "WorkspaceError",
    "WorkspaceNotFoundError",
]



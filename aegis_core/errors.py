"""Standardized typed exception hierarchy for Soma-Governance."""
from __future__ import annotations

from typing import Any


class SomaError(Exception):
    """Root domain exception for all soma operations."""

    def __init__(self, message: str = "", code: str = "ERR_SOMA", **kwargs: Any) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        for k, v in kwargs.items():
            setattr(self, k, v)

    def __str__(self) -> str:
        return self.message if self.message else super().__str__()


class SomaValidationError(SomaError, ValueError):
    """Raised when data validation fails against Soma contracts or schemas."""

    def __init__(self, message: str = "", code: str = "VALIDATION_ERROR", **kwargs: Any) -> None:
        super().__init__(message, code=code, **kwargs)


class CellCorruptError(SomaError):
    """Raised when a cell frontmatter or body is malformed or unparseable."""

    def __init__(
        self,
        message: str = "",
        cell_id: str | None = None,
        code: str = "CELL_CORRUPT",
        **kwargs: Any,
    ) -> None:
        super().__init__(message, code=code, cell_id=cell_id, **kwargs)
        self.cell_id = cell_id


class ReceiptExpiredError(SomaError, KeyError):
    """Raised when a receipt is expired or not found."""

    def __init__(
        self,
        message: str = "",
        receipt_id: str | None = None,
        code: str = "RECEIPT_EXPIRED",
        **kwargs: Any,
    ) -> None:
        super().__init__(message, code=code, receipt_id=receipt_id, **kwargs)
        self.receipt_id = receipt_id


class LockTimeoutError(SomaError, TimeoutError):
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


class WorkspaceError(SomaValidationError):
    """Raised when workspace resolution, confinement, or structure fails."""

    def __init__(self, message: str = "", code: str = "ERR_WORKSPACE", **kwargs: Any) -> None:
        super().__init__(message, code=code, **kwargs)


class WorkspaceNotFoundError(WorkspaceError):
    """Raised when no valid soma workspace root can be located."""

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


class NoTestRunnerFoundError(SomaError, RuntimeError):
    """Raised when tests are required but no pytest test runner can be discovered."""

    def __init__(
        self,
        message: str = "No suitable pytest runner found in virtualenv or PATH",
        code: str = "NO_TEST_RUNNER_FOUND",
        **kwargs: Any,
    ) -> None:
        super().__init__(message, code=code, **kwargs)


class InvalidHandoffPayloadError(SomaValidationError):
    """Raised when an artifact payload violates its typed schema."""

    def __init__(
        self,
        message: str = "",
        code: str = "ERR_INVALID_HANDOFF_PAYLOAD",
        **kwargs: Any,
    ) -> None:
        super().__init__(message, code=code, **kwargs)


class HandoffAuthorizationError(SomaError):
    """Raised when a producer skill/tier lacks authorization to emit an artifact."""

    def __init__(
        self,
        message: str = "",
        code: str = "ERR_HANDOFF_UNAUTHORIZED",
        **kwargs: Any,
    ) -> None:
        super().__init__(message, code=code, **kwargs)


__all__ = [
    "CellCorruptError",
    "HandoffAuthorizationError",
    "InvalidHandoffPayloadError",
    "LockTimeoutError",
    "NoTestRunnerFoundError",
    "PathTraversalError",
    "ReceiptExpiredError",
    "SomaError",
    "SomaValidationError",
    "WorkspaceBareRepoError",
    "WorkspaceError",
    "WorkspaceNotFoundError",
]



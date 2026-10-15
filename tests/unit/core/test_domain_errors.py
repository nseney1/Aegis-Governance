"""Tests for standardized typed AegisError hierarchy (aegis_core.errors)."""
from __future__ import annotations

import pytest

from aegis_core.errors import (
    AegisError,
    AegisValidationError,
    RuleCorruptError,
    LockTimeoutError,
)


class TestDomainErrors:
    """Test suite for typed exception hierarchy and backwards compatibility."""

    def test_soma_error_base(self):
        """All domain exceptions inherit from AegisError."""
        err = AegisError("Base error", code="ERR_BASE")
        assert str(err) == "Base error"
        assert err.code == "ERR_BASE"
        assert isinstance(err, Exception)

    def test_validation_error_is_value_error(self):
        """AegisValidationError inherits from ValueError for backward compatibility."""
        err = AegisValidationError("Invalid value", code="INVALID_VALUE")
        assert isinstance(err, AegisError)
        assert isinstance(err, ValueError)
        assert str(err) == "Invalid value"

    def test_cell_corrupt_error(self):
        """RuleCorruptError provides structured corruption metadata."""
        err = RuleCorruptError("Malformed YAML", cell_id="bad_cell", code="CORRUPT_FRONTMATTER")
        assert isinstance(err, AegisError)
        assert err.cell_id == "bad_cell"
        assert err.code == "CORRUPT_FRONTMATTER"

    def test_lock_timeout_error(self):
        """LockTimeoutError inherits from TimeoutError."""
        err = LockTimeoutError("Could not acquire lock", resource="cells")
        assert isinstance(err, AegisError)
        assert isinstance(err, TimeoutError)
        assert err.resource == "cells"

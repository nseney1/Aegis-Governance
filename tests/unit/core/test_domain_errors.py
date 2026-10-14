"""Tests for standardized typed SomaError hierarchy (aegis_core.errors)."""
from __future__ import annotations

import pytest

from aegis_core.errors import (
    SomaError,
    SomaValidationError,
    CellCorruptError,
    ReceiptExpiredError,
    LockTimeoutError,
)


class TestDomainErrors:
    """Test suite for typed exception hierarchy and backwards compatibility."""

    def test_soma_error_base(self):
        """All domain exceptions inherit from SomaError."""
        err = SomaError("Base error", code="ERR_BASE")
        assert str(err) == "Base error"
        assert err.code == "ERR_BASE"
        assert isinstance(err, Exception)

    def test_validation_error_is_value_error(self):
        """SomaValidationError inherits from ValueError for backward compatibility."""
        err = SomaValidationError("Invalid value", code="INVALID_VALUE")
        assert isinstance(err, SomaError)
        assert isinstance(err, ValueError)
        assert str(err) == "Invalid value"

    def test_cell_corrupt_error(self):
        """CellCorruptError provides structured corruption metadata."""
        err = CellCorruptError("Malformed YAML", cell_id="bad_cell", code="CORRUPT_FRONTMATTER")
        assert isinstance(err, SomaError)
        assert err.cell_id == "bad_cell"
        assert err.code == "CORRUPT_FRONTMATTER"

    def test_receipt_expired_error(self):
        """ReceiptExpiredError inherits from KeyError for dict lookup compatibility."""
        err = ReceiptExpiredError("Receipt expired", receipt_id="rcpt_123")
        assert isinstance(err, SomaError)
        assert isinstance(err, KeyError)
        assert err.receipt_id == "rcpt_123"

    def test_lock_timeout_error(self):
        """LockTimeoutError inherits from TimeoutError."""
        err = LockTimeoutError("Could not acquire lock", resource="cells")
        assert isinstance(err, SomaError)
        assert isinstance(err, TimeoutError)
        assert err.resource == "cells"

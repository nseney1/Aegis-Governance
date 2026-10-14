"""Unified telemetry signal writer for the Soma evidence pipeline (SDK facade).

Delegates all atomic evidence logging, process-level locking, idempotency,
and epoch generation tracking to the canonical single-authority implementation
in aegis_core.telemetry.
"""
from __future__ import annotations

import sys
import types
from typing import Any

from aegis_core.telemetry import (
    DEFAULT_GENERATION,
    EPOCH_FILENAME,
    LOCK_FILENAME,
    SIGNALS_FILENAME,
    VALID_SIGNAL_TYPES,
    VALID_SOURCES,
    EventConflictError,
    StaleGenerationError,
    append_signal,
    append_signals,
    compute_event_id,
    compute_payload_digest,
    current_generation,
    evidence_lock,
    increment_generation,
    read_generation,
    read_signals,
    _validate_event,
)

__all__ = [
    "VALID_SIGNAL_TYPES",
    "VALID_SOURCES",
    "SIGNALS_FILENAME",
    "LOCK_FILENAME",
    "EPOCH_FILENAME",
    "DEFAULT_GENERATION",
    "EventConflictError",
    "StaleGenerationError",
    "evidence_lock",
    "read_generation",
    "current_generation",
    "increment_generation",
    "compute_payload_digest",
    "compute_event_id",
    "append_signal",
    "append_signals",
    "read_signals",
    "_validate_event",
]


class _TelemetryFacadeModule(types.ModuleType):
    """Module proxy that mirrors attribute mutations down to canonical aegis_core.telemetry."""

    def __setattr__(self, name: str, value: Any) -> None:
        super().__setattr__(name, value)
        try:
            import aegis_core.telemetry as _core
            if hasattr(_core, name):
                setattr(_core, name, value)
        except Exception:
            pass


sys.modules[__name__].__class__ = _TelemetryFacadeModule

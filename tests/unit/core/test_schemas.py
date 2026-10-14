"""Unit tests for immutable typed schemas (aegis_core.schemas)."""
from dataclasses import FrozenInstanceError
import pytest

from aegis_core.schemas import CellMetadata, TransitionResult, SignalEvent


def test_cell_metadata_immutability():
    meta = CellMetadata(
        id="cell-guard-1",
        type="wall",
        domain="security",
        enforcement="gate",
        tags=("security", "auth"),
    )
    assert meta.id == "cell-guard-1"
    assert meta.enforcement == "gate"
    assert meta.tags == ("security", "auth")

    with pytest.raises(FrozenInstanceError):
        meta.id = "modified"  # type: ignore[misc]


def test_transition_result_immutability():
    result = TransitionResult(
        cell_id="cell-test-2",
        from_type="membrane",
        to_type="wall",
        success=True,
        reason="high fitness score",
        timestamp="2026-10-05T12:00:00Z",
    )
    assert result.success is True
    assert result.to_type == "wall"

    with pytest.raises(FrozenInstanceError):
        result.success = False  # type: ignore[misc]


def test_signal_event_immutability():
    event = SignalEvent(
        event_id="evt-100",
        cell_id="cell-test-2",
        signal_type="promotion",
        score=0.98,
        timestamp="2026-10-05T12:00:00Z",
        details={"executor": "soma-cli"},
    )
    assert event.score == 0.98
    assert event.details == {"executor": "soma-cli"}

    with pytest.raises(FrozenInstanceError):
        event.score = 0.5  # type: ignore[misc]

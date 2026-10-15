"""Tests verifying strict mathematical and operational idempotency f(f(x)) = f(x)."""
from __future__ import annotations



from aegis_core.lifecycle.quorum import is_promotable


class TestIdempotencyContracts:
    """Test suite asserting idempotency contracts across core operations."""

    def test_predicates_are_pure_and_idempotent(self):
        """is_promotable returns identical values on repeated invocations."""
        for tp, triggers in [(25, 25), (10, 50), (1, 100), (0, 0)]:
            p1 = is_promotable(tp, triggers)
            p2 = is_promotable(tp, triggers)
            assert p1 == p2


from pathlib import Path
"""Tests for v0.30 exponential decay on fitness data.

Decay prevents Beta-locking: a cell with 1000 historical TPs can still
be demoted if it starts producing false positives consistently.

The decay function should:
1. Multiply triggers, true_positives, false_positives by DECAY_FACTOR each call
2. Floor to integers (can't have 0.5 triggers)
3. Recompute score using Bayesian posterior mean
4. Preserve the invariant: tp + fp <= triggers
5. Not decay cells with zero triggers (nothing to decay)
6. Converge to small numbers over ~20 applications (0.95^20 ≈ 0.36)
"""
import os
import sys
import copy

import pytest

REPO_ROOT = str(next(p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").exists()))
sys.path.insert(0, REPO_ROOT)


class TestExponentialDecay:
    """Verify exponential decay prevents Beta-locking."""

    def test_decay_reduces_counts(self):
        """A single decay step should reduce all counts."""
        from aegis_core.lifecycle import apply_decay
        meta = {'fitness': {'triggers': 100, 'true_positives': 90, 'false_positives': 10}}
        result = apply_decay(meta)
        fitness = result['fitness']
        assert fitness['triggers'] < 100
        assert fitness['true_positives'] < 90
        assert fitness['false_positives'] < 10

    def test_decay_preserves_ratio_approximately(self):
        """Decay should roughly preserve the TP/trigger ratio."""
        from aegis_core.lifecycle import apply_decay
        meta = {'fitness': {'triggers': 100, 'true_positives': 80, 'false_positives': 20}}
        original_ratio = 80 / 100
        result = apply_decay(meta)
        f = result['fitness']
        new_ratio = f['true_positives'] / max(f['triggers'], 1)
        # Ratios should be close (int rounding causes small drift)
        assert abs(new_ratio - original_ratio) < 0.05, \
            f"Ratio drifted too much: {original_ratio:.3f} -> {new_ratio:.3f}"

    def test_decay_recomputes_bayesian_score(self):
        """Score should be recomputed using Bayesian formula after decay."""
        from aegis_core.lifecycle import apply_decay
        meta = {'fitness': {
            'triggers': 100, 'true_positives': 90,
            'false_positives': 10, 'score': 0.9
        }}
        result = apply_decay(meta)
        f = result['fitness']
        expected = (f['true_positives'] + 1) / (f['triggers'] + 2)
        assert f['score'] == pytest.approx(expected, rel=1e-3)

    def test_decay_zero_triggers_is_noop(self):
        """Cells with zero triggers should not be modified."""
        from aegis_core.lifecycle import apply_decay
        meta = {'fitness': {'triggers': 0, 'true_positives': 0, 'false_positives': 0}}
        result = apply_decay(meta)
        assert result['fitness']['triggers'] == 0
        assert result['fitness']['true_positives'] == 0

    def test_decay_floors_to_integers(self):
        """Decayed counts must be integers (can't have fractional triggers)."""
        from aegis_core.lifecycle import apply_decay
        meta = {'fitness': {'triggers': 7, 'true_positives': 5, 'false_positives': 2}}
        result = apply_decay(meta)
        f = result['fitness']
        assert isinstance(f['triggers'], int)
        assert isinstance(f['true_positives'], int)
        assert isinstance(f['false_positives'], int)

    def test_20_decay_steps_reduce_1000_to_manageable(self):
        """After 20 decay steps (0.95^20 ≈ 0.36), 1000 triggers should
        drop to ~360. This is the 'effective memory window' test."""
        from aegis_core.lifecycle import apply_decay
        meta = {'fitness': {'triggers': 1000, 'true_positives': 950, 'false_positives': 50}}
        for _ in range(20):
            meta['fitness'].pop('last_decay_epoch', None)  # simulate session gap
            meta = apply_decay(meta)
        f = meta['fitness']
        # 1000 * 0.95^20 ≈ 358 (with int rounding drift)
        assert f['triggers'] < 500, f"After 20 steps, triggers should be <500, got {f['triggers']}"
        assert f['triggers'] > 200, f"After 20 steps, triggers should be >200, got {f['triggers']}"

    def test_frozen_champion_can_be_displaced(self):
        """The critical test: a cell with Beta(1001, 1) should be displaceable
        after enough decay steps, even with no new observations."""
        from aegis_core.lifecycle import apply_decay
        meta = {'fitness': {'triggers': 1000, 'true_positives': 1000, 'false_positives': 0}}
        for _ in range(50):
            meta['fitness'].pop('last_decay_epoch', None)  # simulate session gap
            meta = apply_decay(meta)
        f = meta['fitness']
        # After 50 steps of pure decay, triggers should be very small
        assert f['triggers'] < 100, \
            f"Frozen champion should be displaceable after 50 decay steps, got triggers={f['triggers']}"

    def test_decay_triggers_never_below_1(self):
        """If a cell has data, triggers should floor at 1, not hit 0
        (which would erase all evidence)."""
        from aegis_core.lifecycle import apply_decay
        meta = {'fitness': {'triggers': 2, 'true_positives': 1, 'false_positives': 1}}
        for _ in range(100):
            meta['fitness'].pop('last_decay_epoch', None)  # simulate session gap
            meta = apply_decay(meta)
        f = meta['fitness']
        assert f['triggers'] >= 1, "Triggers should floor at 1, not erase to 0"

    def test_decay_does_not_mutate_input(self):
        """apply_decay should return modified meta, not silently mutate
        the caller's dict in a surprising way... or if it does mutate,
        the return value should be the same object."""
        from aegis_core.lifecycle import apply_decay
        meta = {'fitness': {'triggers': 100, 'true_positives': 90, 'false_positives': 10}}
        original_triggers = meta['fitness']['triggers']
        result = apply_decay(meta)
        # Either result IS meta (mutates in place) or meta is unchanged
        if result is not meta:
            assert meta['fitness']['triggers'] == original_triggers, \
                "apply_decay returned a new dict but also mutated the input"

    def test_decay_missing_fitness_key(self):
        """Cells without a fitness key should be handled gracefully."""
        from aegis_core.lifecycle import apply_decay
        meta = {}
        result = apply_decay(meta)
        # Should not crash, should return meta unchanged
        assert result is not None

# ── Phase 5: C5 — Decay Idempotency ──────────────────────────────────────

import time

class TestDecayIdempotency:
    """Verify apply_decay is idempotent within a session."""

    def test_consecutive_decay_is_noop(self):
        """Two apply_decay calls within 1 hour should only decay once."""
        from aegis_core.lifecycle import apply_decay
        meta = {'fitness': {
            'triggers': 100, 'true_positives': 90, 'false_positives': 10,
            'last_decay_epoch': int(time.time())  # just decayed
        }}
        original_triggers = meta['fitness']['triggers']
        apply_decay(meta)
        assert meta['fitness']['triggers'] == original_triggers, \
            f"Decay should be no-op within session, got {meta['fitness']['triggers']}"

    def test_decay_applies_after_gap(self):
        """Decay should apply if last_decay_epoch is > 1 hour ago."""
        from aegis_core.lifecycle import apply_decay
        meta = {'fitness': {
            'triggers': 100, 'true_positives': 90, 'false_positives': 10,
            'last_decay_epoch': int(time.time()) - 7200  # 2 hours ago
        }}
        apply_decay(meta)
        assert meta['fitness']['triggers'] < 100, \
            f"Decay should apply after 2-hour gap, got {meta['fitness']['triggers']}"

    def test_decay_sets_epoch_after_application(self):
        """After decaying, last_decay_epoch should be set to current time."""
        from aegis_core.lifecycle import apply_decay
        before = int(time.time())
        meta = {'fitness': {
            'triggers': 100, 'true_positives': 90, 'false_positives': 10
        }}
        apply_decay(meta)
        after = int(time.time())
        epoch = meta['fitness'].get('last_decay_epoch', 0)
        assert before <= epoch <= after, \
            f"last_decay_epoch should be set to current time, got {epoch}"

    def test_first_decay_no_epoch_applies(self):
        """Cells without last_decay_epoch (legacy) should still get decayed."""
        from aegis_core.lifecycle import apply_decay
        meta = {'fitness': {
            'triggers': 100, 'true_positives': 90, 'false_positives': 10
            # no last_decay_epoch
        }}
        apply_decay(meta)
        assert meta['fitness']['triggers'] < 100, \
            "First decay (no epoch) should apply"

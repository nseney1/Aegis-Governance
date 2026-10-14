"""Tests for soma_core.lifecycle — canonical cell state transitions, scoring, and operations."""
from __future__ import annotations

import os
import shutil
import time
from pathlib import Path

import pytest

from soma_core.lifecycle import (
    PROTECTED_RULES,
    STATUS_ADAPT,
    STATUS_APOPTOSIS,
    STATUS_APOPTOSIS_WARNING,
    STATUS_DORMANT,
    STATUS_EXTINCT,
    STATUS_NEW,
    STATUS_SURVIVE,
    apply_exponential_decay,
    calculate_fitness_status,
    demote_cell,
    find_cell_file,
    is_extinct,
    is_promotable,
    promote_cell,
)


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """Create a minimal workspace with .soma/cells directories."""
    (tmp_path / ".soma" / "cells" / "vacuoles").mkdir(parents=True)
    (tmp_path / ".soma" / "cells" / "walls").mkdir(parents=True)
    (tmp_path / "genome").mkdir(parents=True)
    (tmp_path / "soma_core").mkdir(parents=True)
    (tmp_path / "soma_cli").mkdir(parents=True)
    (tmp_path / "pyproject.toml").write_text('name = "soma-governance"\n', encoding="utf-8")
    return tmp_path


def _create_cell_file(path: Path, cell_id: str, cell_type: str, triggers: int = 0, tp: int = 0, fp: int = 0) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = f"""---
id: {cell_id}
type: {cell_type}
domain: testing
fitness:
  triggers: {triggers}
  true_positives: {tp}
  false_positives: {fp}
  score: 0.5
---
# {cell_id}
Description here.
"""
    path.write_text(content, encoding="utf-8")
    return path


class TestFitnessStatusEvaluation:
    """Evaluates cell lifecycle status from decay, scores, and apoptosis."""

    def test_apoptosis_for_vacuole_when_false_positives_dominate(self):
        status = calculate_fitness_status(
            cell_type="vacuole", tp=5, fp=15, triggers=20, dec_score=0.25
        )
        assert status == STATUS_APOPTOSIS

    def test_apoptosis_warning_for_wall(self):
        status = calculate_fitness_status(
            cell_type="wall", tp=5, fp=15, triggers=20, dec_score=0.25
        )
        assert status == STATUS_APOPTOSIS_WARNING

    def test_survive_status_high_score(self):
        status = calculate_fitness_status(
            cell_type="vacuole", tp=18, fp=2, triggers=20, dec_score=0.85
        )
        assert status == STATUS_SURVIVE

    def test_adapt_status_medium_score(self):
        status = calculate_fitness_status(
            cell_type="vacuole", tp=10, fp=10, triggers=20, dec_score=0.5
        )
        assert status == STATUS_ADAPT

    def test_extinct_status_below_threshold(self):
        status = calculate_fitness_status(
            cell_type="vacuole", tp=1, fp=1, triggers=20, dec_score=0.10
        )
        assert status == STATUS_EXTINCT

    def test_dormant_vs_new_unobserved(self):
        # Unobserved older than expiry -> DORMANT
        status_old = calculate_fitness_status(
            cell_type="vacuole", tp=0, fp=0, triggers=0, is_unobserved=True,
            created_str="2020-01-01T00:00:00Z", expiry_days=30
        )
        assert status_old == STATUS_DORMANT

        # Unobserved recent -> NEW
        status_new = calculate_fitness_status(
            cell_type="vacuole", tp=0, fp=0, triggers=0, is_unobserved=True,
            created_str="2099-01-01T00:00:00Z", expiry_days=30
        )
        assert status_new == STATUS_NEW


class TestPromotableAndExtinct:
    """Verifies boundary thresholds for promotion and extinction."""

    def test_is_promotable_above_threshold(self):
        # tp=19, triggers=20 -> (19+1)/(20+2) = 0.909 > 0.85
        assert is_promotable(tp=19, triggers=20) is True

    def test_is_promotable_insufficient_triggers(self):
        # Perfect score but only 10 triggers
        assert is_promotable(tp=10, triggers=10) is False

    def test_is_extinct_at_or_below_threshold(self):
        # tp=0, triggers=10 -> (0+1)/(10+2) = 0.083 <= 0.15
        assert is_extinct(tp=0, triggers=10) is True
        # tp=2, triggers=10 -> (2+1)/(10+2) = 0.25 > 0.15
        assert is_extinct(tp=2, triggers=10) is False

    def test_zero_triggers_neither(self):
        assert is_promotable(tp=0, triggers=0) is False
        assert is_extinct(tp=0, triggers=0) is False


class TestDecay:
    """Verifies exponential decay and idempotency."""

    def test_decay_reduces_counts(self):
        fitness = {
            "triggers": 100,
            "true_positives": 90,
            "false_positives": 10,
            "last_decay_epoch": 0,
        }
        decayed = apply_exponential_decay(fitness, decay_factor=0.95, min_interval_seconds=0)
        assert decayed["triggers"] == 95
        assert decayed["true_positives"] == 85
        assert decayed["false_positives"] == 9
        assert decayed["last_decay_epoch"] > 0

    def test_decay_idempotency(self):
        now = int(time.time())
        fitness = {
            "triggers": 100,
            "true_positives": 90,
            "false_positives": 10,
            "last_decay_epoch": now - 60,  # 1 min ago (< 3600s)
        }
        decayed = apply_exponential_decay(fitness, decay_factor=0.95, min_interval_seconds=3600)
        assert decayed["triggers"] == 100  # unchanged


class TestCellPromoteAndDemote:
    """Verifies file movements and frontmatter updates for promotions and demotions."""

    def test_find_cell_file(self, workspace: Path):
        vacuole = _create_cell_file(workspace / ".soma" / "cells" / "vacuoles" / "test-v.md", "test-v", "vacuole")
        found_path, found_type = find_cell_file(workspace, "test-v")
        assert found_path == vacuole
        assert found_type == "vacuole"

        # Traversal attempt returns None
        assert find_cell_file(workspace, "../etc/passwd") == (None, None)

    def test_promote_vacuole_to_wall(self, workspace: Path):
        vacuole = _create_cell_file(
            workspace / ".soma" / "cells" / "vacuoles" / "promote-me.md",
            "promote-me", "vacuole", triggers=25, tp=24, fp=1
        )
        res = promote_cell(workspace, "promote-me", force=False)
        assert res["status"] == "promoted"
        assert res["from_type"] == "vacuole"
        assert res["to_type"] == "wall"

        # Original vacuole path no longer exists
        assert not vacuole.exists()

        # Wall path exists with updated frontmatter
        wall_path = workspace / ".soma" / "cells" / "walls" / "promote-me.md"
        assert wall_path.exists()
        content = wall_path.read_text(encoding="utf-8")
        assert "type: wall" in content

    def test_promote_wall_to_genome(self, workspace: Path):
        wall = _create_cell_file(
            workspace / ".soma" / "cells" / "walls" / "wall-cell.md",
            "wall-cell", "wall", triggers=30, tp=29, fp=1
        )
        res = promote_cell(workspace, "wall-cell", force=True)
        assert res["status"] == "promoted"
        assert res["to_type"] == "genome"
        assert not wall.exists()
        assert (workspace / "genome" / "wall-cell.md").exists()

    def test_promote_terminal_genome_cell(self, workspace: Path):
        _create_cell_file(workspace / "genome" / "terminal.md", "terminal", "genome")
        res = promote_cell(workspace, "terminal", force=True)
        assert res["status"] == "already_terminal"

    def test_demote_wall_to_vacuole(self, workspace: Path):
        wall = _create_cell_file(workspace / ".soma" / "cells" / "walls" / "demote-wall.md", "demote-wall", "wall")
        res = demote_cell(workspace, "demote-wall")
        assert res["status"] == "demoted"
        assert res["from_type"] == "wall"
        assert res["to_type"] == "vacuole"
        assert not wall.exists()
        vacuole_path = workspace / ".soma" / "cells" / "vacuoles" / "demote-wall.md"
        assert vacuole_path.exists()
        assert "type: vacuole" in vacuole_path.read_text(encoding="utf-8")

    def test_demote_protected_rules_blocked(self, workspace: Path):
        for rule in ("providence", "cost-optimization", "git-workflow"):
            _create_cell_file(workspace / "genome" / f"{rule}.md", rule, "genome")
            with pytest.raises(ValueError, match="Cannot demote protected core rule"):
                demote_cell(workspace, rule)

    def test_promote_protected_rule_blocked(self, workspace: Path):
        _create_cell_file(
            workspace / ".soma" / "cells" / "walls" / "providence.md",
            "providence", "wall", triggers=30, tp=29, fp=1
        )
        res = promote_cell(workspace, "providence", force=True)
        assert res["status"] == "protected_rule_immutable"
        assert "protected core rule" in res["message"].lower()

    def test_apoptosis_triggers_for_zero_tp(self):
        status = calculate_fitness_status("vacuole", tp=0, fp=5, triggers=5, dec_score=0.1)
        assert status == STATUS_APOPTOSIS

        status_wall = calculate_fitness_status("wall", tp=0, fp=5, triggers=5, dec_score=0.1)
        assert status_wall == STATUS_APOPTOSIS_WARNING

    def test_extinction_boundary_parity(self):
        # dec_score == 0.15 should be EXTINCT, matching is_extinct
        status = calculate_fitness_status("vacuole", tp=1, fp=1, triggers=2, dec_score=0.15)
        assert status == STATUS_EXTINCT

    def test_demote_wall_cleans_enforcement_artifacts(self, workspace: Path):
        wall = _create_cell_file(
            workspace / ".soma" / "cells" / "walls" / "guarded-cell.md",
            "guarded-cell", "wall"
        )
        # Create gate enforcement artifact
        enf_dir = workspace / ".soma" / "enforcement"
        enf_dir.mkdir(parents=True)
        gate_script = enf_dir / "gate-guarded-cell.sh"
        gate_script.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")

        res = demote_cell(workspace, "guarded-cell")
        assert res["status"] == "demoted"
        assert not gate_script.exists()

    def test_lifecycle_frontmatter_and_storage_consolidation(self):
        """Ensure lifecycle, sync, and telemetry delegate frontmatter and fsync/atomic storage to yaml.py and storage.py."""
        import inspect
        from aegis_core import storage, sync, telemetry
        from aegis_core.lifecycle import creation, parsers, promotion, selection

        assert hasattr(storage, "atomic_write_and_unlink")
        for mod in (creation, parsers, promotion, selection, sync, telemetry):
            src = inspect.getsource(mod)
            assert 'find("---", 3)' not in src, f"{mod.__name__} still uses naive find('---', 3)"
            assert "def _fsync_dir" not in src, f"{mod.__name__} still defines duplicate _fsync_dir"
            assert "def _atomic_write_and_unlink" not in src, f"{mod.__name__} still defines duplicate _atomic_write_and_unlink"


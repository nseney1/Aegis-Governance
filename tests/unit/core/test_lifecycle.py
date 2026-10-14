from pathlib import Path
"""TDD Gate 1 tests for the cell lifecycle engine.

The lifecycle engine provides deterministic promotion/demotion decisions
based on canonical signals.jsonl evidence:

Lifecycle path: vacuole (hypothesis) → wall (proven gate) → genome (universal law)

Promotion criteria (deterministic):
  - triggers ≥ 20 AND tp_rate > 0.85 AND age > 30 days

Demotion criteria (deterministic):
  - fp_rate > 0.5 OR triggers == 0 for 90 days
"""
import json
import os
import sys
from datetime import datetime, timedelta

import pytest

REPO_ROOT = str(next(p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").exists()))
sys.path.insert(0, REPO_ROOT)

from tests.helpers_rule import make_cell


def write_evidence(evidence_dir, cell_id, triggers=0, tp=0, fp=0):
    """Write canonical trigger and outcome rows to signals.jsonl."""
    signal_file = os.path.join(str(evidence_dir), "signals.jsonl")
    timestamp = datetime.now().isoformat()
    with open(signal_file, "a", encoding="utf-8") as stream:
        for _ in range(triggers):
            stream.write(json.dumps({
                "cell": cell_id,
                "signal": "trigger",
                "timestamp": timestamp,
            }) + "\n")
        for signal, count in (("tp", tp), ("fp", fp)):
            for _ in range(count):
                stream.write(json.dumps({
                    "cell": cell_id,
                    "signal": signal,
                    "timestamp": timestamp,
                }) + "\n")


class TestLifecycleImport:
    """Lifecycle engine must be importable."""

    def test_evaluate_promotions_importable(self):
        from aegis_core.lifecycle import evaluate_promotions
        assert callable(evaluate_promotions)

    def test_evaluate_demotions_importable(self):
        from aegis_core.lifecycle import evaluate_demotions
        assert callable(evaluate_demotions)


class TestPromotionCriteria:
    """Deterministic promotion: triggers ≥ 20 AND tp_rate > 0.85 AND age > 30 days."""

    def test_promotes_qualifying_vacuole(self, tmp_path):
        """Trap with 25 triggers, 90% tp_rate, 45 days old → promote to invariant."""
        from aegis_core.lifecycle import evaluate_promotions

        cells_dir = tmp_path / ".aegis" / "rules" / "traps"
        cells_dir.mkdir(parents=True)
        evidence_dir = tmp_path / ".aegis" / "evidence"
        evidence_dir.mkdir(parents=True)

        make_cell(str(cells_dir), "proven-cell", cell_type="trap",
                  created_days_ago=45)
        write_evidence(str(evidence_dir), "proven-cell", triggers=25, tp=23, fp=2)

        candidates = evaluate_promotions(str(tmp_path))
        assert len(candidates) == 1
        assert candidates[0]["cell_id"] == "proven-cell"
        assert candidates[0]["from_type"] == "trap"
        assert candidates[0]["to_type"] == "invariant"

    def test_rejects_too_few_triggers(self, tmp_path):
        """Only 10 triggers → not enough for promotion."""
        from aegis_core.lifecycle import evaluate_promotions

        cells_dir = tmp_path / ".aegis" / "rules" / "traps"
        cells_dir.mkdir(parents=True)
        evidence_dir = tmp_path / ".aegis" / "evidence"
        evidence_dir.mkdir(parents=True)

        make_cell(str(cells_dir), "young-cell", cell_type="trap",
                  created_days_ago=45)
        write_evidence(str(evidence_dir), "young-cell", triggers=10, tp=9, fp=1)

        candidates = evaluate_promotions(str(tmp_path))
        assert len(candidates) == 0

    def test_rejects_low_tp_rate(self, tmp_path):
        """tp_rate = 0.60 → below 0.85 threshold."""
        from aegis_core.lifecycle import evaluate_promotions

        cells_dir = tmp_path / ".aegis" / "rules" / "traps"
        cells_dir.mkdir(parents=True)
        evidence_dir = tmp_path / ".aegis" / "evidence"
        evidence_dir.mkdir(parents=True)

        make_cell(str(cells_dir), "noisy-cell", cell_type="trap",
                  created_days_ago=45)
        write_evidence(str(evidence_dir), "noisy-cell", triggers=25, tp=15, fp=10)

        candidates = evaluate_promotions(str(tmp_path))
        assert len(candidates) == 0

    def test_rejects_too_young(self, tmp_path):
        """Cell only 15 days old → must be > 30 days."""
        from aegis_core.lifecycle import evaluate_promotions

        cells_dir = tmp_path / ".aegis" / "rules" / "traps"
        cells_dir.mkdir(parents=True)
        evidence_dir = tmp_path / ".aegis" / "evidence"
        evidence_dir.mkdir(parents=True)

        make_cell(str(cells_dir), "new-cell", cell_type="trap",
                  created_days_ago=15)
        write_evidence(str(evidence_dir), "new-cell", triggers=30, tp=28, fp=2)

        candidates = evaluate_promotions(str(tmp_path))
        assert len(candidates) == 0

    def test_wall_promotes_to_genome(self, tmp_path):
        """Wall with strong evidence → promote to genome."""
        from aegis_core.lifecycle import evaluate_promotions

        cells_dir = tmp_path / ".aegis" / "rules" / "walls"
        cells_dir.mkdir(parents=True)
        evidence_dir = tmp_path / ".aegis" / "evidence"
        evidence_dir.mkdir(parents=True)
        (tmp_path / "aegis_core").mkdir(parents=True)
        (tmp_path / "aegis_cli").mkdir(parents=True)
        (tmp_path / "pyproject.toml").write_text('name = "aegis-governance"\n', encoding="utf-8")

        make_cell(str(cells_dir), "proven-wall", cell_type="wall",
                  created_days_ago=60)
        write_evidence(str(evidence_dir), "proven-wall", triggers=30, tp=28, fp=2)

        candidates = evaluate_promotions(str(tmp_path))
        assert len(candidates) == 1
        assert candidates[0]["to_type"] == "genome"

    def test_empty_workspace_returns_empty(self, tmp_path):
        """No cells → no promotion candidates."""
        from aegis_core.lifecycle import evaluate_promotions

        (tmp_path / ".aegis" / "rules").mkdir(parents=True)
        (tmp_path / ".aegis" / "evidence").mkdir(parents=True)

        candidates = evaluate_promotions(str(tmp_path))
        assert candidates == []


class TestDemotionCriteria:
    """Deterministic demotion: fp_rate > 0.5 OR triggers == 0 for 90 days."""

    def test_demotes_noisy_cell(self, tmp_path):
        """fp_rate = 0.7 → demote."""
        from aegis_core.lifecycle import evaluate_demotions

        cells_dir = tmp_path / ".aegis" / "rules" / "walls"
        cells_dir.mkdir(parents=True)
        evidence_dir = tmp_path / ".aegis" / "evidence"
        evidence_dir.mkdir(parents=True)

        make_cell(str(cells_dir), "noisy-wall", cell_type="wall",
                  created_days_ago=60)
        write_evidence(str(evidence_dir), "noisy-wall", triggers=20, tp=6, fp=14)

        candidates = evaluate_demotions(str(tmp_path))
        assert len(candidates) == 1
        assert candidates[0]["cell_id"] == "noisy-wall"
        assert candidates[0]["reason"] == "high_fp_rate"

    def test_demotes_dormant_cell(self, tmp_path):
        """Zero triggers for 90+ days → demote."""
        from aegis_core.lifecycle import evaluate_demotions

        cells_dir = tmp_path / ".aegis" / "rules" / "walls"
        cells_dir.mkdir(parents=True)
        evidence_dir = tmp_path / ".aegis" / "evidence"
        evidence_dir.mkdir(parents=True)

        make_cell(str(cells_dir), "dormant-wall", cell_type="wall",
                  created_days_ago=120)
        # No evidence at all — zero triggers

        candidates = evaluate_demotions(str(tmp_path))
        assert len(candidates) == 1
        assert candidates[0]["cell_id"] == "dormant-wall"
        assert candidates[0]["reason"] == "dormant"

    def test_keeps_healthy_cell(self, tmp_path):
        """Cell with good metrics → no demotion."""
        from aegis_core.lifecycle import evaluate_demotions

        cells_dir = tmp_path / ".aegis" / "rules" / "walls"
        cells_dir.mkdir(parents=True)
        evidence_dir = tmp_path / ".aegis" / "evidence"
        evidence_dir.mkdir(parents=True)

        make_cell(str(cells_dir), "good-wall", cell_type="wall",
                  created_days_ago=60)
        write_evidence(str(evidence_dir), "good-wall", triggers=25, tp=23, fp=2)

        candidates = evaluate_demotions(str(tmp_path))
        assert len(candidates) == 0

    def test_wall_demotes_to_vacuole(self, tmp_path):
        """Demoted wall should become a trap."""
        from aegis_core.lifecycle import evaluate_demotions

        cells_dir = tmp_path / ".aegis" / "rules" / "walls"
        cells_dir.mkdir(parents=True)
        evidence_dir = tmp_path / ".aegis" / "evidence"
        evidence_dir.mkdir(parents=True)

        make_cell(str(cells_dir), "bad-wall", cell_type="wall",
                  created_days_ago=60)
        write_evidence(str(evidence_dir), "bad-wall", triggers=10, tp=3, fp=7)

        candidates = evaluate_demotions(str(tmp_path))
        assert len(candidates) == 1
        assert candidates[0]["from_type"] == "wall"
        assert candidates[0]["to_type"] == "trap"

    def test_empty_workspace_returns_empty(self, tmp_path):
        """No cells → no demotion candidates."""
        from aegis_core.lifecycle import evaluate_demotions

        (tmp_path / ".aegis" / "rules").mkdir(parents=True)
        (tmp_path / ".aegis" / "evidence").mkdir(parents=True)

        candidates = evaluate_demotions(str(tmp_path))
        assert candidates == []


class TestLifecycleBoundaries:
    """Boundary condition tests for promotion/demotion thresholds."""

    def test_promotion_boundary_triggers_19_rejected(self, tmp_path):
        """19 triggers should NOT promote (need >=20)."""
        from aegis_core.lifecycle import evaluate_promotions

        cells_dir = tmp_path / ".aegis" / "rules" / "traps"
        cells_dir.mkdir(parents=True)
        evidence_dir = tmp_path / ".aegis" / "evidence"
        evidence_dir.mkdir(parents=True)

        make_cell(str(cells_dir), "edge-cell-19", cell_type="trap",
                  created_days_ago=45)
        # 19 triggers, all TP → tp_rate = 1.0 (passes rate check)
        write_evidence(str(evidence_dir), "edge-cell-19", triggers=19, tp=19, fp=0)

        candidates = evaluate_promotions(str(tmp_path))
        assert len(candidates) == 0

    def test_promotion_boundary_triggers_20_accepted(self, tmp_path):
        """Exactly 20 triggers should promote."""
        from aegis_core.lifecycle import evaluate_promotions

        cells_dir = tmp_path / ".aegis" / "rules" / "traps"
        cells_dir.mkdir(parents=True)
        evidence_dir = tmp_path / ".aegis" / "evidence"
        evidence_dir.mkdir(parents=True)

        make_cell(str(cells_dir), "edge-cell-20", cell_type="trap",
                  created_days_ago=45)
        # 20 triggers, 18 TP → tp_rate = 0.90 (passes >=0.85)
        write_evidence(str(evidence_dir), "edge-cell-20", triggers=20, tp=18, fp=2)

        candidates = evaluate_promotions(str(tmp_path))
        assert len(candidates) == 1
        assert candidates[0]["cell_id"] == "edge-cell-20"

    def test_promotion_boundary_tp_rate_084_rejected(self, tmp_path):
        """0.84 tp_rate should NOT promote (need >=0.85)."""
        from aegis_core.lifecycle import evaluate_promotions

        cells_dir = tmp_path / ".aegis" / "rules" / "traps"
        cells_dir.mkdir(parents=True)
        evidence_dir = tmp_path / ".aegis" / "evidence"
        evidence_dir.mkdir(parents=True)

        make_cell(str(cells_dir), "low-tp-cell", cell_type="trap",
                  created_days_ago=45)
        # 25 triggers, 21 TP → tp_rate = 0.84
        write_evidence(str(evidence_dir), "low-tp-cell", triggers=25, tp=21, fp=4)

        candidates = evaluate_promotions(str(tmp_path))
        assert len(candidates) == 0

    def test_demotion_boundary_triggers_4_not_enough(self, tmp_path):
        """4 triggers too few for fp_rate demotion (need >=5)."""
        from aegis_core.lifecycle import evaluate_demotions

        cells_dir = tmp_path / ".aegis" / "rules" / "walls"
        cells_dir.mkdir(parents=True)
        evidence_dir = tmp_path / ".aegis" / "evidence"
        evidence_dir.mkdir(parents=True)

        make_cell(str(cells_dir), "few-triggers", cell_type="wall",
                  created_days_ago=10)
        # 4 triggers, 3 FP → fp_rate would be 0.75, but <5 triggers skips check
        write_evidence(str(evidence_dir), "few-triggers", triggers=4, tp=1, fp=3)

        candidates = evaluate_demotions(str(tmp_path))
        # Should NOT be demoted — not enough triggers for fp_rate check
        # and not dormant (recent triggers, age < 90)
        assert len(candidates) == 0

    def test_demotion_boundary_triggers_5_fp_demotes(self, tmp_path):
        """5 triggers with >50% FP should demote."""
        from aegis_core.lifecycle import evaluate_demotions

        cells_dir = tmp_path / ".aegis" / "rules" / "walls"
        cells_dir.mkdir(parents=True)
        evidence_dir = tmp_path / ".aegis" / "evidence"
        evidence_dir.mkdir(parents=True)

        make_cell(str(cells_dir), "noisy-5", cell_type="wall",
                  created_days_ago=10)
        # 5 triggers, 3 FP → fp_rate = 0.60 (>0.5 threshold)
        write_evidence(str(evidence_dir), "noisy-5", triggers=5, tp=2, fp=3)

        candidates = evaluate_demotions(str(tmp_path))
        assert len(candidates) == 1
        assert candidates[0]["cell_id"] == "noisy-5"
        assert candidates[0]["reason"] == "high_fp_rate"

    def test_promotion_boundary_tp_rate_085_accepted(self, tmp_path):
        """Exactly 0.85 tp_rate should promote (inclusive >=)."""
        from aegis_core.lifecycle import evaluate_promotions

        cells_dir = tmp_path / ".aegis" / "rules" / "traps"
        cells_dir.mkdir(parents=True)
        evidence_dir = tmp_path / ".aegis" / "evidence"
        evidence_dir.mkdir(parents=True)

        make_cell(str(cells_dir), "tp-085-cell", cell_type="trap",
                  created_days_ago=45)
        # 20 triggers, 17 TP → tp_rate = 0.85
        write_evidence(str(evidence_dir), "tp-085-cell", triggers=20, tp=17, fp=3)

        candidates = evaluate_promotions(str(tmp_path))
        assert len(candidates) == 1
        assert candidates[0]["cell_id"] == "tp-085-cell"
        assert candidates[0]["tp_rate"] == 0.85

    def test_promotion_boundary_age_29_rejected(self, tmp_path):
        """29 days old should NOT promote (need >=30)."""
        from aegis_core.lifecycle import evaluate_promotions

        cells_dir = tmp_path / ".aegis" / "rules" / "traps"
        cells_dir.mkdir(parents=True)
        evidence_dir = tmp_path / ".aegis" / "evidence"
        evidence_dir.mkdir(parents=True)

        # created_days_ago=28 → actual age_days=29 (date truncation adds ~1 day)
        make_cell(str(cells_dir), "age-29-cell", cell_type="trap",
                  created_days_ago=28)
        # Passes trigger and tp_rate checks
        write_evidence(str(evidence_dir), "age-29-cell", triggers=25, tp=24, fp=1)

        candidates = evaluate_promotions(str(tmp_path))
        assert len(candidates) == 0

    def test_promotion_boundary_age_30_accepted(self, tmp_path):
        """Exactly 30 days old should promote."""
        from aegis_core.lifecycle import evaluate_promotions

        cells_dir = tmp_path / ".aegis" / "rules" / "traps"
        cells_dir.mkdir(parents=True)
        evidence_dir = tmp_path / ".aegis" / "evidence"
        evidence_dir.mkdir(parents=True)

        make_cell(str(cells_dir), "age-30-cell", cell_type="trap",
                  created_days_ago=30)
        # Passes trigger and tp_rate checks
        write_evidence(str(evidence_dir), "age-30-cell", triggers=25, tp=24, fp=1)

        candidates = evaluate_promotions(str(tmp_path))
        assert len(candidates) == 1
        assert candidates[0]["cell_id"] == "age-30-cell"

    def test_demotion_boundary_fp_rate_050_not_demoted(self, tmp_path):
        """fp_rate exactly 0.50 should NOT demote (need >0.50)."""
        from aegis_core.lifecycle import evaluate_demotions

        cells_dir = tmp_path / ".aegis" / "rules" / "walls"
        cells_dir.mkdir(parents=True)
        evidence_dir = tmp_path / ".aegis" / "evidence"
        evidence_dir.mkdir(parents=True)

        make_cell(str(cells_dir), "fp-050-wall", cell_type="wall",
                  created_days_ago=10)
        # 10 triggers, 5 FP → fp_rate = 0.50 exactly
        write_evidence(str(evidence_dir), "fp-050-wall", triggers=10, tp=5, fp=5)

        candidates = evaluate_demotions(str(tmp_path))
        assert len(candidates) == 0

    def test_demotion_boundary_dormancy_89_not_demoted(self, tmp_path):
        """89 days old with 0 triggers should NOT be demoted for dormancy (need >=90)."""
        from aegis_core.lifecycle import evaluate_demotions

        cells_dir = tmp_path / ".aegis" / "rules" / "walls"
        cells_dir.mkdir(parents=True)
        evidence_dir = tmp_path / ".aegis" / "evidence"
        evidence_dir.mkdir(parents=True)

        # created_days_ago=88 → actual age_days=89 (date truncation adds ~1 day)
        make_cell(str(cells_dir), "dormant-89", cell_type="wall",
                  created_days_ago=88)
        # No evidence — dormancy proxy uses cell age (89 < 90)

        candidates = evaluate_demotions(str(tmp_path))
        assert len(candidates) == 0

    def test_demotion_boundary_dormancy_90_demoted(self, tmp_path):
        """90 days old with 0 triggers should be demoted for dormancy."""
        from aegis_core.lifecycle import evaluate_demotions

        cells_dir = tmp_path / ".aegis" / "rules" / "walls"
        cells_dir.mkdir(parents=True)
        evidence_dir = tmp_path / ".aegis" / "evidence"
        evidence_dir.mkdir(parents=True)

        make_cell(str(cells_dir), "dormant-90", cell_type="wall",
                  created_days_ago=90)
        # No evidence — dormancy proxy uses cell age (90 >= 90)

        candidates = evaluate_demotions(str(tmp_path))
        assert len(candidates) == 1
        assert candidates[0]["cell_id"] == "dormant-90"
        assert candidates[0]["reason"] == "dormant"


class TestModernRuleLifecycle:
    """Lifecycle promotion and demotion for modern .aegis/rules/ types (trap <-> invariant)."""

    def test_promote_trap_to_invariant_and_demote_invariant_to_trap(self, tmp_path):
        from aegis_core.lifecycle import evaluate_promotions, evaluate_demotions

        traps_dir = tmp_path / ".aegis" / "rules" / "traps"
        inv_dir = tmp_path / ".aegis" / "rules" / "invariants"
        evidence_dir = tmp_path / ".aegis" / "evidence"
        traps_dir.mkdir(parents=True)
        inv_dir.mkdir(parents=True)
        evidence_dir.mkdir(parents=True)

        make_cell(str(traps_dir), "proven-trap", cell_type="trap", created_days_ago=45)
        write_evidence(str(evidence_dir), "proven-trap", triggers=25, tp=23, fp=2)

        make_cell(str(inv_dir), "noisy-invariant", cell_type="invariant", created_days_ago=45)
        write_evidence(str(evidence_dir), "noisy-invariant", triggers=20, tp=4, fp=16)

        promotions = evaluate_promotions(str(tmp_path))
        assert len(promotions) == 1
        assert promotions[0]["rule_id"] == "proven-trap"
        assert promotions[0]["from_type"] == "trap"
        assert promotions[0]["to_type"] == "invariant"

        demotions = evaluate_demotions(str(tmp_path))
        assert len(demotions) == 1
        assert demotions[0]["rule_id"] == "noisy-invariant"
        assert demotions[0]["from_type"] == "invariant"
        assert demotions[0]["to_type"] == "trap"



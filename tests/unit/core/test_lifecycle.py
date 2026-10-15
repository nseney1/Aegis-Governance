"""Promotion and demotion candidates from ledger fitness (aegis_core.lifecycle.promotion).

The ladder is trap -> invariant -> gate. Candidates come from the one estimator
(aegis_core.fitness, Wilson lower bound at 90%):

- promote: at least 20 verdicts, fitness >= 0.85, created at least 30 days ago;
- demote (or archive, for a rule with no lower tier): the Wilson lower bound of the
  false-positive rate is above 0.5.

Boundary values below are Wilson bounds: 20/20 tp -> 0.881, 19/20 -> 0.804,
24/25 -> 0.839; 3/3 fp -> 0.526, 5/6 -> 0.498, 4/5 -> 0.435.
"""
from __future__ import annotations

from tests.helpers_rule import make_cell, write_evidence

from aegis_core.lifecycle.promotion import evaluate_demotions, evaluate_promotions
from aegis_core.lifecycle.selection import evaluate_archives


def _ws(tmp_path):
    (tmp_path / ".aegis" / "rules").mkdir(parents=True, exist_ok=True)
    return tmp_path


def _trap(tmp_path, name, tp=0, fp=0, triggers=None, age=45):
    make_cell(str(tmp_path / ".aegis" / "rules"), name, cell_type="trap", created_days_ago=age)
    if tp or fp or triggers:
        write_evidence(tmp_path, name, triggers=triggers or tp + fp, tp=tp, fp=fp)


def _invariant(tmp_path, name, tp=0, fp=0, age=45):
    make_cell(str(tmp_path / ".aegis" / "rules"), name, cell_type="invariant", created_days_ago=age)
    if tp or fp:
        write_evidence(tmp_path, name, triggers=tp + fp, tp=tp, fp=fp)


def _ids(candidates):
    return [c["rule_id"] for c in candidates]


class TestPromotion:
    def test_a_proven_trap_is_a_promotion_candidate(self, tmp_path):
        _trap(_ws(tmp_path), "proven", tp=20)
        (candidate,) = evaluate_promotions(tmp_path)
        assert (candidate["rule_id"], candidate["from_type"], candidate["to_type"]) == ("proven", "trap", "invariant")
        assert candidate["triggers"] == 20 and candidate["fitness"] > 0.85

    def test_an_invariant_promotes_to_gate(self, tmp_path):
        _invariant(_ws(tmp_path), "inv", tp=30)
        assert [(c["from_type"], c["to_type"]) for c in evaluate_promotions(tmp_path)] == [("invariant", "gate")]

    def test_19_verdicts_are_not_enough_however_clean(self, tmp_path):
        _trap(_ws(tmp_path), "few", tp=19)
        assert evaluate_promotions(tmp_path) == []

    def test_the_bound_not_the_raw_rate_decides(self, tmp_path):
        """24 of 25 is a 96% rate, but its Wilson bound (0.839) is below 0.85."""
        _trap(_ws(tmp_path), "almost", tp=24, fp=1)
        assert evaluate_promotions(tmp_path) == []

    def test_bare_triggers_are_not_failures(self, tmp_path):
        _trap(_ws(tmp_path), "relevant", tp=20, triggers=60)
        assert _ids(evaluate_promotions(tmp_path)) == ["relevant"]

    def test_age_29_is_too_young_and_30_is_old_enough(self, tmp_path):
        _ws(tmp_path)
        _trap(tmp_path, "age-29", tp=25, age=29)
        _trap(tmp_path, "age-30", tp=25, age=30)
        assert _ids(evaluate_promotions(tmp_path)) == ["age-30"]

    def test_an_empty_workspace_has_no_candidates(self, tmp_path):
        _ws(tmp_path)
        assert evaluate_promotions(tmp_path) == [] and evaluate_demotions(tmp_path) == []


class TestDemotionAndArchive:
    def test_a_misfiring_invariant_is_demoted_to_trap(self, tmp_path):
        _invariant(_ws(tmp_path), "noisy", tp=6, fp=14)
        (candidate,) = evaluate_demotions(tmp_path)
        assert (candidate["rule_id"], candidate["from_type"], candidate["to_type"]) == ("noisy", "invariant", "trap")
        assert candidate["misfire"] > 0.5

    def test_a_misfiring_trap_is_archived_not_demoted(self, tmp_path):
        _trap(_ws(tmp_path), "noisy-trap", fp=3)
        assert evaluate_demotions(tmp_path) == []
        assert _ids(evaluate_archives(tmp_path)) == ["noisy-trap"]

    def test_three_straight_false_positives_clear_the_bound_and_five_of_six_do_not(self, tmp_path):
        _ws(tmp_path)
        _invariant(tmp_path, "three-of-three", fp=3)
        _invariant(tmp_path, "five-of-six", tp=1, fp=5)
        assert _ids(evaluate_demotions(tmp_path)) == ["three-of-three"]

    def test_a_healthy_rule_and_a_rule_without_evidence_are_kept(self, tmp_path):
        """v3 demoted rules with no triggers for 90 days; no evidence is not misfiring."""
        _ws(tmp_path)
        _invariant(tmp_path, "good", tp=23, fp=2)
        _invariant(tmp_path, "quiet", age=400)
        assert evaluate_demotions(tmp_path) == []
        assert evaluate_archives(tmp_path) == []

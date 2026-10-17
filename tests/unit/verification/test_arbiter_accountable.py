"""Behavioral tests for T6: Accountable Arbiter (log-only)."""
from __future__ import annotations

from pathlib import Path

import pytest

from aegis_core.verification import (
    ArbitrationResult,
    Claim,
    Prediction,
    RiskCategory,
    Severity,
    ToolEvidence,
    Verdict,
)
from aegis_core.verification.arbiter import (
    arbitrate,
    brier_skill_score,
    calibration_summary,
    check_vendor_independence,
    prune_predictions,
    score_predictions,
    structural_ship_gaps,
    wilson_ci,
)


class TestSplitArbitrationResult:
    """ArbitrationResult separates Layer 1 verdict, infra status, and LLM predictions."""

    def test_split_fields_on_clean_pass(self):
        pred = Prediction(
            category=RiskCategory.PERSISTENCE_GAP,
            severity=Severity.MEDIUM,
            risk="State might not flush",
            mechanism="Missing fsync",
            affected_function="save_state",
            scope="aegis_core/state.py",
            observable="fix_touch_in_window",
            p=0.65,
        )
        claim = Claim(
            category=RiskCategory.PERSISTENCE_GAP,
            claim="Flushed via atomic_write_text",
            evidence_file="aegis_core/state.py",
            evidence_line=42,
            tests_covering=["test_save_state"],
        )
        ev = ToolEvidence(
            tool="persistence_checker",
            target="aegis_core/state.py",
            verdict=True,
            detail="All writes persisted",
        )

        res = arbitrate([pred], [claim], [ev])

        assert isinstance(res, ArbitrationResult)
        assert res.layer1_verdict == "PASS"
        assert res.infra_status == "ok"
        assert isinstance(res.llm_predictions, tuple)
        assert len(res.llm_predictions) == 1
        assert res.llm_predictions[0] == pred
        # Backward-compatible properties/fields
        assert res.verdict == Verdict.SHIP
        assert res.decision == "SHIP"
        assert isinstance(res.confidence, float)
        assert isinstance(res.rationale, str) and len(res.rationale) > 0
        assert res.predictions == [pred]
        assert isinstance(res.verdict_id, str) and len(res.verdict_id) > 0

    def test_split_fields_on_layer1_fail_and_spec_failure(self):
        ev_fail = ToolEvidence(
            tool="import_guard",
            target="aegis_core/foo.py",
            verdict=False,
            detail="Boundary violation",
        )
        res = arbitrate([], [], [ev_fail], spec_agent_failed=True)
        assert res.layer1_verdict == "FAIL"
        assert res.infra_status == "unverified"
        assert res.llm_predictions == ()
        assert res.verdict == Verdict.BLOCK
        assert res.decision == "BLOCK"


class TestExtendedPredictionSchema:
    """Prediction supports accountable calibration fields and legacy compatibility."""

    def test_prediction_defaults_and_legacy_aliases(self):
        p = Prediction(
            category=RiskCategory.MISSING_COVERAGE,
            severity=Severity.HIGH,
            risk="Untested branch",
            mechanism="Error path skipped",
            affected_function="parse_header",
        )
        assert p.disposition == "logged"
        assert p.window_days == 14
        assert p.observable == "fix_touch_in_window"
        assert 0.0 <= p.p <= 1.0
        assert p.scope == "parse_header"
        assert p.target == "parse_header"
        assert p.claim_type == "fix_touch_in_window"
        assert p.horizon_commits == 10
        assert isinstance(p.id, str) and len(p.id) > 0

    def test_prediction_explicit_accountable_fields(self):
        p = Prediction(
            id="pred-001",
            verdict_id="verd-123",
            ts=1700000000.0,
            tree="abc1234",
            backend="anthropic/claude-3-5-sonnet",
            scope="aegis_core/verification/arbiter.py",
            observable="revert_in_window",
            window_days=14,
            p=0.80,
            disposition="overridden",
        )
        assert p.id == "pred-001"
        assert p.verdict_id == "verd-123"
        assert p.ts == 1700000000.0
        assert p.tree == "abc1234"
        assert p.backend == "anthropic/claude-3-5-sonnet"
        assert p.scope == "aegis_core/verification/arbiter.py"
        assert p.observable == "revert_in_window"
        assert p.window_days == 14
        assert p.p == 0.80
        assert p.disposition == "overridden"
        assert p.target == "aegis_core/verification/arbiter.py"
        assert p.claim_type == "revert_in_window"


class TestStructuralShipGaps:
    """structural_ship_gaps deterministically flags missing tests and high rule-miss history."""

    def test_flags_changed_source_without_test_and_high_miss_history(self):
        changed_files = [
            "aegis_core/new_feature.py",
            "aegis_core/covered_module.py",
            "aegis_core/frequent_offender.py",
        ]
        all_files = [
            "aegis_core/new_feature.py",
            "aegis_core/covered_module.py",
            "aegis_core/frequent_offender.py",
            "tests/unit/core/test_covered_module.py",
            "tests/unit/core/test_frequent_offender.py",
        ]
        rule_miss_counts = {
            "aegis_core/frequent_offender.py": 5,
            "aegis_core/covered_module.py": 1,
        }

        gaps = structural_ship_gaps(
            changed_files,
            all_files,
            rule_miss_counts=rule_miss_counts,
        )
        by_file = {g["file"]: g for g in gaps}

        assert "aegis_core/new_feature.py" in by_file
        assert "missing_test" in by_file["aegis_core/new_feature.py"]["reasons"]

        assert "aegis_core/frequent_offender.py" in by_file
        assert "high_rule_miss_history" in by_file["aegis_core/frequent_offender.py"]["reasons"]

        assert "aegis_core/covered_module.py" not in by_file


class TestCalibrationScoringAndPruning:
    """Calibration math, heeded exclusion, deduplication, thresholds, and 60-day pruning."""

    def test_wilson_ci_matches_reference_formula(self):
        assert wilson_ci(0, 0) == (0.0, 1.0)
        lo, hi = wilson_ci(14, 20)
        assert 0.48 < lo < 0.49
        assert 0.85 < hi < 0.86

    def test_brier_skill_score_computation(self):
        probs = [0.9, 0.8, 0.1, 0.2]
        outcomes = [1, 1, 0, 0]
        bss = brier_skill_score(probs, outcomes)
        assert bss > 0.85

    def test_filters_heeded_and_deduplicates_scope_observable(self):
        records = [
            # Logged and resolved True
            Prediction(
                id="p1",
                scope="aegis_core/a.py",
                observable="fix_touch_in_window",
                p=0.8,
                disposition="logged",
                outcome=True,
            ),
            # Duplicate (scope, observable) — must be deduplicated in n_effective
            Prediction(
                id="p2",
                scope="aegis_core/a.py",
                observable="fix_touch_in_window",
                p=0.7,
                disposition="logged",
                outcome=True,
            ),
            # Overridden and resolved False
            Prediction(
                id="p3",
                scope="aegis_core/b.py",
                observable="revert_in_window",
                p=0.6,
                disposition="overridden",
                outcome=False,
            ),
            # Heeded — must be excluded from accuracy scoring (treatment effect confounder)
            Prediction(
                id="p4",
                scope="aegis_core/c.py",
                observable="fix_touch_in_window",
                p=0.9,
                disposition="heeded",
                outcome=False,
            ),
        ]

        scored = score_predictions(records)
        assert scored["n_heeded_excluded"] == 1
        assert scored["n_raw"] == 3
        assert scored["n_effective"] == 2
        assert scored["hits"] == 1

        summary = calibration_summary(records)
        assert summary["status"] == "insufficient (n=2/25)"
        assert "insufficient (n=2/25)" in str(summary)
        assert summary["brier_skill_score"] is None
        assert summary["lift_suppressed"] is True

    def test_calibration_summary_thresholds_25_and_100_and_base_rate(self):
        # 30 effective predictions (< 100): status is ok, but Brier skill / lift is suppressed
        records_30 = [
            {
                "id": f"p-{i}",
                "scope": f"mod_{i}.py",
                "observable": "fix_touch_in_window",
                "p": 0.75 if i % 2 == 0 else 0.25,
                "disposition": "logged",
                "outcome": (i % 2 == 0),
            }
            for i in range(30)
        ]
        sum_30 = calibration_summary(records_30)
        assert sum_30["n_effective"] == 30
        assert sum_30["status"] == "ok"
        assert sum_30["brier_skill_score"] is None
        assert sum_30["lift_suppressed"] is True
        assert len(sum_30["wilson_ci"]) == 2

        # 100 effective predictions with base rate >= 5%: Brier skill score reported
        records_100 = [
            {
                "id": f"p-{i}",
                "scope": f"mod_{i}.py",
                "observable": "fix_touch_in_window",
                "p": 0.85 if i < 20 else 0.15,
                "disposition": "logged",
                "outcome": (i < 20),
            }
            for i in range(100)
        ]
        sum_100 = calibration_summary(records_100)
        assert sum_100["n_effective"] == 100
        assert sum_100["status"] == "ok"
        assert sum_100["lift_suppressed"] is False
        assert sum_100["brier_skill_score"] is not None
        assert sum_100["brier_skill_score"] > 0.0

        # 100 effective predictions with base rate < 5% (only 2/100 = 2%): suppressed
        records_low_base = [
            {
                "id": f"p-{i}",
                "scope": f"mod_{i}.py",
                "observable": "fix_touch_in_window",
                "p": 0.85 if i < 2 else 0.05,
                "disposition": "logged",
                "outcome": (i < 2),
            }
            for i in range(100)
        ]
        sum_low_base = calibration_summary(records_low_base)
        assert sum_low_base["lift_suppressed"] is True
        assert sum_low_base["brier_skill_score"] is None

    def test_prune_predictions_compacts_records_older_than_60_days(self):
        now_ts = 1_800_000_000.0
        old_ts = now_ts - (65 * 86400)
        recent_ts = now_ts - (10 * 86400)

        records = [
            {
                "id": "old-scored",
                "ts": old_ts,
                "scope": "a.py",
                "observable": "fix_touch_in_window",
                "p": 0.8,
                "disposition": "logged",
                "outcome": True,
            },
            {
                "id": "old-unresolved",
                "ts": old_ts,
                "scope": "b.py",
                "observable": "fix_touch_in_window",
                "p": 0.4,
                "disposition": "logged",
                "outcome": None,
            },
            {
                "id": "recent-scored",
                "ts": recent_ts,
                "scope": "c.py",
                "observable": "revert_in_window",
                "p": 0.2,
                "disposition": "overridden",
                "outcome": False,
            },
        ]

        kept, buckets = prune_predictions(records, now_ts=now_ts, max_age_days=60)
        kept_ids = [r["id"] for r in kept]
        assert "old-scored" not in kept_ids
        assert "old-unresolved" in kept_ids
        assert "recent-scored" in kept_ids
        assert buckets["pruned_count"] == 1
        assert buckets["hits"] == 1


class TestVendorIndependence:
    """check_vendor_independence warns on same-vendor or unknown vendor pairs."""

    def test_warns_when_same_vendor_family(self):
        msg = check_vendor_independence("claude-3-5-sonnet", "claude-code")
        assert "Same-vendor arbiter provides prompt isolation only, not model independence." in msg

    def test_warns_when_vendor_unknown(self):
        msg = check_vendor_independence(None, "claude-code")
        assert len(msg) > 0
        assert "unknown" in msg.lower() or "unverified" in msg.lower()

    def test_no_warning_when_cross_vendor(self):
        msg = check_vendor_independence("gemini-2.5-pro", "claude-code")
        assert msg == ""


class TestVerifyCalibrationCli:
    """CLI integration test for `aegis verify --calibration`."""

    def test_verify_calibration_cli_human_and_json(self, tmp_path: Path, capsys):
        import argparse
        import json
        from aegis_cli.verify import run_verify

        ws = tmp_path / "ws"
        state_dir = ws / ".aegis" / "state"
        state_dir.mkdir(parents=True)
        preds_path = state_dir / "arbiter_predictions.jsonl"
        preds_path.write_text(
            json.dumps({
                "id": "p-1",
                "scope": "aegis_core/foo.py",
                "observable": "fix_touch_in_window",
                "p": 0.75,
                "disposition": "logged",
                "outcome": True,
            })
            + "\n",
            encoding="utf-8",
        )

        args_human = argparse.Namespace(_root=ws, calibration=True, json=False)
        rc = run_verify(args_human)
        assert rc == 0
        out_human = capsys.readouterr().out
        assert "insufficient (n=1/25)" in out_human

        args_json = argparse.Namespace(_root=ws, calibration=True, json=True)
        rc_json = run_verify(args_json)
        assert rc_json == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["status"] == "insufficient (n=1/25)"
        assert payload["n_effective"] == 1
        assert payload["hits"] == 1


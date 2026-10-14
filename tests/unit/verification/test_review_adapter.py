"""Tests for the review adapter — Prosecutor/Defender → Arbiter pipeline."""
import json
import os
import tempfile

import pytest

from aegis_core.verification import RiskCategory, Severity, Verdict
from aegis_core.verification.review_adapter import (
    _classify_finding,
    findings_to_claims,
    findings_to_predictions,
    get_latest_arbitration_evidence,
    get_next_cycle_number,
    run_review_arbitration,
    save_arbitration_evidence,
)


class TestClassifyFinding:
    """Keyword → RiskCategory mapping."""

    def test_path_traversal_keyword(self):
        assert _classify_finding("Path traversal via --files") == RiskCategory.PATH_TRAVERSAL

    def test_code_injection_keyword(self):
        assert _classify_finding("Code injection via .format()") == RiskCategory.CODE_INJECTION

    def test_shell_keyword(self):
        assert _classify_finding("shell=True in subprocess") == RiskCategory.SHELL_INJECTION

    def test_dry_violation_keyword(self):
        assert _classify_finding("DRY violation: copy-pasted logic") == RiskCategory.DRY_VIOLATION

    def test_missing_test_keyword(self):
        assert _classify_finding("--force promote is untested") == RiskCategory.MISSING_COVERAGE

    def test_doc_drift_keyword(self):
        assert _classify_finding("README code example crashes") == RiskCategory.DOC_DRIFT

    def test_portability_keyword(self):
        assert _classify_finding("Windows path escaping fails") == RiskCategory.PLATFORM_INCOMPATIBLE

    def test_unknown_falls_back(self):
        assert _classify_finding("something completely novel") == RiskCategory.CONTRACT_DRIFT


class TestFindingsToObjects:
    """Conversion of JSON dicts to Prediction/Claim objects."""

    def test_prosecutor_finding_to_prediction(self):
        findings = [{
            "severity": "BLOCK",
            "issue": "Path traversal in verify.py",
            "file": "soma_cli/verify.py",
            "function": "resolve_target_files",
        }]
        preds = findings_to_predictions(findings)
        assert len(preds) == 1
        assert preds[0].category == RiskCategory.PATH_TRAVERSAL
        assert preds[0].severity == Severity.CRITICAL
        assert preds[0].affected_function == "resolve_target_files"

    def test_warn_maps_to_high(self):
        findings = [{"severity": "WARN", "issue": "DRY violation in tools.py"}]
        preds = findings_to_predictions(findings)
        assert preds[0].severity == Severity.HIGH

    def test_info_maps_to_low(self):
        findings = [{"severity": "INFO", "issue": "Missing type hint"}]
        preds = findings_to_predictions(findings)
        assert preds[0].severity == Severity.LOW

    def test_defender_confirmed_becomes_claim(self):
        verifications = [{
            "verdict": "CONFIRMED",
            "claim": "Path containment check prevents traversal",
            "file": "soma_cli/verify.py",
            "line": 73,
            "tests": ["test_path_containment"],
        }]
        claims = findings_to_claims(verifications)
        assert len(claims) == 1
        assert claims[0].category == RiskCategory.PATH_TRAVERSAL
        assert claims[0].evidence_line == 73

    def test_defender_concern_excluded(self):
        """CONCERN verdicts are NOT converted to claims — they're undefended."""
        verifications = [
            {"verdict": "CONCERN", "claim": "Missing test coverage"},
            {"verdict": "CONFIRMED", "claim": "shell=True removed from subprocess"},
        ]
        claims = findings_to_claims(verifications)
        assert len(claims) == 1
        assert claims[0].category == RiskCategory.SHELL_INJECTION


class TestRunReviewArbitration:
    """End-to-end arbitration through the adapter."""

    def test_ship_when_all_defended(self):
        """Prosecutor finds issues, Defender addresses all → SHIP."""
        prosecutor = [
            {"severity": "WARN", "issue": "DRY violation in checkpoint helpers"},
        ]
        defender = [
            {"verdict": "CONFIRMED", "claim": "DRY violation addressed by extraction"},
        ]
        result = run_review_arbitration(prosecutor, defender)
        assert result.verdict == Verdict.SHIP

    def test_block_when_undefended_critical(self):
        """Prosecutor finds BLOCK issue, Defender has no matching claim → REVISE or BLOCK."""
        prosecutor = [
            {"severity": "BLOCK", "issue": "Code injection via .format() is exploitable"},
        ]
        defender = []  # No defense
        result = run_review_arbitration(prosecutor, defender)
        # Unmatched critical prediction → REVISE
        assert result.verdict in (Verdict.REVISE, Verdict.BLOCK)
        assert len(result.divergences) > 0

    def test_ship_when_no_findings(self):
        """No findings at all → SHIP."""
        result = run_review_arbitration([], [])
        assert result.verdict == Verdict.SHIP


class TestSaveArbitrationEvidence:
    """Evidence persistence for checkpoint gate."""

    def test_saves_json_file(self):
        prosecutor = [{"severity": "WARN", "issue": "DRY violation"}]
        defender = [{"verdict": "CONFIRMED", "claim": "DRY fixed"}]
        result = run_review_arbitration(prosecutor, defender)

        with tempfile.TemporaryDirectory() as tmpdir:
            path = save_arbitration_evidence(result, tmpdir, cycle=2)
            assert os.path.exists(path)
            with open(path) as f:
                record = json.load(f)
            assert record["cycle"] == 2
            assert record["verdict"] == "ship"

    def test_block_verdict_persisted(self):
        prosecutor = [
            {"severity": "BLOCK", "issue": "Path traversal unguarded"},
        ]
        defender = []
        result = run_review_arbitration(prosecutor, defender)

        with tempfile.TemporaryDirectory() as tmpdir:
            path = save_arbitration_evidence(result, tmpdir, cycle=1)
            with open(path) as f:
                record = json.load(f)
            assert record["verdict"] in ("block", "revise")
            assert record["divergence_count"] > 0


class TestCycleHelpers:
    """Cycle auto-increment and latest evidence retrieval."""

    def test_get_next_cycle_number_empty(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            assert get_next_cycle_number(tmpdir) == 1

    def test_get_next_cycle_number_increments(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ev_dir = os.path.join(tmpdir, ".soma", "evidence")
            os.makedirs(ev_dir, exist_ok=True)
            with open(os.path.join(ev_dir, "arbitration_cycle_1.json"), "w") as f:
                f.write("{}")
            with open(os.path.join(ev_dir, "arbitration_cycle_2.json"), "w") as f:
                f.write("{}")
            with open(os.path.join(ev_dir, "signals.jsonl"), "w") as f:
                f.write("")
            assert get_next_cycle_number(tmpdir) == 3

    def test_get_next_cycle_number_sparse(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ev_dir = os.path.join(tmpdir, ".soma", "evidence")
            os.makedirs(ev_dir, exist_ok=True)
            with open(os.path.join(ev_dir, "arbitration_cycle_4.json"), "w") as f:
                f.write("{}")
            assert get_next_cycle_number(tmpdir) == 5

    def test_cycle_counter_file_created_and_atomic(self):
        """Verify .cycle_counter persists monotonic increments under lock."""
        with tempfile.TemporaryDirectory() as tmpdir:
            counter_file = os.path.join(tmpdir, ".soma", "evidence", ".cycle_counter")
            c1 = get_next_cycle_number(tmpdir)
            assert c1 == 1
            assert os.path.isfile(counter_file)
            with open(counter_file, "r") as f:
                assert f.read().strip() == "1"

            c2 = get_next_cycle_number(tmpdir)
            assert c2 == 2
            with open(counter_file, "r") as f:
                assert f.read().strip() == "2"

    def test_cycle_counter_fallback_recovery(self):
        """Verify fallback recovery scans directory if counter file is missing or corrupted."""
        with tempfile.TemporaryDirectory() as tmpdir:
            ev_dir = os.path.join(tmpdir, ".soma", "evidence")
            os.makedirs(ev_dir, exist_ok=True)
            with open(os.path.join(ev_dir, "arbitration_cycle_7.json"), "w") as f:
                f.write("{}")
            counter_file = os.path.join(ev_dir, ".cycle_counter")
            # Counter missing
            assert not os.path.exists(counter_file)
            assert get_next_cycle_number(tmpdir) == 8
            assert os.path.isfile(counter_file)
            with open(counter_file, "r") as f:
                assert f.read().strip() == "8"

            # Counter corrupted without file written: recovers to 8 from disk
            with open(counter_file, "w") as f:
                f.write("corrupt_data")
            assert get_next_cycle_number(tmpdir) == 8

            # When arbitration_cycle_8.json is saved and counter is corrupted: recovers to 9
            with open(os.path.join(ev_dir, "arbitration_cycle_8.json"), "w") as f:
                f.write("{}")
            with open(counter_file, "w") as f:
                f.write("corrupt_data")
            assert get_next_cycle_number(tmpdir) == 9


    def test_get_latest_arbitration_evidence_empty(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cycle, data = get_latest_arbitration_evidence(tmpdir)
            assert cycle == 0
            assert data is None

    def test_get_latest_arbitration_evidence_finds_latest(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ev_dir = os.path.join(tmpdir, ".soma", "evidence")
            os.makedirs(ev_dir, exist_ok=True)
            with open(os.path.join(ev_dir, "arbitration_cycle_1.json"), "w") as f:
                json.dump({"cycle": 1, "verdict": "block"}, f)
            with open(os.path.join(ev_dir, "arbitration_cycle_2.json"), "w") as f:
                json.dump({"cycle": 2, "verdict": "ship"}, f)
            cycle, data = get_latest_arbitration_evidence(tmpdir)
            assert cycle == 2
            assert data is not None
            assert data["verdict"] == "ship"

    def test_get_next_cycle_number_oserror(self, monkeypatch):
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmpdir:
            ev_dir = Path(tmpdir) / ".soma" / "evidence"
            ev_dir.mkdir(parents=True)
            def mock_iterdir(self):
                raise OSError("Permission denied")
            monkeypatch.setattr(Path, "iterdir", mock_iterdir)
            assert get_next_cycle_number(tmpdir) == 1

    def test_get_latest_arbitration_evidence_oserror(self, monkeypatch):
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmpdir:
            ev_dir = Path(tmpdir) / ".soma" / "evidence"
            ev_dir.mkdir(parents=True)
            def mock_iterdir(self):
                raise OSError("Permission denied")
            monkeypatch.setattr(Path, "iterdir", mock_iterdir)
            cycle, data = get_latest_arbitration_evidence(tmpdir)
            assert cycle == 0
            assert data is None

    def test_get_latest_arbitration_evidence_no_matching_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ev_dir = os.path.join(tmpdir, ".soma", "evidence")
            os.makedirs(ev_dir, exist_ok=True)
            with open(os.path.join(ev_dir, "signals.jsonl"), "w") as f:
                f.write("")
            cycle, data = get_latest_arbitration_evidence(tmpdir)
            assert cycle == 0
            assert data is None

    def test_get_latest_arbitration_evidence_corrupted_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ev_dir = os.path.join(tmpdir, ".soma", "evidence")
            os.makedirs(ev_dir, exist_ok=True)
            with open(os.path.join(ev_dir, "arbitration_cycle_1.json"), "w") as f:
                f.write("not valid json{{{")
            cycle, data = get_latest_arbitration_evidence(tmpdir)
            assert cycle == 1
            assert data is None

    def test_cycle_helpers_ignore_subdirectories(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ev_dir = os.path.join(tmpdir, ".soma", "evidence")
            os.makedirs(os.path.join(ev_dir, "subdir_should_be_skipped"), exist_ok=True)
            with open(os.path.join(ev_dir, "arbitration_cycle_1.json"), "w") as f:
                json.dump({"cycle": 1, "verdict": "ship"}, f)
            assert get_next_cycle_number(tmpdir) == 2
            cycle, data = get_latest_arbitration_evidence(tmpdir)
            assert cycle == 1
            assert data is not None

    def test_save_arbitration_evidence_invalid_cycle(self):
        from aegis_core.verification import ArbitrationResult, Verdict
        res = ArbitrationResult(
            divergences=[],
            convergences=[],
            verdict=Verdict.SHIP,
            layer1_results=[],
            predictions=[],
            claims=[],
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            with pytest.raises(ValueError, match="cycle must be a positive integer"):
                save_arbitration_evidence(res, tmpdir, cycle=0)

    def test_save_arbitration_evidence_with_target_files(self):
        from aegis_core.verification import ArbitrationResult, Verdict
        res = ArbitrationResult(
            divergences=[],
            convergences=[],
            verdict=Verdict.SHIP,
            layer1_results=[],
            predictions=[],
            claims=[],
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            path = save_arbitration_evidence(
                res, tmpdir, cycle=1, target_files=["worker.py", "main.py"]
            )
            # Verify successive save in existing directory (tests exist_ok=True)
            path2 = save_arbitration_evidence(
                res, tmpdir, cycle=2, target_files=["worker.py"]
            )
            assert os.path.exists(path2)
            with open(path) as f:
                record = json.load(f)
            assert record["target_files"] == ["worker.py", "main.py"]

    def test_save_arbitration_evidence_cleanup_on_error(self, monkeypatch):
        from aegis_core.verification import ArbitrationResult, Verdict
        res = ArbitrationResult(
            divergences=[],
            convergences=[],
            verdict=Verdict.SHIP,
            layer1_results=[],
            predictions=[],
            claims=[],
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            ev_dir = os.path.join(tmpdir, ".soma", "evidence")
            def broken_dump(*args, **kwargs):
                raise RuntimeError("disk write failure")
            monkeypatch.setattr(json, "dump", broken_dump)
            with pytest.raises(RuntimeError, match="disk write failure"):
                save_arbitration_evidence(res, tmpdir, cycle=1)
            # Ensure no orphaned temp files remained in evidence dir
            leftover = [f for f in os.listdir(ev_dir) if f.endswith(".json")]
            assert leftover == []

    def test_save_arbitration_evidence_auto_cycle(self):
        from aegis_core.verification import ArbitrationResult, Verdict
        res = ArbitrationResult(
            divergences=[],
            convergences=[],
            verdict=Verdict.SHIP,
            layer1_results=[],
            predictions=[],
            claims=[],
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            p1 = save_arbitration_evidence(res, tmpdir)
            assert "arbitration_cycle_1.json" in p1
            with open(p1) as f:
                assert json.load(f)["cycle"] == 1

            p2 = save_arbitration_evidence(res, tmpdir)
            assert "arbitration_cycle_2.json" in p2
            with open(p2) as f:
                assert json.load(f)["cycle"] == 2

            counter_file = os.path.join(tmpdir, ".soma", "evidence", ".cycle_counter")
            assert os.path.isfile(counter_file)
            with open(counter_file) as f:
                assert f.read().strip() == "2"

            # Explicit higher cycle updates counter
            save_arbitration_evidence(res, tmpdir, cycle=10)
            with open(counter_file) as f:
                assert f.read().strip() == "10"

            # Explicit lower cycle does not decrease counter
            save_arbitration_evidence(res, tmpdir, cycle=5)
            with open(counter_file) as f:
                assert f.read().strip() == "10"

        with tempfile.TemporaryDirectory() as fresh_dir:
            # Explicit cycle=1 in fresh dir without pre-existing counter
            save_arbitration_evidence(res, fresh_dir, cycle=1)
            fresh_cf = os.path.join(fresh_dir, ".soma", "evidence", ".cycle_counter")
            assert os.path.isfile(fresh_cf)
            with open(fresh_cf) as f:
                assert f.read().strip() == "1"

    def test_save_arbitration_evidence_git_metadata(self):
        from pathlib import Path
        import subprocess
        from aegis_core.verification import ArbitrationResult, Verdict
        res = ArbitrationResult(
            divergences=[],
            convergences=[],
            verdict=Verdict.SHIP,
            layer1_results=[],
            predictions=[],
            claims=[],
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            subprocess.run(["git", "init"], cwd=tmpdir, capture_output=True, check=True)
            subprocess.run(["git", "config", "user.name", "Tester"], cwd=tmpdir, check=True)
            subprocess.run(["git", "config", "user.email", "tester@example.com"], cwd=tmpdir, check=True)
            dummy = Path(tmpdir) / "dummy.txt"
            dummy.write_text("hello")
            subprocess.run(["git", "add", "dummy.txt"], cwd=tmpdir, check=True)
            subprocess.run(["git", "commit", "-m", "initial"], cwd=tmpdir, check=True)

            p = save_arbitration_evidence(res, tmpdir)
            with open(p) as f:
                record = json.load(f)
            assert "commit_sha" in record
            assert len(record["commit_sha"]) == 40
            assert "tree_hash" in record
            assert len(record["tree_hash"]) == 40

    def test_save_arbitration_evidence_git_failure_graceful(self, monkeypatch):
        import subprocess
        from aegis_core.verification import ArbitrationResult, Verdict
        res = ArbitrationResult(
            divergences=[],
            convergences=[],
            verdict=Verdict.SHIP,
            layer1_results=[],
            predictions=[],
            claims=[],
        )

        def _raise_git(*args, **kwargs):
            raise OSError("git not found")

        monkeypatch.setattr(subprocess, "run", _raise_git)

        with tempfile.TemporaryDirectory() as tmpdir:
            p = save_arbitration_evidence(res, tmpdir)
            with open(p) as f:
                record = json.load(f)
            assert "commit_sha" not in record
            assert "tree_hash" not in record


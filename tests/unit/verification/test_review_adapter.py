"""Tests for the review adapter — Prosecutor/Defender → Arbiter pipeline."""
from aegis_core.verification import RiskCategory, Severity, Verdict
from aegis_core.verification.review_adapter import (
    _classify_finding,
    findings_to_claims,
    findings_to_predictions,
    run_review_arbitration,
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



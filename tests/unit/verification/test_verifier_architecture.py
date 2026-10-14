"""Tests for Verifier OOP Architecture and Pipeline (Phase 20).

Verifies:
- DeterministicVerifier Layer 1 orchestration & GitWorkspace integration
- AgentBackend hierarchy (DirectSDKBackend, MCPSamplingBackend, InBandChargeSheetBackend)
- ChargeSheet and Information Partitioning Guard (SOMA-V01)
- AdversarialVerifier Layer 2 orchestration & in-band rebuttal claims
- Arbiter OOP integration
- VerificationPipeline end-to-end execution
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from aegis_core.verification import (
    AdversarialVerifier,
    AgentBackend,
    Arbiter,
    ChargeSheet,
    Claim,
    DeterministicVerifier,
    DirectSDKBackend,
    InBandChargeSheetBackend,
    MCPSamplingBackend,
    Prediction,
    RiskCategory,
    Severity,
    ToolEvidence,
    Verdict,
    VerificationPipeline,
)
from aegis_core.workspace import GitWorkspace, Workspace


class TestDeterministicVerifier:
    """Verifies DeterministicVerifier execution and GitWorkspace auto-discovery."""

    def test_verify_explicit_files(self, tmp_path):
        src = tmp_path / "calc.py"
        src.write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
        test = tmp_path / "test_calc.py"
        test.write_text("from calc import add\ndef test_add():\n    assert add(1, 2) == 3\n", encoding="utf-8")

        verifier = DeterministicVerifier()
        ws = Workspace(root=tmp_path)
        evidence = verifier.verify(changed_files=["calc.py"], workspace=ws)
        assert isinstance(evidence, list)
        assert all(isinstance(e, ToolEvidence) for e in evidence)

    def test_verify_git_workspace_auto_discovers_changed_files(self, tmp_path):
        import subprocess

        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-b", "main"], cwd=str(repo), check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=str(repo), check=True)
        subprocess.run(["git", "config", "user.name", "Tester"], cwd=str(repo), check=True)

        tracked = repo / "module.py"
        tracked.write_text("def fn():\n    return 1\n", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=str(repo), check=True)
        subprocess.run(["git", "commit", "-m", "Init"], cwd=str(repo), check=True, capture_output=True)

        tracked.write_text("def fn():\n    return 2\n", encoding="utf-8")

        ws = GitWorkspace(root=repo)
        assert "module.py" in ws.get_changed_files()

        verifier = DeterministicVerifier()
        evidence = verifier.verify(changed_files=None, workspace=ws)
        assert isinstance(evidence, list)


class TestAgentBackendHierarchy:
    """Verifies DirectSDKBackend, MCPSamplingBackend, and InBandChargeSheetBackend."""

    def test_direct_sdk_backend_with_callable(self):
        backend = DirectSDKBackend(lambda prompt: "mock response")
        assert backend.generate("test prompt") == "mock response"

    def test_direct_sdk_backend_with_provider_object(self):
        class MockProvider:
            def generate(self, prompt: str) -> str:
                return f"echo: {prompt}"

        backend = DirectSDKBackend(MockProvider())
        assert backend.generate("hello") == "echo: hello"

    def test_direct_sdk_backend_invalid_type_raises(self):
        with pytest.raises(TypeError, match="must be callable or provide .generate"):
            DirectSDKBackend(12345).generate("hi")

    def test_mcp_sampling_backend_capability_check(self):
        session_no_caps = MagicMock(client_capabilities={})
        backend1 = MCPSamplingBackend(session=session_no_caps)
        assert not backend1.is_available()
        with pytest.raises(RuntimeError, match="not supported"):
            backend1.generate("prompt")

        session_with_caps = MagicMock(
            client_capabilities={"sampling": {}},
            sample_message=MagicMock(return_value="sampled response"),
        )
        backend2 = MCPSamplingBackend(session=session_with_caps, timeout=5.0)
        assert backend2.is_available()
        assert backend2.generate("prompt") == "sampled response"
        session_with_caps.sample_message.assert_called_once_with("prompt", timeout=5.0)

    def test_in_band_charge_sheet_backend_signature_synthesis(self):
        backend = InBandChargeSheetBackend()
        prompt = (
            "## Function Signatures\n"
            "```python\n"
            "def authenticate_user(token: str) -> bool:\n"
            "def revoke_session(session_id: str) -> None:\n"
            "```\n"
        )
        res = backend.generate(prompt)
        data = json.loads(res)
        assert isinstance(data, list)
        functions_charged = {d["affected_function"] for d in data}
        assert "authenticate_user" in functions_charged
        assert "revoke_session" in functions_charged
        assert all(d["category"] in [c.value for c in RiskCategory] for d in data)


class TestInformationPartitioningGuard:
    """Verifies Information Partitioning Guard (SOMA-V01) on ChargeSheet."""

    def test_charge_sheet_sanitization(self):
        pred = Prediction(
            category=RiskCategory.PATH_TRAVERSAL,
            severity=Severity.CRITICAL,
            risk="File escape via traversal",
            mechanism="Unguarded relative path resolution",
            affected_function="read_file",
        )
        ev = ToolEvidence(
            tool="import_guard",
            target="io_utils.py",
            verdict=True,
            detail="All imports guarded",
        )
        sheet = ChargeSheet(
            target_files=["io_utils.py"],
            predictions=[pred],
            layer1_evidence=[ev],
        )

        d = sheet.to_dict()
        assert d["status"] == "CHARGE_SHEET"
        assert d["target_files"] == ["io_utils.py"]
        assert len(d["charges"]) == 1
        assert d["charges"][0]["category"] == "path_traversal"
        assert d["charges"][0]["affected_function"] == "read_file"

        # Information Partitioning Guard (SOMA-V01) Invariant:
        # Raw task plan and eval criteria must never appear in the serialized charge sheet
        assert "task_plan" not in d
        assert "eval_criteria" not in d
        assert "system_prompt" not in d


class TestAdversarialVerifierAndInBandRebuttal:
    """Verifies AdversarialVerifier with charge sheet generation and direct in-band rebuttal."""

    def test_generate_charge_sheet(self, tmp_path):
        f = tmp_path / "api.py"
        f.write_text("def execute_transaction(amount: float):\n    pass\n", encoding="utf-8")

        verifier = AdversarialVerifier()
        sheet = verifier.generate_charge_sheet(
            changed_files=["api.py"],
            workspace=Workspace(root=tmp_path),
            task_plan="Implement banking transaction",
            layer1_evidence=[],
        )

        assert isinstance(sheet, ChargeSheet)
        assert len(sheet.predictions) > 0
        assert any(p.affected_function == "execute_transaction" for p in sheet.predictions)

    def test_verify_with_direct_rebuttal_claims(self, tmp_path):
        f = tmp_path / "api.py"
        f.write_text("def execute_transaction(amount: float):\n    pass\n", encoding="utf-8")

        verifier = AdversarialVerifier()
        rebuttal = [
            Claim(
                category=RiskCategory.MISSING_COVERAGE,
                claim="Covered in test_transaction",
                evidence_file="tests/test_tx.py",
                evidence_line=12,
                tests_covering=["test_transaction"],
            ),
            {
                "category": "unguarded_transition",
                "claim": "Preconditions checked at line 3",
                "evidence_file": "api.py",
                "evidence_line": 3,
                "tests_covering": ["test_preconditions"],
            },
        ]

        preds, claims, spec_failed = verifier.verify(
            changed_files=["api.py"],
            workspace=Workspace(root=tmp_path),
            task_plan="Implement banking transaction",
            layer1_evidence=[],
            rebuttal_claims=rebuttal,
        )

        assert not spec_failed
        assert len(preds) > 0
        assert len(claims) == 2
        assert any(c.category == RiskCategory.MISSING_COVERAGE for c in claims)
        assert any(c.category == RiskCategory.UNGUARDED_TRANSITION for c in claims)


class TestVerificationPipeline:
    """Verifies VerificationPipeline in layer1_only, in-band, and full arbitration modes."""

    def test_pipeline_layer1_only(self, tmp_path):
        f = tmp_path / "clean.py"
        f.write_text("def hello():\n    return 'world'\n\ndef main():\n    hello()\n", encoding="utf-8")

        pipeline = VerificationPipeline()
        res = pipeline.run(
            changed_files=["clean.py"],
            workspace=tmp_path,
            layer1_only=True,
        )

        assert res.layer1_passed
        assert res.passed
        assert res.verdict == Verdict.SHIP
        assert res.charge_sheet is None

    def test_pipeline_in_band_mode_returns_charge_sheet(self, tmp_path):
        f = tmp_path / "auth.py"
        f.write_text("def login(user, pw):\n    return True\n\ndef main():\n    login('a', 'b')\n", encoding="utf-8")

        pipeline = VerificationPipeline()
        res = pipeline.run(
            changed_files=["auth.py"],
            workspace=tmp_path,
            task_plan="Add login logic",
            in_band=True,
            rebuttal=None,
        )

        assert res.verdict == Verdict.REVISE
        assert not res.passed
        assert res.charge_sheet is not None
        assert len(res.charge_sheet.predictions) > 0

    def test_pipeline_in_band_rebuttal_arbitrates_to_ship(self, tmp_path):
        f = tmp_path / "auth.py"
        f.write_text("def login(user, pw):\n    return True\n\ndef main():\n    login('a', 'b')\n", encoding="utf-8")

        pipeline = VerificationPipeline()
        # Active agent provides rebuttal addressing the categories
        rebuttal = [
            {
                "category": "missing_coverage",
                "claim": "Tested in test_auth.py",
                "evidence_file": "tests/test_auth.py",
                "evidence_line": 5,
                "tests_covering": ["test_login_success"],
            },
            {
                "category": "unguarded_transition",
                "claim": "Guarded at line 1",
                "evidence_file": "auth.py",
                "evidence_line": 1,
                "tests_covering": ["test_login_invalid"],
            },
        ]

        res = pipeline.run(
            changed_files=["auth.py"],
            workspace=tmp_path,
            task_plan="Add login logic",
            in_band=True,
            rebuttal=rebuttal,
        )

        assert res.arbitration_result is not None
        assert res.verdict == Verdict.SHIP
        assert res.passed

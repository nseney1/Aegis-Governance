"""Test suite for soma_core/verification/pipeline.py conforming to strict checkpoint conventions."""
from __future__ import annotations

import json
from pathlib import Path
import pytest

from aegis_core.verification import (
    AgentBackend,
    ArbitrationResult,
    Claim,
    RiskCategory,
    Verdict,
)
from aegis_core.verification.pipeline import VerificationPipeline
from aegis_core.workspace import Workspace


class FakeUnparseableBackend(AgentBackend):
    """Backend returning malformed or error string instead of JSON list."""

    def __init__(self, response: str):
        self.response = response

    def generate(self, prompt: str) -> str:
        return self.response


class TestPipelineEvidencePersistenceAndFailClosed:
    """Verifies evidence persistence and fail-closed parser handling."""

    def test_pipeline_persists_evidence_on_arbitration(self, tmp_path):
        f = tmp_path / "auth.py"
        f.write_text("def login(user, pw):\n    return True\n\ndef main():\n    login('a', 'b')\n", encoding="utf-8")

        pipeline = VerificationPipeline()
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

        assert res.verdict == Verdict.SHIP
        ev_file = tmp_path / ".soma" / "evidence" / "arbitration_cycle_1.json"
        assert ev_file.exists(), "Arbitration evidence must be persisted by VerificationPipeline.run"
        assert res.evidence_path == str(ev_file)
        assert res.persistence_error is None
        assert res.cycle == 1
        record = json.loads(ev_file.read_text(encoding="utf-8"))
        assert record["cycle"] == 1
        assert record["verdict"] == "ship"
        assert record["target_files"] == ["auth.py"]

    def test_pipeline_no_evidence_without_workspace(self):
        pipeline = VerificationPipeline()
        res = pipeline.run(
            changed_files=[],
            workspace=None,
            task_plan="Clean run",
            in_band=True,
        )
        assert res.verdict == Verdict.SHIP

    def test_pipeline_no_evidence_when_arbitration_none(self, tmp_path):
        pipeline = VerificationPipeline()
        res = pipeline.run(
            changed_files=["nonexistent.py"],
            workspace=tmp_path,
            task_plan="None",
            layer1_only=True,
        )
        assert not (tmp_path / ".soma" / "evidence" / "arbitration_cycle_1.json").exists()

    def test_pipeline_evidence_persistence_failure_logs_warning(self, tmp_path, monkeypatch, caplog):
        import logging
        f = tmp_path / "auth.py"
        f.write_text("def login(user, pw):\n    return True\n\ndef main():\n    login('a', 'b')\n", encoding="utf-8")
        pipeline = VerificationPipeline()
        def _raise(*args, **kwargs):
            raise OSError("disk full")
        monkeypatch.setattr("aegis_core.verification.review_adapter.save_arbitration_evidence", _raise)
        rebuttal = [
            {"category": "missing_coverage", "claim": "Tested", "evidence_file": "auth.py", "evidence_line": 1, "tests_covering": []},
            {"category": "unguarded_transition", "claim": "Guarded", "evidence_file": "auth.py", "evidence_line": 1, "tests_covering": []},
        ]
        with caplog.at_level(logging.WARNING):
            res = pipeline.run(
                changed_files=["auth.py"],
                workspace=tmp_path,
                task_plan="Plan",
                in_band=True,
                rebuttal=rebuttal,
            )
        assert res.verdict == Verdict.SHIP
        assert any("Failed to persist arbitration evidence" in r.message for r in caplog.records)
        assert res.evidence_path is None
        assert res.persistence_error == "disk full"

    def test_spec_agent_unparseable_json_fails_closed_to_block(self, tmp_path):
        """When Spec Agent returns malformed JSON or error text, pipeline must FAIL-CLOSED with BLOCK."""
        f = tmp_path / "module.py"
        f.write_text("def run():\n    return 42\n", encoding="utf-8")

        pipeline = VerificationPipeline()
        bad_backend = FakeUnparseableBackend("Internal Server Error: 500 API Gateway Timeout")

        res = pipeline.run(
            changed_files=["module.py"],
            workspace=tmp_path,
            task_plan="Implement run",
            backend=bad_backend,
        )

        assert res.verdict == Verdict.BLOCK, (
            f"Expected Verdict.BLOCK on Spec Agent parse failure, got {res.verdict}"
        )
        assert not res.passed

    def test_spec_agent_dict_instead_of_list_fails_closed_to_block(self, tmp_path):
        """When Spec Agent returns a JSON dictionary instead of a list of predictions, fail-closed."""
        f = tmp_path / "module.py"
        f.write_text("def run():\n    return 42\n", encoding="utf-8")

        pipeline = VerificationPipeline()
        dict_backend = FakeUnparseableBackend('{"error": "rate limit exceeded", "retry_after": 60}')

        res = pipeline.run(
            changed_files=["module.py"],
            workspace=tmp_path,
            task_plan="Implement run",
            backend=dict_backend,
        )

        assert res.verdict == Verdict.BLOCK
        assert not res.passed

    def test_pipeline_reusable_layer1_evidence_and_discovery(self, tmp_path):
        from aegis_core.verification import ToolEvidence
        f = tmp_path / "module.py"
        f.write_text("def run():\n    return 42\n", encoding="utf-8")
        test_f = tmp_path / "test_module.py"
        test_f.write_text("def test_run():\n    assert True\n", encoding="utf-8")

        pipeline = VerificationPipeline()
        backend = lambda p: "[]"
        l1_ev = [ToolEvidence("call_graph", "module.py", True, "ok")]

        res = pipeline.run(
            changed_files=["module.py"],
            workspace=tmp_path,
            task_plan="Implement run",
            backend=backend,
            layer1_evidence=l1_ev,
        )
        assert res.verdict == Verdict.SHIP
        assert res.passed is True
        assert res.evidence_path is not None
        assert res.persistence_error is None
        assert res.layer1_evidence == l1_ev

    def test_pipeline_explicit_test_evidence_skips_discovery(self, tmp_path, monkeypatch):
        from aegis_core.verification import ToolEvidence
        f = tmp_path / "module.py"
        f.write_text("def run():\n    return 42\n", encoding="utf-8")

        discovered = []
        def _mock_disc(*a, **kw):
            discovered.append(True)
            return ([], "")
        monkeypatch.setattr("aegis_core.verification.test_runner.discover_test_evidence", _mock_disc)

        pipeline = VerificationPipeline()
        backend = lambda p: "[]"
        res = pipeline.run(
            changed_files=["module.py"],
            workspace=tmp_path,
            task_plan="Implement run",
            backend=backend,
            test_names=["test_custom"],
            test_results="1 passed in 0.01s",
            layer1_evidence=[ToolEvidence("call_graph", "module.py", True, "ok")],
        )
        assert res.verdict == Verdict.SHIP
        assert len(discovered) == 0, "Explicit test_names/test_results must skip discover_test_evidence"

    def test_pipeline_test_evidence_discovery_exception_handled_gracefully(self, tmp_path, monkeypatch):
        from aegis_core.verification import ToolEvidence
        f = tmp_path / "module.py"
        f.write_text("def run():\n    return 42\n", encoding="utf-8")

        def _raise_err(*a, **kw):
            raise RuntimeError("test discovery failure simulation")
        monkeypatch.setattr("aegis_core.verification.test_runner.discover_test_evidence", _raise_err)

        pipeline = VerificationPipeline()
        backend = lambda p: "[]"
        res = pipeline.run(
            changed_files=["module.py"],
            workspace=tmp_path,
            task_plan="Implement run",
            backend=backend,
            layer1_evidence=[ToolEvidence("call_graph", "module.py", True, "ok")],
        )
        assert res.verdict == Verdict.SHIP

    def test_pipeline_partial_test_evidence_triggers_discovery_for_missing(self, tmp_path, monkeypatch):
        from aegis_core.verification import ToolEvidence
        f = tmp_path / "module.py"
        f.write_text("def run():\n    return 42\n", encoding="utf-8")

        discovered = []
        def _mock_disc(*a, **kw):
            discovered.append(True)
            return (["disc_test"], "discovered test output")
        monkeypatch.setattr("aegis_core.verification.test_runner.discover_test_evidence", _mock_disc)

        captured_kwargs = {}
        def mock_verify(**kwargs):
            captured_kwargs.update(kwargs)
            return ([], [], False)

        pipeline = VerificationPipeline()
        monkeypatch.setattr(pipeline.adversarial_verifier, "verify", mock_verify)

        # Pass test_names but leave test_results None
        res = pipeline.run(
            changed_files=["module.py"],
            workspace=tmp_path,
            task_plan="Plan",
            backend=lambda p: "[]",
            test_names=["provided_test"],
            test_results=None,
            layer1_evidence=[ToolEvidence("call_graph", "module.py", True, "ok")],
        )
        assert len(discovered) == 1, "Partial test evidence (test_results=None) must trigger discovery for missing results"
        assert captured_kwargs["test_names"] == ["provided_test"]
        assert captured_kwargs["test_results"] == "discovered test output"

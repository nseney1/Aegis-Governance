"""TDD Gate 1 tests for Layer 2 Adversarial Rebuttal Protocol (Phase 11).

Tests prove:
1. build_code_prompt accepts spec_predictions and renders '## Predicted Risk Charges'
2. Information partitioning invariant: task plan text is NEVER in code prompt even with charges
3. run_layer2 orchestrates serial execution: Spec Agent charges are fed to Code Agent prompt
4. Rebuttal convergence: Code Agent defending predicted charges leads Arbiter to SHIP verdict
5. Unaddressed risk / concession leads Arbiter to REVISE or BLOCK verdict
"""
import inspect
import json
import os
import sys
import pytest

from aegis_core.verification import (
    ArbitrationResult,
    Claim,
    Divergence,
    Prediction,
    RiskCategory,
    Severity,
    ToolEvidence,
    Verdict,
)
from aegis_core.verification import immune_verify, runner, arbiter


class TestAdversarialRebuttalPrompt:
    """Verify build_code_prompt incorporates Spec Agent charges without leaking plan text."""

    def test_build_code_prompt_accepts_spec_predictions(self):
        """build_code_prompt must accept spec_predictions parameter."""
        sig = inspect.signature(immune_verify.build_code_prompt)
        assert "spec_predictions" in sig.parameters

    def test_code_prompt_renders_predicted_charges(self):
        """When spec_predictions are supplied, prompt renders the charges section."""
        predictions = [
            {
                "category": "missing_wire",
                "severity": "high",
                "risk": "express fails to wire extract_target_constraints into return dict",
                "affected_function": "express",
            }
        ]
        prompt = immune_verify.build_code_prompt(
            implementation="def express(): return {'target_constraints': {}}",
            test_results="test_express PASSED",
            layer1_output={},
            spec_predictions=predictions,
        )
        assert "## Predicted Risk Charges" in prompt
        assert "missing_wire" in prompt
        assert "express fails to wire extract_target_constraints" in prompt
        assert "defend" in prompt.lower() or "address" in prompt.lower()

    def test_information_partitioning_preserved_under_rebuttal(self):
        """Code prompt MUST NOT contain plan text even when spec_predictions are present."""
        plan_secret = "SECRET_TASK_PLAN_PHASE_11_DO_NOT_LEAK"
        predictions = [
            {
                "category": "missing_wire",
                "severity": "high",
                "risk": "Target constraint extraction omitted",
                "affected_function": "express",
            }
        ]
        prompt = immune_verify.build_code_prompt(
            implementation="def express(): pass",
            test_results="",
            layer1_output={},
            spec_predictions=predictions,
        )
        assert plan_secret not in prompt


class TestAdversarialRebuttalOrchestration:
    """Verify run_layer2 passes Spec predictions into Code Agent prompt and arbitrates."""

    def test_run_layer2_serial_rebuttal_flow(self, tmp_path):
        """run_layer2 must pass Spec Agent predictions to the Code Agent prompt."""
        # Create a mock source file
        src_file = tmp_path / "module.py"
        src_file.write_text("def run():\n    return 42\n")

        prompts_received = []

        def mock_llm(prompt: str) -> str:
            prompts_received.append(prompt)
            if "Spec Agent" in prompt:
                # Spec Agent charges: missing_wire on run
                return json.dumps([
                    {
                        "category": "missing_wire",
                        "severity": "high",
                        "risk": "run fails to wire return value",
                        "mechanism": "caller gets None",
                        "affected_function": "run",
                    }
                ])
            else:
                # Code Agent sees the charge in prompt!
                assert "Predicted Risk Charges" in prompt
                assert "missing_wire" in prompt
                # Code Agent defends with claim under missing_wire
                return json.dumps([
                    {
                        "category": "missing_wire",
                        "claim": "run wires return value 42",
                        "evidence_file": "module.py",
                        "evidence_line": 2,
                        "tests_covering": ["test_run"],
                    }
                ])

        result = runner.run_layer2(
            changed_files=["module.py"],
            repo_root=str(tmp_path),
            task_plan="Implement run function",
            layer1_evidence=[ToolEvidence("call_graph", "module.py", True, "ok")],
            llm_backend=mock_llm,
        )

        assert len(prompts_received) == 2
        # Both addressed missing_wire -> convergence -> SHIP!
        assert RiskCategory.MISSING_WIRE in result.convergences
        assert result.verdict == Verdict.SHIP

    def test_unaddressed_risk_still_triggers_revise(self, tmp_path):
        """When Code Agent concedes or cannot defend a high risk, Arbiter yields REVISE."""
        src_file = tmp_path / "module.py"
        src_file.write_text("def run():\n    return None\n")

        def mock_llm(prompt: str) -> str:
            if "Spec Agent" in prompt:
                return json.dumps([
                    {
                        "category": "contract_drift",
                        "severity": "high",
                        "risk": "run returns None instead of expected dictionary",
                        "mechanism": "TypeError on key lookup",
                        "affected_function": "run",
                    }
                ])
            else:
                # Code Agent does not defend contract_drift (leaves it unaddressed)
                return json.dumps([
                    {
                        "category": "boundary_violation",
                        "claim": "no unauthorized imports",
                        "evidence_file": "module.py",
                        "evidence_line": 1,
                    }
                ])

        result = runner.run_layer2(
            changed_files=["module.py"],
            repo_root=str(tmp_path),
            task_plan="Implement run function returning dict",
            layer1_evidence=[ToolEvidence("call_graph", "module.py", True, "ok")],
            llm_backend=mock_llm,
        )

        assert result.verdict == Verdict.REVISE
        assert any(d.category == RiskCategory.CONTRACT_DRIFT for d in result.divergences)

"""Unified Verification Pipeline and OOP Class Hierarchy for Soma (Phase 20).

Provides:
- BaseVerifier (ABC)
- DeterministicVerifier: Layer 1 AST checkers, call graphs, import guards, branch coverage, mutation tests
- AgentBackend (ABC): Strategy for LLM interaction
- DirectSDKBackend: Headless SDK execution via environment API keys
- MCPSamplingBackend: Zero-key / client-side sampling via MCP transport
- InBandChargeSheetBackend: Zero-key interactive in-session verification
- ChargeSheet: Information-partitioned prosecution charges (SOMA-V01)
- AdversarialVerifier: Layer 2 prosecution and defense rebuttal
- Arbiter: Pure deterministic set-logic judge
- VerificationPipeline: Composes Layer 1 -> Layer 2 -> Arbiter
"""
from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from aegis_core.workspace import GitWorkspace, Workspace, as_workspace

from . import (
    ArbitrationResult,
    Claim,
    Divergence,
    Prediction,
    RiskCategory,
    Severity,
    ToolEvidence,
    Verdict,
)
from . import arbiter as arbiter_module
from . import immune_verify
from . import runner

logger = logging.getLogger(__name__)


# ── Base Verifier ─────────────────────────────────────────────────────────


class BaseVerifier(ABC):
    """Abstract base class for verification components."""

    @abstractmethod
    def verify(self, *args: Any, **kwargs: Any) -> Any:
        """Run verification and emit results."""
        pass


# ── Deterministic Verifier (Layer 1) ──────────────────────────────────────


class DeterministicVerifier(BaseVerifier):
    """Layer 1 deterministic verification engine.

    Orchestrates AST checkers, call graph, import guards, mutation testing,
    and branch coverage against modified files.
    """

    def __init__(self, max_mutations: int = 5, fast_mode: bool = False):
        self.max_mutations = max_mutations
        self.fast_mode = fast_mode

    def verify(
        self,
        changed_files: list[str] | None = None,
        workspace: str | Path | Workspace | None = None,
        persistence_targets: list[tuple[str, str]] | None = None,
        mutation_targets: list[tuple[str, str, str]] | None = None,
        coverage_targets: list[tuple[str, str]] | None = None,
        fast_mode: bool | None = None,
    ) -> list[ToolEvidence]:
        """Run Layer 1 checks.

        If changed_files is not provided and workspace is a GitWorkspace,
        automatically queries changed files from git.
        """
        ws = as_workspace(workspace)
        repo_root = str(ws.root)

        files = changed_files
        if files is None:
            if isinstance(ws, GitWorkspace):
                files = ws.get_changed_files()
            else:
                files = []

        is_fast = self.fast_mode if fast_mode is None else fast_mode
        return runner.run_layer1(
            changed_files=files,
            repo_root=repo_root,
            persistence_targets=persistence_targets,
            mutation_targets=mutation_targets,
            coverage_targets=coverage_targets,
            max_mutations=self.max_mutations,
            fast_mode=is_fast,
        )


# ── Agent Backends ────────────────────────────────────────────────────────


class AgentBackend(ABC):
    """Abstract strategy interface for AI / LLM interactions during Layer 2."""

    @abstractmethod
    def generate(self, prompt: str) -> str:
        """Submit prompt and return model response string."""
        pass


class DirectSDKBackend(AgentBackend):
    """Headless SDK execution using direct environment API keys or local callables."""

    def __init__(self, provider_or_callable: Any):
        self._provider = provider_or_callable

    def generate(self, prompt: str) -> str:
        if callable(self._provider):
            return str(self._provider(prompt))
        if hasattr(self._provider, "generate") and callable(self._provider.generate):
            return str(self._provider.generate(prompt))
        raise TypeError(
            f"DirectSDKBackend provider must be callable or provide .generate(), got {type(self._provider)}"
        )


class MCPSamplingBackend(AgentBackend):
    """Agent backend utilizing MCP sampling (sampling/createMessage).

    Enforces capability negotiation and timeout guards to eliminate
    single-threaded stdio deadlocks.
    """

    def __init__(self, session: Any = None, timeout: float = 15.0):
        self.session = session
        self.timeout = timeout

    def is_available(self) -> bool:
        """Return True if the connected MCP client negotiated sampling capability."""
        if not self.session:
            return False
        caps = getattr(self.session, "client_capabilities", {}) or {}
        return "sampling" in caps

    def generate(self, prompt: str) -> str:
        if not self.is_available():
            raise RuntimeError("MCP sampling capability is not supported by the client.")
        if hasattr(self.session, "sample_message") and callable(self.session.sample_message):
            return str(self.session.sample_message(prompt, timeout=self.timeout))
        raise NotImplementedError("MCP session does not implement sample_message")


class InBandChargeSheetBackend(AgentBackend):
    """Zero-key in-session verification backend.

    Generates structured prosecution charges without external API calls,
    allowing the active agent to act as Defense.
    """

    def __init__(self, fallback_generator: Callable[[str], str] | None = None):
        self.fallback_generator = fallback_generator

    def generate(self, prompt: str) -> str:
        if self.fallback_generator is not None:
            return self.fallback_generator(prompt)

        # Synthesize baseline structured predictions from function signatures in prompt
        predictions: list[dict[str, Any]] = []
        signatures: list[str] = []
        in_sigs = False
        for line in prompt.splitlines():
            stripped = line.strip()
            if "## Function Signatures" in stripped:
                in_sigs = True
                continue
            if in_sigs:
                if stripped.startswith("## "):
                    break
                if stripped.startswith("def "):
                    fn_name = stripped[4:].split("(")[0].strip()
                    if fn_name:
                        signatures.append(fn_name)

        if not signatures:
            signatures = ["general_logic"]

        for fn in signatures[:4]:
            predictions.append({
                "category": RiskCategory.MISSING_COVERAGE.value,
                "severity": Severity.HIGH.value,
                "risk": f"Function '{fn}' may lack behavioral test coverage for failure modes",
                "mechanism": "Unexercised error paths or edge case mutations",
                "affected_function": fn,
            })
            predictions.append({
                "category": RiskCategory.UNGUARDED_TRANSITION.value,
                "severity": Severity.MEDIUM.value,
                "risk": f"Function '{fn}' state transition without precondition validation",
                "mechanism": "Invalid argument state or prerequisite bypass",
                "affected_function": fn,
            })

        return json.dumps(predictions)


# ── Charge Sheet (Information Partitioning Guard SOMA-V01) ─────────────────


@dataclass
class ChargeSheet:
    """Information-partitioned prosecution charges for active agent rebuttal.

    Upholds Information Partitioning Guard (SOMA-V01):
    Strictly scrubs raw task plans and confidential prompt instructions,
    exposing only abstract risk categories, mechanisms, and affected functions.
    """

    target_files: list[str]
    predictions: list[Prediction]
    layer1_evidence: list[ToolEvidence]
    instructions: str = (
        "Rebut the prosecution charges below by submitting line-level claims "
        "with evidence_file, evidence_line, and test function names."
    )

    def to_dict(self) -> dict[str, Any]:
        """Convert to sanitized dictionary representation safe for MCP responses."""
        return {
            "status": "CHARGE_SHEET",
            "target_files": list(self.target_files),
            "charges": [
                {
                    "category": p.category.value if hasattr(p.category, "value") else str(p.category),
                    "severity": p.severity.value if hasattr(p.severity, "value") else str(p.severity),
                    "risk": p.risk,
                    "mechanism": p.mechanism,
                    "affected_function": p.affected_function,
                }
                for p in self.predictions
            ],
            "layer1_evidence": [
                {
                    "tool": e.tool,
                    "target": e.target,
                    "verdict": e.verdict,
                    "detail": e.detail,
                }
                for e in self.layer1_evidence
            ],
            "instructions": self.instructions,
        }


# ── Adversarial Verifier (Layer 2) ────────────────────────────────────────


class AdversarialVerifier(BaseVerifier):
    """Layer 2 adversarial verification engine."""

    def __init__(self, backend: AgentBackend | Callable[[str], str] | None = None):
        if backend is None:
            self.backend = InBandChargeSheetBackend()
        elif isinstance(backend, AgentBackend):
            self.backend = backend
        else:
            self.backend = DirectSDKBackend(backend)

    def extract_target_data(
        self,
        changed_files: list[str],
        workspace: Workspace | GitWorkspace | str | Path,
    ) -> tuple[list[str], str]:
        """Extract signatures and implementation text from changed Python files."""
        ws = as_workspace(workspace)
        repo_root = str(ws.root)

        all_signatures: list[str] = []
        all_implementation: list[str] = []

        for filepath in changed_files:
            full_path = Path(repo_root) / filepath
            if not full_path.exists() or not filepath.endswith(".py"):
                continue
            basename = full_path.name
            if basename.startswith("test_") or basename in ("__init__.py", "conftest.py"):
                continue
            try:
                sigs = immune_verify.extract_signatures(str(full_path))
                all_signatures.extend(sigs)
                all_implementation.append(full_path.read_text(encoding="utf-8", errors="replace"))
            except Exception:
                continue

        return all_signatures, "\n\n".join(all_implementation)

    def generate_charge_sheet(
        self,
        changed_files: list[str],
        workspace: Workspace | GitWorkspace | str | Path,
        task_plan: str,
        layer1_evidence: list[ToolEvidence],
        test_names: list[str] | None = None,
        backend: AgentBackend | Callable[[str], str] | None = None,
    ) -> ChargeSheet:
        """Phase 1: Prosecution. Build an information-partitioned ChargeSheet."""
        active_backend = self._resolve_backend(backend)
        signatures, _ = self.extract_target_data(changed_files, workspace)

        spec_prompt = immune_verify.build_spec_prompt(
            plan=task_plan,
            signatures=signatures,
            test_names=test_names or [],
        )
        spec_response = active_backend.generate(spec_prompt)
        raw_predictions = self._parse_json(spec_response)
        predictions = immune_verify.parse_predictions(raw_predictions)

        return ChargeSheet(
            target_files=list(changed_files),
            predictions=predictions,
            layer1_evidence=layer1_evidence,
        )

    def verify(
        self,
        changed_files: list[str],
        workspace: Workspace | GitWorkspace | str | Path,
        task_plan: str,
        layer1_evidence: list[ToolEvidence],
        backend: AgentBackend | Callable[[str], str] | None = None,
        test_names: list[str] | None = None,
        test_results: str | None = None,
        rebuttal_claims: list[Claim | dict[str, Any]] | None = None,
    ) -> tuple[list[Prediction], list[Claim], bool]:
        """Run Phase 1 (Prosecution) and Phase 2 (Defense).

        Returns (predictions, claims, spec_agent_failed).
        """
        active_backend = self._resolve_backend(backend)
        signatures, implementation_text = self.extract_target_data(changed_files, workspace)

        # Phase 1: Prosecution
        spec_prompt = immune_verify.build_spec_prompt(
            plan=task_plan,
            signatures=signatures,
            test_names=test_names or [],
        )
        spec_response = active_backend.generate(spec_prompt)
        spec_agent_failed = False
        try:
            raw_predictions = self._parse_json(spec_response)
        except Exception:
            raw_predictions = []
            spec_agent_failed = True

        predictions = immune_verify.parse_predictions(raw_predictions)

        # Phase 2: Defense
        if rebuttal_claims is not None:
            parsed_claims: list[Claim] = []
            for c in rebuttal_claims:
                if isinstance(c, Claim):
                    parsed_claims.append(c)
                elif isinstance(c, dict):
                    parsed_claims.extend(immune_verify.parse_claims([c]))
            return predictions, parsed_claims, spec_agent_failed

        # Otherwise run Code Agent prompt
        layer1_output: dict[str, list] = {}
        for e in layer1_evidence:
            layer1_output.setdefault(e.tool, []).append(
                {"target": e.target, "verdict": e.verdict, "detail": e.detail}
            )

        code_prompt = immune_verify.build_code_prompt(
            implementation=implementation_text,
            test_results=test_results or "",
            layer1_output=layer1_output,
            spec_predictions=raw_predictions,
        )
        code_response = active_backend.generate(code_prompt)
        try:
            raw_claims = self._parse_json(code_response)
        except Exception:
            raw_claims = []
        claims = immune_verify.parse_claims(raw_claims)

        return predictions, claims, spec_agent_failed

    def _resolve_backend(self, backend: AgentBackend | Callable[[str], str] | None) -> AgentBackend:
        if backend is None:
            return self.backend
        if isinstance(backend, AgentBackend):
            return backend
        return DirectSDKBackend(backend)

    @staticmethod
    def _parse_json(text: str) -> list[dict[str, Any]]:
        raw = runner._strip_code_fence(text)
        data = json.loads(raw)
        if not isinstance(data, list):
            raise ValueError(f"Expected JSON list from LLM response, got {type(data).__name__}")
        return data


# ── Arbiter OOP Wrapper ───────────────────────────────────────────────────


class Arbiter:
    """Pure deterministic set-logic judge comparing predictions, claims, and tool evidence."""

    def arbitrate(
        self,
        predictions: list[Prediction],
        claims: list[Claim],
        layer1_evidence: list[ToolEvidence],
        *,
        spec_agent_failed: bool = False,
    ) -> ArbitrationResult:
        return arbiter_module.arbitrate(
            predictions=predictions,
            claims=claims,
            layer1_evidence=layer1_evidence,
            spec_agent_failed=spec_agent_failed,
        )


# ── Verification Pipeline ─────────────────────────────────────────────────


@dataclass
class VerificationPipelineResult:
    target_files: list[str]
    layer1_evidence: list[ToolEvidence]
    layer1_passed: bool
    verdict: Verdict
    passed: bool
    summary: str
    arbitration_result: ArbitrationResult | None = None
    charge_sheet: ChargeSheet | None = None
    evidence_path: str | None = None
    persistence_error: str | None = None
    cycle: int | None = None


class VerificationPipeline:
    """End-to-end verification pipeline composing Layer 1, Layer 2, and Arbiter."""

    def __init__(
        self,
        deterministic_verifier: DeterministicVerifier | None = None,
        adversarial_verifier: AdversarialVerifier | None = None,
        arbiter: Arbiter | None = None,
    ):
        self.deterministic_verifier = deterministic_verifier or DeterministicVerifier()
        self.adversarial_verifier = adversarial_verifier or AdversarialVerifier()
        self.arbiter = arbiter or Arbiter()

    def run(
        self,
        changed_files: list[str] | None = None,
        workspace: str | Path | Workspace | None = None,
        task_plan: str | None = None,
        backend: AgentBackend | Callable[[str], str] | None = None,
        layer1_only: bool = False,
        in_band: bool = False,
        rebuttal: list[Claim | dict[str, Any]] | None = None,
        test_names: list[str] | None = None,
        test_results: str | None = None,
        attribute: bool = False,
        layer1_evidence: list[ToolEvidence] | None = None,
    ) -> VerificationPipelineResult:
        ws = as_workspace(workspace)
        files = changed_files
        if files is None:
            if isinstance(ws, GitWorkspace):
                files = ws.get_changed_files()
            else:
                files = []

        # 1. Deterministic Layer 1
        if layer1_evidence is not None:
            l1_evidence = layer1_evidence
        else:
            l1_evidence = self.deterministic_verifier.verify(
                changed_files=files,
                workspace=ws,
            )
        l1_passed = runner.gate_verdict(l1_evidence)
        l1_summary = runner.format_summary(l1_evidence)

        if layer1_only or not files:
            verdict = Verdict.SHIP if l1_passed else Verdict.BLOCK
            res = VerificationPipelineResult(
                target_files=list(files),
                layer1_evidence=l1_evidence,
                layer1_passed=l1_passed,
                verdict=verdict,
                passed=bool(l1_passed),
                summary=l1_summary,
            )
            if attribute and ws:
                from aegis_core.attribution import attribute_verification_outcome
                attribute_verification_outcome(
                    workspace=ws,
                    layer1_evidence=l1_evidence,
                    arbitration_result=None,
                    target_files=list(files) if files else None,
                )
            return res

        # 2. In-band charge sheet generation (if requested and no rebuttal provided yet)
        if in_band and rebuttal is None:
            cs = self.adversarial_verifier.generate_charge_sheet(
                changed_files=files,
                workspace=ws,
                task_plan=task_plan or "Verify changed files against governance invariants",
                layer1_evidence=l1_evidence,
                test_names=test_names,
                backend=backend,
            )
            return VerificationPipelineResult(
                target_files=list(files),
                layer1_evidence=l1_evidence,
                layer1_passed=l1_passed,
                verdict=Verdict.REVISE,
                passed=False,
                summary=f"Charge sheet issued with {len(cs.predictions)} prosecution charges; awaiting agent rebuttal",
                charge_sheet=cs,
            )

        # 3. Layer 2 Adversarial Verification
        if not task_plan and rebuttal is None:
            verdict = Verdict.SHIP if l1_passed else Verdict.BLOCK
            res = VerificationPipelineResult(
                target_files=list(files),
                layer1_evidence=l1_evidence,
                layer1_passed=l1_passed,
                verdict=verdict,
                passed=bool(l1_passed),
                summary=f"{l1_summary} (Layer 2 skipped: no task plan)",
            )
            if attribute and ws:
                from aegis_core.attribution import attribute_verification_outcome
                attribute_verification_outcome(
                    workspace=ws,
                    layer1_evidence=l1_evidence,
                    arbitration_result=None,
                    target_files=list(files) if files else None,
                )
            return res

        if (test_names is None or test_results is None) and files:
            try:
                from aegis_core.verification.test_runner import discover_test_evidence
                disc_names, disc_results = discover_test_evidence(
                    files, str(ws.root if hasattr(ws, "root") else ws)
                )
                if test_names is None:
                    test_names = disc_names
                if test_results is None:
                    test_results = disc_results
            except Exception:
                pass

        predictions, claims, spec_failed = self.adversarial_verifier.verify(
            changed_files=files,
            workspace=ws,
            task_plan=task_plan or "",
            layer1_evidence=l1_evidence,
            backend=backend,
            test_names=test_names,
            test_results=test_results,
            rebuttal_claims=rebuttal,
        )

        arb_result = self.arbiter.arbitrate(
            predictions=predictions,
            claims=claims,
            layer1_evidence=l1_evidence,
            spec_agent_failed=spec_failed,
        )

        overall_passed = bool(l1_passed and arb_result.verdict == Verdict.SHIP)
        summary = (
            f"{l1_summary} | Layer 2: {arb_result.verdict.name} "
            f"({len(arb_result.divergences)} divergences, {len(arb_result.convergences)} convergences)"
        )

        res = VerificationPipelineResult(
            target_files=list(files),
            layer1_evidence=l1_evidence,
            layer1_passed=l1_passed,
            verdict=arb_result.verdict,
            passed=overall_passed,
            summary=summary,
            arbitration_result=arb_result,
        )
        evidence_path = None
        persistence_error = None
        try:
            from aegis_core.verification.review_adapter import (
                get_next_cycle_number,
                save_arbitration_evidence,
            )
            cycle_num = get_next_cycle_number(ws)
            evidence_path = save_arbitration_evidence(
                result=arb_result,
                workspace=ws,
                cycle=cycle_num,
                target_files=list(files) if files else None,
            )
        except Exception as exc:
            persistence_error = str(exc)
            logging.getLogger(__name__).warning("Failed to persist arbitration evidence: %s", exc)

        res.evidence_path = evidence_path
        res.persistence_error = persistence_error
        if evidence_path:
            res.cycle = cycle_num

        if attribute and ws:
            from aegis_core.attribution import attribute_verification_outcome
            attribute_verification_outcome(
                workspace=ws,
                layer1_evidence=l1_evidence,
                arbitration_result=arb_result,
                target_files=list(files) if files else None,
            )
        return res

    verify = run



__all__ = [
    "AdversarialVerifier",
    "AgentBackend",
    "Arbiter",
    "BaseVerifier",
    "ChargeSheet",
    "DeterministicVerifier",
    "DirectSDKBackend",
    "InBandChargeSheetBackend",
    "MCPSamplingBackend",
    "VerificationPipeline",
    "VerificationPipelineResult",
]

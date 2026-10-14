"""Verification framework shared types and risk taxonomy.

The taxonomy is the anti-collusion mechanism. Both the Spec Agent and Code Agent
must classify findings into these enumerated categories. The Arbiter then performs
pure set operations — no LLM judgment needed for comparison.
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class RiskCategory(Enum):
    """Fixed taxonomy of risk categories.

    Both agents MUST select from this list. This is what makes the Arbiter
    deterministic — it compares enum values, not natural language.
    """
    # Structural
    PERSISTENCE_GAP = "persistence_gap"          # State mutated but not serialized
    DEAD_CODE = "dead_code"                      # Unreachable branches
    MISSING_WIRE = "missing_wire"                # Function defined but not called from entry point

    # State
    IDEMPOTENCY_VIOLATION = "idempotency"        # Repeated calls produce different results
    RACE_CONDITION = "race_condition"             # TOCTOU or concurrent mutation
    STATE_CORRUPTION = "state_corruption"        # Valid input produces invalid state

    # Contracts
    UNGUARDED_TRANSITION = "unguarded_transition" # State promotion/demotion without prerequisite
    CONTRACT_DRIFT = "contract_drift"             # Signature changed but callers not updated
    TYPE_MISMATCH = "type_mismatch"              # Returns unexpected type (None vs float, inf vs int)

    # Data
    BOUNDARY_VIOLATION = "boundary_violation"     # Cross-module dependency that shouldn't exist
    DIVISION_BY_ZERO = "division_by_zero"        # Unguarded division
    OVERFLOW = "overflow"                        # Numeric overflow or underflow

    # Testing
    TAUTOLOGICAL_TEST = "tautological_test"      # Test that passes regardless of implementation
    MISSING_COVERAGE = "missing_coverage"        # Changed code not exercised by any test

    # Security (added for Supercell review)
    CODE_INJECTION = "code_injection"            # Untrusted input in exec/eval/format
    PATH_TRAVERSAL = "path_traversal"            # User paths escape containment root
    SHELL_INJECTION = "shell_injection"          # subprocess shell=True with user input

    # Quality
    DRY_VIOLATION = "dry_violation"              # Copy-pasted logic across modules
    DOC_DRIFT = "doc_drift"                      # Documentation diverges from implementation
    CONVENTION_VIOLATION = "convention_violation" # Schema/naming doesn't match existing instances

    # Portability
    PLATFORM_INCOMPATIBLE = "platform_incompatible"  # Code fails on non-host OS


class Severity(Enum):
    CRITICAL = "critical"    # Ship blocker
    HIGH = "high"            # Should fix before ship
    MEDIUM = "medium"        # Track for next release
    LOW = "low"              # Informational


class Verdict(Enum):
    SHIP = "ship"
    BLOCK = "block"
    REVISE = "revise"


@dataclass
class Prediction:
    """Spec Agent output: what COULD go wrong (from spec + signatures only)."""
    category: RiskCategory
    severity: Severity
    risk: str               # One-line description
    mechanism: str           # How the bug would manifest
    affected_function: str   # Function name (from signatures)


@dataclass
class Claim:
    """Code Agent output: what the code ACTUALLY does (from implementation only)."""
    category: RiskCategory
    claim: str              # One-line description
    evidence_file: str      # file:line citation
    evidence_line: int
    tests_covering: list[str] = field(default_factory=list)


@dataclass
class ToolEvidence:
    """Layer 1 tool output: deterministic boolean result."""
    tool: str               # Tool name
    target: str             # What was checked
    verdict: bool           # PASS=True, FAIL=False
    detail: str             # Human-readable detail
    lines: list[int] = field(default_factory=list)  # Relevant line numbers


@dataclass
class Divergence:
    """Arbiter output: a mismatch between predictions, claims, and evidence."""
    divergence_type: str    # "unmatched_prediction", "contradicted_claim", "confirmed_risk"
    category: RiskCategory
    prediction: Optional[Prediction] = None
    claim: Optional[Claim] = None
    tool_evidence: Optional[ToolEvidence] = None
    resolution: str = ""


@dataclass
class ArbitrationResult:
    """Final output of the two-layer verification."""
    divergences: list[Divergence]
    convergences: list[RiskCategory]   # Categories where prediction + claim + evidence align
    verdict: Verdict
    layer1_results: list[ToolEvidence]
    predictions: list[Prediction]
    claims: list[Claim]

    @property
    def ship_blockers(self) -> list[Divergence]:
        return [d for d in self.divergences
                if d.prediction and d.prediction.severity == Severity.CRITICAL]


# ── Structured Output Schemas (for agent prompts) ─────────────────────────

PREDICTION_SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "required": ["category", "severity", "risk", "mechanism", "affected_function"],
        "properties": {
            "category": {
                "type": "string",
                "enum": [c.value for c in RiskCategory],
                "description": "Risk category from the fixed taxonomy"
            },
            "severity": {
                "type": "string",
                "enum": [s.value for s in Severity]
            },
            "risk": {
                "type": "string",
                "description": "One-line description of what could go wrong"
            },
            "mechanism": {
                "type": "string",
                "description": "How the bug would manifest at runtime"
            },
            "affected_function": {
                "type": "string",
                "description": "Function name from the provided signatures"
            }
        }
    }
}

CLAIM_SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "required": ["category", "claim", "evidence_file", "evidence_line"],
        "properties": {
            "category": {
                "type": "string",
                "enum": [c.value for c in RiskCategory],
                "description": "Category of correctness this claim addresses"
            },
            "claim": {
                "type": "string",
                "description": "One-line claim about what the code does"
            },
            "evidence_file": {
                "type": "string",
                "description": "File path containing the evidence"
            },
            "evidence_line": {
                "type": "integer",
                "description": "Line number of the evidence"
            },
            "tests_covering": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Test function names that verify this claim"
            }
        }
    }
}


from .pipeline import (
    AdversarialVerifier,
    AgentBackend,
    Arbiter,
    BaseVerifier,
    ChargeSheet,
    DeterministicVerifier,
    DirectSDKBackend,
    InBandChargeSheetBackend,
    MCPSamplingBackend,
    VerificationPipeline,
    VerificationPipelineResult,
)

__all__ = [
    "CLAIM_SCHEMA",
    "PREDICTION_SCHEMA",
    "AdversarialVerifier",
    "AgentBackend",
    "ArbitrationResult",
    "Arbiter",
    "BaseVerifier",
    "ChargeSheet",
    "Claim",
    "DeterministicVerifier",
    "DirectSDKBackend",
    "Divergence",
    "InBandChargeSheetBackend",
    "MCPSamplingBackend",
    "Prediction",
    "RiskCategory",
    "Severity",
    "ToolEvidence",
    "Verdict",
    "VerificationPipeline",
    "VerificationPipelineResult",
]

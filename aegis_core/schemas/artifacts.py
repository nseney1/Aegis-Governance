"""Typed artifact contracts, cryptographic envelopes, and authorization matrix."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import hashlib
import hmac
import json
import re
from typing import Any, ClassVar, Dict, Mapping, Optional, Set, Tuple, Type

from aegis_core.errors import HandoffAuthorizationError, InvalidHandoffPayloadError

__all__ = [
    "ChargeSheet",
    "ArtifactEnvelope",
    "ArtifactRegistry",
    "MAX_CHARGE_FIELD_LEN",
    "PROMPT_INJECTION_TOKENS",
]

MAX_CHARGE_FIELD_LEN: int = 160
PROMPT_INJECTION_TOKENS = ("SYSTEM:", "---", "###", "<script", "```", "[PROMPT]")


def _sanitize_charge_field(val: str, field_name: str) -> str:
    """Cap field length to 160 chars and strip prompt injection delimiters."""
    s = str(val).strip()
    if len(s) > MAX_CHARGE_FIELD_LEN:
        s = s[:MAX_CHARGE_FIELD_LEN]
    for token in PROMPT_INJECTION_TOKENS:
        s = s.replace(token, "")
    # XML-escaped data encapsulation
    return s.strip()


@dataclass(frozen=True)
class ChargeSheet:
    """Structured architectural or invariant charge emitted by review guardrails."""

    category: str
    risk: str
    mechanism: str
    affected_function: str = ""
    line_number: Optional[int] = None
    severity: str = "medium"

    def __post_init__(self):
        if not self.category:
            raise InvalidHandoffPayloadError("ChargeSheet 'category' cannot be empty")
        if not self.risk:
            raise InvalidHandoffPayloadError("ChargeSheet 'risk' cannot be empty")
        if not self.mechanism:
            raise InvalidHandoffPayloadError("ChargeSheet 'mechanism' cannot be empty")

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ChargeSheet:
        if not isinstance(data, (dict, Mapping)):
            raise InvalidHandoffPayloadError("ChargeSheet payload must be a mapping")
        for req in ("category", "risk", "mechanism"):
            if req not in data:
                raise InvalidHandoffPayloadError(f"Missing required field '{req}' in ChargeSheet")
        return cls(
            category=str(data["category"]),
            risk=_sanitize_charge_field(str(data["risk"]), "risk"),
            mechanism=_sanitize_charge_field(str(data["mechanism"]), "mechanism"),
            affected_function=str(data.get("affected_function", "")),
            line_number=int(data["line_number"]) if data.get("line_number") is not None else None,
            severity=str(data.get("severity", "medium")),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "category": self.category,
            "risk": self.risk,
            "mechanism": self.mechanism,
            "affected_function": self.affected_function,
            "line_number": self.line_number,
            "severity": self.severity,
        }


@dataclass(frozen=True)
class InspectionReceipt:
    """Deterministic audit/inspection report."""

    inspector: str
    checked_files: Tuple[str, ...]
    violations_found: int = 0
    passed: bool = True
    details: Tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> InspectionReceipt:
        if not isinstance(data, (dict, Mapping)):
            raise InvalidHandoffPayloadError("InspectionReceipt payload must be a mapping")
        if "inspector" not in data:
            raise InvalidHandoffPayloadError("Missing required field 'inspector' in InspectionReceipt")
        files = data.get("checked_files", [])
        details = data.get("details", [])
        return cls(
            inspector=str(data["inspector"]),
            checked_files=tuple(str(f) for f in files),
            violations_found=int(data.get("violations_found", 0)),
            passed=bool(data.get("passed", True)),
            details=tuple(str(d) for d in details),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "inspector": self.inspector,
            "checked_files": list(self.checked_files),
            "violations_found": self.violations_found,
            "passed": self.passed,
            "details": list(self.details),
        }


@dataclass(frozen=True)
class DiffProposal:
    """Disjoint lane implementation change proposal."""

    summary: str
    proposed_files: Tuple[str, ...]
    risk_tier: str = "low"

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> DiffProposal:
        if not isinstance(data, (dict, Mapping)):
            raise InvalidHandoffPayloadError("DiffProposal payload must be a mapping")
        if "summary" not in data:
            raise InvalidHandoffPayloadError("Missing required field 'summary' in DiffProposal")
        files = data.get("proposed_files", [])
        return cls(
            summary=str(data["summary"]),
            proposed_files=tuple(str(f) for f in files),
            risk_tier=str(data.get("risk_tier", "low")),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "summary": self.summary,
            "proposed_files": list(self.proposed_files),
            "risk_tier": self.risk_tier,
        }


@dataclass(frozen=True)
class TestVerdict:
    """Structured test suite execution report."""

    __test__ = False

    test_suite: str
    passed: int
    failed: int
    skipped: int = 0
    duration_ms: float = 0.0

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> TestVerdict:
        if not isinstance(data, (dict, Mapping)):
            raise InvalidHandoffPayloadError("TestVerdict payload must be a mapping")
        for req in ("test_suite", "passed", "failed"):
            if req not in data:
                raise InvalidHandoffPayloadError(f"Missing required field '{req}' in TestVerdict")
        return cls(
            test_suite=str(data["test_suite"]),
            passed=int(data["passed"]),
            failed=int(data["failed"]),
            skipped=int(data.get("skipped", 0)),
            duration_ms=float(data.get("duration_ms", 0.0)),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "test_suite": self.test_suite,
            "passed": self.passed,
            "failed": self.failed,
            "skipped": self.skipped,
            "duration_ms": self.duration_ms,
        }


# ── Production Authorization Matrix ──────────────────────────────────────────

PRODUCTION_MATRIX: Dict[str, Set[str]] = {
    "ChargeSheet": {"guardrail", "sentinel"},
    "ArbitrationEvidence": {"guardrail", "sentinel"},
    "InspectionReceipt": {"guardrail", "auditor", "scout", "method", "sentinel"},
    "DiffProposal": {"method", "lane", "implementer"},
    "TestVerdict": {"guardrail", "sentinel", "tester", "method"},
}


def validate_artifact_production(artifact_type: str, producer_tier: str) -> None:
    """Validate that producer_tier is authorized to emit artifact_type."""
    tier_norm = producer_tier.strip().lower()
    allowed_tiers = PRODUCTION_MATRIX.get(artifact_type)
    if allowed_tiers is not None and tier_norm not in allowed_tiers:
        raise HandoffAuthorizationError(
            f"Producer tier '{producer_tier}' is unauthorized to emit '{artifact_type}'. "
            f"Allowed tiers: {sorted(allowed_tiers)}"
        )


# ── Schema Registry ──────────────────────────────────────────────────────────

class ArtifactRegistry:
    """Registry of typed artifact schemas for handoff validation."""

    _SCHEMAS: ClassVar[Dict[str, Any]] = {
        "ChargeSheet": ChargeSheet,
        "InspectionReceipt": InspectionReceipt,
        "DiffProposal": DiffProposal,
        "TestVerdict": TestVerdict,
    }

    @classmethod
    def register(cls, name: str, schema_cls: Any) -> None:
        cls._SCHEMAS[name] = schema_cls

    @classmethod
    def validate(cls, artifact_type: str, payload: Any) -> Dict[str, Any]:
        """Validate payload against registered contract, returning sanitized dictionary."""
        schema_cls = cls._SCHEMAS.get(artifact_type)
        if schema_cls is None:
            if isinstance(payload, dict):
                return payload
            raise InvalidHandoffPayloadError(f"Unregistered artifact type: {artifact_type}")

        if hasattr(schema_cls, "from_dict"):
            instance = schema_cls.from_dict(payload)
            return instance.to_dict()
        elif isinstance(payload, schema_cls):
            return asdict(payload)
        raise InvalidHandoffPayloadError(f"Cannot validate payload for {artifact_type}")


# ── Cryptographically Bound Envelope ─────────────────────────────────────────

@dataclass(frozen=True)
class ArtifactEnvelope:
    """Immutable cryptographically signed artifact envelope."""

    artifact_type: str
    producer_skill: str
    producer_tier: str
    tree_hash: str
    session_hmac: str
    payload: Dict[str, Any]
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    @classmethod
    def create(
        cls,
        artifact_type: str,
        producer_skill: str,
        producer_tier: str,
        tree_hash: str,
        session_secret: str,
        payload: Mapping[str, Any] | Any,
    ) -> ArtifactEnvelope:
        validate_artifact_production(artifact_type, producer_tier)
        validated_payload = ArtifactRegistry.validate(artifact_type, payload)
        
        # Calculate session HMAC over payload + tree_hash
        payload_bytes = json.dumps(validated_payload, sort_keys=True).encode("utf-8")
        mac = hmac.new(session_secret.encode("utf-8"), tree_hash.encode("utf-8") + b":" + payload_bytes, hashlib.sha256).hexdigest()
        
        return cls(
            artifact_type=artifact_type,
            producer_skill=producer_skill,
            producer_tier=producer_tier,
            tree_hash=tree_hash,
            session_hmac=mac,
            payload=validated_payload,
        )

    def verify_integrity(self, session_secret: str, expected_tree_hash: Optional[str] = None) -> bool:
        """Verify HMAC signature and tree_hash binding."""
        if expected_tree_hash and self.tree_hash != expected_tree_hash:
            return False
        payload_bytes = json.dumps(self.payload, sort_keys=True).encode("utf-8")
        expected_mac = hmac.new(
            session_secret.encode("utf-8"),
            self.tree_hash.encode("utf-8") + b":" + payload_bytes,
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(self.session_hmac, expected_mac)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "artifact_type": self.artifact_type,
            "producer_skill": self.producer_skill,
            "producer_tier": self.producer_tier,
            "tree_hash": self.tree_hash,
            "session_hmac": self.session_hmac,
            "payload": self.payload,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> ArtifactEnvelope:
        return cls(
            artifact_type=str(d["artifact_type"]),
            producer_skill=str(d["producer_skill"]),
            producer_tier=str(d["producer_tier"]),
            tree_hash=str(d["tree_hash"]),
            session_hmac=str(d["session_hmac"]),
            payload=dict(d["payload"]),
            timestamp=str(d.get("timestamp", "")),
        )

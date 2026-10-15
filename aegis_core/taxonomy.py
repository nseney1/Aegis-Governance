"""Canonical domain taxonomy, review hierarchy, rule types, and tuning constants."""
from __future__ import annotations


# ── 1. Review Modes & Escalation Hierarchy ──────────────────────────────────
class ReviewMode:
    PATROL = "patrol"
    SWEEP = "sweep"
    VANGUARD = "vanguard"
    BULWARK = "bulwark"
    FORTRESS = "fortress"
    CITADEL = "citadel"


REVIEW_MODE_RANKS: dict[str, int] = {
    ReviewMode.PATROL: 1,
    ReviewMode.SWEEP: 2,
    ReviewMode.VANGUARD: 3,
    ReviewMode.BULWARK: 4,
    ReviewMode.FORTRESS: 5,
    ReviewMode.CITADEL: 6,
}

REVIEW_MODES: tuple[str, ...] = tuple(REVIEW_MODE_RANKS.keys())

ESCALATION_PROTOCOLS: tuple[str, ...] = REVIEW_MODES
ESCALATING_PROTOCOLS: tuple[str, ...] = (
    ReviewMode.VANGUARD,
    ReviewMode.BULWARK,
    ReviewMode.FORTRESS,
    ReviewMode.CITADEL,
)

# Backward-compatible input normalization for legacy frontmatter or external callers
LEGACY_REVIEW_MODE_ALIASES: dict[str, str] = {
    "breeze": ReviewMode.PATROL,
    "gale": ReviewMode.SWEEP,
    "trident": ReviewMode.VANGUARD,
    "maelstrom": ReviewMode.BULWARK,
    "tempest": ReviewMode.FORTRESS,
    "supercell": ReviewMode.CITADEL,
}


def normalize_review_mode(mode: str | None, default: str = ReviewMode.PATROL) -> str:
    """Normalize a review mode string (case-insensitive, mapping legacy aliases)."""
    if not mode:
        return default
    cleaned = mode.strip().lower()
    if cleaned in REVIEW_MODE_RANKS:
        return cleaned
    return LEGACY_REVIEW_MODE_ALIASES.get(cleaned, cleaned)


# ── 2. Review Prongs & Genesis Reconnaissance Stages ────────────────────────
class ReviewProng:
    SENTRY = "Sentry"
    TRACE = "Trace"
    PROBE = "Probe"
    GAUNTLET = "Gauntlet"
    BASTION = "Bastion"
    DEBRIEF = "Debrief"


REVIEW_PRONGS: tuple[str, ...] = (
    ReviewProng.SENTRY,
    ReviewProng.TRACE,
    ReviewProng.PROBE,
    ReviewProng.GAUNTLET,
    ReviewProng.BASTION,
    ReviewProng.DEBRIEF,
)

LEGACY_REVIEW_PRONG_ALIASES: dict[str, str] = {
    "spores": ReviewProng.SENTRY,
    "mycelium": ReviewProng.TRACE,
    "roots": ReviewProng.PROBE,
    "thorns": ReviewProng.GAUNTLET,
    "bedrock": ReviewProng.BASTION,
    "mulch": ReviewProng.DEBRIEF,
}


class GenesisStage:
    PERIMETER = "Perimeter"
    CHRONOLOGY = "Chronology"
    BLUEPRINT = "Blueprint"
    POLICY = "Policy"


GENESIS_STAGES: tuple[str, ...] = (
    GenesisStage.PERIMETER,
    GenesisStage.CHRONOLOGY,
    GenesisStage.BLUEPRINT,
    GenesisStage.POLICY,
)


# ── 3. Rule Types, Directory Mappings & Display Styles ──────────────────────
class RuleType:
    INVARIANT = "invariant"
    TRAP = "trap"
    GATE = "gate"
    BOUNDARY = "boundary"
    PERSONA = "persona"
    CONTRACT = "contract"


CANONICAL_RULE_TYPES: tuple[str, ...] = (
    RuleType.INVARIANT,
    RuleType.TRAP,
    RuleType.GATE,
    RuleType.BOUNDARY,
    RuleType.PERSONA,
    RuleType.CONTRACT,
)

RULE_TYPE_DIRS: dict[str, str] = {
    RuleType.TRAP: "traps",
    RuleType.INVARIANT: "invariants",
    RuleType.GATE: "gates",
    RuleType.BOUNDARY: "boundaries",
    RuleType.PERSONA: "personas",
    RuleType.CONTRACT: "contracts",
    # Legacy read-compat aliases mapped to canonical directories
    "wall": "invariants",
    "membrane": "boundaries",
}

DIR_TO_PRIMARY_RULE_TYPE: dict[str, str] = {
    "traps": RuleType.TRAP,
    "invariants": RuleType.INVARIANT,
    "gates": RuleType.GATE,
    "boundaries": RuleType.BOUNDARY,
    "personas": RuleType.PERSONA,
    "contracts": RuleType.CONTRACT,
    "walls": RuleType.INVARIANT,
    "membranes": RuleType.BOUNDARY,
}

DIR_TO_ALLOWED_RULE_TYPES: dict[str, tuple[str, ...]] = {
    "traps": (RuleType.TRAP,),
    "invariants": (RuleType.INVARIANT, "wall"),
    "gates": (RuleType.GATE,),
    "boundaries": (RuleType.BOUNDARY, "membrane"),
    "personas": (RuleType.PERSONA,),
    "contracts": (RuleType.CONTRACT,),
    "walls": ("wall", RuleType.INVARIANT),
    "membranes": ("membrane", RuleType.BOUNDARY),
}

RULE_TYPE_NORMALIZATION: dict[str, str] = {
    "wall": RuleType.INVARIANT,
    "walls": RuleType.INVARIANT,
    "invariants": RuleType.INVARIANT,
    "membrane": RuleType.BOUNDARY,
    "membranes": RuleType.BOUNDARY,
    "boundaries": RuleType.BOUNDARY,
    "traps": RuleType.TRAP,
    "patterns": RuleType.TRAP,
    "cells": RuleType.TRAP,
    "rules": RuleType.TRAP,
    "personas": RuleType.PERSONA,
    "contracts": RuleType.CONTRACT,
    "gates": RuleType.GATE,
    "core_rule": "core",
    "genome": "core",
    "safety-guard": RuleType.INVARIANT,
    "learned-trap": RuleType.TRAP,
    "agent-persona": RuleType.PERSONA,
    "escalation-boundary": RuleType.BOUNDARY,
    "contract-bridge": RuleType.CONTRACT,
}

MCP_SUPPORTED_RULE_TYPE_ENUM: tuple[str, ...] = (
    *CANONICAL_RULE_TYPES,
    "wall",
    "membrane",
    "safety-guard",
    "learned-trap",
    "agent-persona",
    "escalation-boundary",
    "contract-bridge",
)

RULE_TYPE_DISPLAY_ORDER: dict[str, int] = {
    "core": 0,
    RuleType.INVARIANT: 1,
    RuleType.BOUNDARY: 2,
    RuleType.CONTRACT: 3,
    RuleType.PERSONA: 4,
    RuleType.TRAP: 5,
    RuleType.GATE: 6,
}

RULE_TYPE_THEME_STYLES: dict[str, tuple[str, ...]] = {
    RuleType.INVARIANT: ("bold", "magenta"),
    "wall": ("bold", "magenta"),
    RuleType.BOUNDARY: ("blue",),
    "membrane": ("blue",),
    RuleType.CONTRACT: ("blue",),
    RuleType.TRAP: ("cyan",),
    RuleType.PERSONA: ("cyan",),
    RuleType.GATE: ("bold", "red"),
    "core_rule": ("bold", "green"),
    "core": ("bold", "green"),
}

SENTINEL_BOUNDARY_SUBDIRS: tuple[str, ...] = (
    "boundaries",
    "invariants",
    "membranes",
    "walls",
)


# ── 4. Timeouts, TTLs, Retries & Rate Limits ────────────────────────────────
DEFAULT_RECEIPT_TTL_SECONDS: float = 3600.0
INTERACTIVE_SESSION_TTL_SECONDS: float = 300.0
RULE_EXPIRY_DAYS: int = 90

# One lock guards rules and the ledger (AD-3), so its wait covers the slowest holder.
LOCK_TIMEOUT_SECONDS: float = 10.0
LOCK_RETRY_INTERVAL_SECONDS: float = 0.01
LOCK_MAX_BACKOFF_SECONDS: float = 0.05

STORAGE_MAX_RETRIES: int = 8
STORAGE_INITIAL_DELAY_SECONDS: float = 0.01

AST_RUNNER_TIMEOUT_SECONDS: float = 3.0
SUBPROCESS_DEFAULT_TIMEOUT_SECONDS: float = 10.0
VERIFY_RUNNER_TIMEOUT_SECONDS: float = 30.0

MCP_DEFAULT_RATE_LIMITS: dict[str, tuple[int, int]] = {
    "READ": (60, 60),
    "MUTATION": (5, 60),
    "EXECUTION": (20, 60),
    "VERIFICATION": (5, 60),
    "CHECKPOINT": (3, 60),
}


# ── 5. Statistical Scoring & JIT Context Budgets ────────────────────────────
WILSON_CONFIDENCE_Z_SCORES: dict[float, float] = {
    0.90: 1.645,
    0.95: 1.960,
    0.99: 2.576,
}
DEFAULT_CONFIDENCE_LEVEL: float = 0.90
INSIGHT_LAPLACE_PRIOR: int = 2

SALIENT_EXPLORATION_PRIOR: float = 0.20
SALIENT_DECAY_FLOOR: float = 0.20
SALIENT_GATE_WEIGHT: float = 5.0
SALIENT_INVARIANT_WEIGHT: float = 2.0
SALIENT_TRAP_WEIGHT: float = 1.0
SALIENT_GATE_UNTESTED: float = 1.0

JIT_DEFAULT_MAX_TOKENS: int = 2000
JIT_GATE_TIER_RATIO: float = 0.60
JIT_DEFAULT_RULE_COUNT_BUDGET: int = 3
WORDS_TO_TOKENS_FACTOR: float = 1.35
CHARS_PER_TOKEN_ESTIMATE: int = 4

__all__ = [
    "ReviewMode",
    "REVIEW_MODE_RANKS",
    "REVIEW_MODES",
    "ESCALATION_PROTOCOLS",
    "ESCALATING_PROTOCOLS",
    "LEGACY_REVIEW_MODE_ALIASES",
    "normalize_review_mode",
    "ReviewProng",
    "REVIEW_PRONGS",
    "LEGACY_REVIEW_PRONG_ALIASES",
    "GenesisStage",
    "GENESIS_STAGES",
    "RuleType",
    "CANONICAL_RULE_TYPES",
    "RULE_TYPE_DIRS",
    "DIR_TO_PRIMARY_RULE_TYPE",
    "DIR_TO_ALLOWED_RULE_TYPES",
    "RULE_TYPE_NORMALIZATION",
    "MCP_SUPPORTED_RULE_TYPE_ENUM",
    "RULE_TYPE_DISPLAY_ORDER",
    "RULE_TYPE_THEME_STYLES",
    "SENTINEL_BOUNDARY_SUBDIRS",
    "DEFAULT_RECEIPT_TTL_SECONDS",
    "INTERACTIVE_SESSION_TTL_SECONDS",
    "RULE_EXPIRY_DAYS",
    "LOCK_TIMEOUT_SECONDS",
    "LOCK_RETRY_INTERVAL_SECONDS",
    "LOCK_MAX_BACKOFF_SECONDS",
    "STORAGE_MAX_RETRIES",
    "STORAGE_INITIAL_DELAY_SECONDS",
    "AST_RUNNER_TIMEOUT_SECONDS",
    "SUBPROCESS_DEFAULT_TIMEOUT_SECONDS",
    "VERIFY_RUNNER_TIMEOUT_SECONDS",
    "MCP_DEFAULT_RATE_LIMITS",
    "WILSON_CONFIDENCE_Z_SCORES",
    "DEFAULT_CONFIDENCE_LEVEL",
    "INSIGHT_LAPLACE_PRIOR",
    "SALIENT_EXPLORATION_PRIOR",
    "SALIENT_DECAY_FLOOR",
    "SALIENT_GATE_WEIGHT",
    "SALIENT_INVARIANT_WEIGHT",
    "SALIENT_TRAP_WEIGHT",
    "SALIENT_GATE_UNTESTED",
    "JIT_DEFAULT_MAX_TOKENS",
    "JIT_GATE_TIER_RATIO",
    "JIT_DEFAULT_RULE_COUNT_BUDGET",
    "WORDS_TO_TOKENS_FACTOR",
    "CHARS_PER_TOKEN_ESTIMATE",
]


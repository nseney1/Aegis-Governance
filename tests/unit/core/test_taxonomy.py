"""Unit tests for aegis_core.taxonomy canonical domain constants and review hierarchy."""
from __future__ import annotations

from aegis_core.taxonomy import (
    CANONICAL_RULE_TYPES,
    DIR_TO_ALLOWED_RULE_TYPES,
    DIR_TO_PRIMARY_RULE_TYPE,
    ESCALATING_PROTOCOLS,
    ESCALATION_PROTOCOLS,
    GENESIS_STAGES,
    GenesisStage,
    LEGACY_REVIEW_MODE_ALIASES,
    LEGACY_REVIEW_PRONG_ALIASES,
    MCP_DEFAULT_RATE_LIMITS,
    MCP_SUPPORTED_RULE_TYPE_ENUM,
    REVIEW_MODES,
    REVIEW_MODE_RANKS,
    REVIEW_PRONGS,
    RULE_EXPIRY_DAYS,
    RULE_TYPE_DIRS,
    RULE_TYPE_DISPLAY_ORDER,
    RULE_TYPE_NORMALIZATION,
    RULE_TYPE_THEME_STYLES,
    ReviewMode,
    ReviewProng,
    RuleType,
    SENTINEL_BOUNDARY_SUBDIRS,
    WILSON_CONFIDENCE_Z_SCORES,
    normalize_review_mode,
)


def test_review_mode_hierarchy_and_ranks():
    assert REVIEW_MODES == ("patrol", "sweep", "vanguard", "bulwark", "fortress", "citadel")
    assert ESCALATION_PROTOCOLS == REVIEW_MODES
    assert ESCALATING_PROTOCOLS == ("vanguard", "bulwark", "fortress", "citadel")
    assert REVIEW_MODE_RANKS[ReviewMode.PATROL] < REVIEW_MODE_RANKS[ReviewMode.SWEEP]
    assert REVIEW_MODE_RANKS[ReviewMode.SWEEP] < REVIEW_MODE_RANKS[ReviewMode.VANGUARD]
    assert REVIEW_MODE_RANKS[ReviewMode.VANGUARD] < REVIEW_MODE_RANKS[ReviewMode.BULWARK]
    assert REVIEW_MODE_RANKS[ReviewMode.BULWARK] < REVIEW_MODE_RANKS[ReviewMode.FORTRESS]
    assert REVIEW_MODE_RANKS[ReviewMode.FORTRESS] < REVIEW_MODE_RANKS[ReviewMode.CITADEL]


def test_normalize_review_mode_canonical_and_legacy():
    assert normalize_review_mode(None) == ReviewMode.PATROL
    assert normalize_review_mode("") == ReviewMode.PATROL
    assert normalize_review_mode("  FORTRESS ") == ReviewMode.FORTRESS
    for legacy, canonical in LEGACY_REVIEW_MODE_ALIASES.items():
        assert normalize_review_mode(legacy) == canonical
        assert normalize_review_mode(legacy.upper()) == canonical


def test_review_prongs_and_genesis_stages():
    assert REVIEW_PRONGS == ("Sentry", "Trace", "Probe", "Gauntlet", "Bastion", "Debrief")
    assert LEGACY_REVIEW_PRONG_ALIASES["spores"] == ReviewProng.SENTRY
    assert LEGACY_REVIEW_PRONG_ALIASES["mulch"] == ReviewProng.DEBRIEF
    assert GENESIS_STAGES == (
        GenesisStage.PERIMETER,
        GenesisStage.CHRONOLOGY,
        GenesisStage.BLUEPRINT,
        GenesisStage.POLICY,
    )


def test_rule_types_and_directory_mappings():
    assert CANONICAL_RULE_TYPES == ("invariant", "trap", "gate", "boundary", "persona", "contract")
    for rt in CANONICAL_RULE_TYPES:
        subdir = RULE_TYPE_DIRS[rt]
        assert DIR_TO_PRIMARY_RULE_TYPE[subdir] == rt
        assert rt in DIR_TO_ALLOWED_RULE_TYPES[subdir]
        assert rt in MCP_SUPPORTED_RULE_TYPE_ENUM
        assert rt in RULE_TYPE_DISPLAY_ORDER
        assert rt in RULE_TYPE_THEME_STYLES

    assert RULE_TYPE_NORMALIZATION["wall"] == RuleType.INVARIANT
    assert RULE_TYPE_NORMALIZATION["membrane"] == RuleType.BOUNDARY
    assert "boundaries" in SENTINEL_BOUNDARY_SUBDIRS
    assert "invariants" in SENTINEL_BOUNDARY_SUBDIRS


def test_statistical_and_operational_constants():
    assert RULE_EXPIRY_DAYS == 90
    assert 0.90 in WILSON_CONFIDENCE_Z_SCORES
    assert 0.95 in WILSON_CONFIDENCE_Z_SCORES
    assert 0.99 in WILSON_CONFIDENCE_Z_SCORES
    assert set(MCP_DEFAULT_RATE_LIMITS.keys()) == {
        "READ",
        "MUTATION",
        "EXECUTION",
        "VERIFICATION",
        "CHECKPOINT",
    }

"""Constants and mappings for rule lifecycle, tiers, and promotion transitions."""
from __future__ import annotations

from aegis_core.taxonomy import (
    DIR_TO_PRIMARY_RULE_TYPE,
    RULE_EXPIRY_DAYS,
    RULE_TYPE_DIRS,
)

VALID_TYPES = dict(RULE_TYPE_DIRS)

TYPE_TO_DIR = dict(RULE_TYPE_DIRS)

DIR_TO_TYPE = dict(DIR_TO_PRIMARY_RULE_TYPE)

CELL_TELOMERE_DAYS = RULE_EXPIRY_DAYS

STATUS_NEW = "NEW"
STATUS_SURVIVE = "SURVIVE"
STATUS_ADAPT = "ADAPT"
STATUS_EXTINCT = "EXTINCT"
STATUS_RETIRED = "RETIRED"
STATUS_APOPTOSIS = STATUS_RETIRED
STATUS_APOPTOSIS_WARNING = "APOPTOSIS_WARNING"
STATUS_RETIRED_WARNING = STATUS_APOPTOSIS_WARNING
STATUS_DORMANT = "DORMANT"

# The protected shipped rules that must never be demoted
PROTECTED_RULES = frozenset({
    "providence",
    "cost-optimization",
    "subagent-delegation",
    "architectural-tenets",
    "polyglot-standards",
    "feature-specs",
    "testing",
    "documentation",
    "destructive-ops",
    "git-workflow",
})

GLOBAL_PROMOTION_PATH = {"trap": "invariant", "invariant": "genome", "wall": "genome"}
LOCAL_PROMOTION_PATH = {"trap": "invariant", "invariant": "gate", "wall": "gate"}
PROMOTION_PATH = GLOBAL_PROMOTION_PATH

GLOBAL_DEMOTION_PATH = {"genome": "invariant", "invariant": "trap", "wall": "trap"}
LOCAL_DEMOTION_PATH = {"gate": "invariant", "invariant": "trap", "wall": "trap"}
DEMOTION_PATH = GLOBAL_DEMOTION_PATH

MODERN_GLOBAL_PROMOTION_PATH = {"trap": "invariant", "invariant": "genome"}
MODERN_LOCAL_PROMOTION_PATH = {"trap": "invariant", "invariant": "gate"}
MODERN_DEMOTION_PATH = {"invariant": "trap"}

EXTINCTION_THRESHOLD = 0.15
PROMOTION_THRESHOLD = 0.85
MIN_PROMOTION_TRIGGERS = 20
DEFAULT_DECAY_FACTOR = 0.95

MIN_TRIGGERS_FOR_PROMOTION = MIN_PROMOTION_TRIGGERS
MIN_TP_RATE_FOR_PROMOTION = PROMOTION_THRESHOLD
MIN_AGE_DAYS_FOR_PROMOTION = 30
MAX_FP_RATE_FOR_DEMOTION = 0.5
DORMANT_DAYS_THRESHOLD = 90


def get_promotion_path(ws: object) -> dict[str, str]:
    """Return promotion path based on whether workspace is an Aegis repository."""
    is_aegis = getattr(ws, "is_aegis_repo", False)
    return GLOBAL_PROMOTION_PATH if is_aegis else LOCAL_PROMOTION_PATH


def get_demotion_path(ws: object) -> dict[str, str]:
    """Return demotion path based on whether workspace is an Aegis repository."""
    is_aegis = getattr(ws, "is_aegis_repo", False)
    return GLOBAL_DEMOTION_PATH if is_aegis else LOCAL_DEMOTION_PATH


VALID_ENFORCEMENT = ("advisory", "mechanical", "gate")

VALID_PROMOTION_TARGETS = ("invariant", "boundary", "rule", "gate")
VALID_METAMORPHOSIS_TARGETS = VALID_PROMOTION_TARGETS

PROMOTION_TRANSITIONS = {
    "trap": [
        {"target": "invariant", "min_fitness": 0.8, "min_sessions": 20},
        {"target": "boundary", "min_fitness": 0.7, "min_sessions": 15},
    ],
    "persona": [
        {"target": "rule", "min_fitness": 0.9, "min_sessions": 30},
    ],
    "wall": [
        {"target": "rule", "min_fitness": 0.85, "min_sessions": 25},
    ],
    "invariant": [
        {"target": "rule", "min_fitness": 0.85, "min_sessions": 25},
    ],
}
METAMORPHOSIS_PATHS = PROMOTION_TRANSITIONS

DECAY_FACTOR = 0.95  # Multiply counts by this each application; ~20-session memory window


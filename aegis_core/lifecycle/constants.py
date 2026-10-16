"""Lifecycle constants: the promotion ladder, protected rules and the evidence thresholds.

Every threshold is read against aegis_core.fitness: ``fitness`` is the decayed Wilson
lower bound (90%) of a rule's true-positive rate in the ledger, ``misfire`` the bound of
its false-positive rate, and verdicts its tp + fp rows.
"""
from __future__ import annotations

from aegis_core.taxonomy import RULE_TYPES

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

# The ladder trap -> invariant -> gate, read from the one rule-type table.
PROMOTION_PATH = {name: spec.promotes_to for name, spec in RULE_TYPES.items() if spec.promotes_to}
DEMOTION_PATH = {name: spec.demotes_to for name, spec in RULE_TYPES.items() if spec.demotes_to}

# Promote: enough verdicts, a high bound, and old enough to have been tried.
MIN_PROMOTION_VERDICTS = 20
PROMOTION_THRESHOLD = 0.85
MIN_AGE_DAYS_FOR_PROMOTION = 30
# Demote or archive: confident the rule fires wrongly more often than not.
# Three straight false positives already clear it (bound 0.53); 4 of 5 do not (0.43).
MISFIRE_THRESHOLD = 0.5

# Enforcement tier transitions: (min verdicts, min fitness) to move up a tier, and the
# misfire bound above which a tier steps down.
TIER_UP = {"advisory": (20, 0.85), "mechanical": (50, 0.90)}
TIER_DOWN_MISFIRE = {"mechanical": 0.5, "gate": 0.3}

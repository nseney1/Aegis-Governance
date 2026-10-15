---
id: trap-schema-test-gap
domain: correctness
type: trap
enforcement: advisory
promotion_threshold: 0.85
demotion_threshold: 0.3
hypothesis: New rule types or core rule categories committed without corresponding parametrized schema test coverage regress toward incomplete frontmatter
prediction: Will flag when a new rule subdirectory or rule type exists but has no row in the WORKSPACE schema table of test_rule_lint.py
falsification: 0 findings in 10 sessions → prune
target_paths:
  - ".aegis/rules/**/*.md"
  - "rules/*.md"
  - tests/unit/core/test_rule_lint.py
triggers:
  - rule_creation
  - rule_type_addition
  - core_rule_creation
expiry_sessions: 10
expiry_days: 30
created: 2026-09-30
impact_weight: 0.9
tags:
  - testing
  - schema
  - meta-governance
fitness:
  score: 0.5
  impact_weight: 0.9
  triggers: 77
  true_positives: 43.25
  false_positives: 30.25
  last_trigger_date: "2026-10-14T22:29:45Z"
---

Every rule subdirectory under `.aegis/rules/` (traps, invariants, boundaries,
personas, contracts) must have a row in the `WORKSPACE` schema table of the
table-driven lint, `tests/unit/core/test_rule_lint.py` (defense #41). The lint
fails any workspace rule outside a listed type dir, so a new rule type needs its
row (type and required fields) before its first rule lands.

Evidence: Session 2026-09-30 added content coherence tests that immediately
caught 23 schema gaps in existing rules — missing `enforcement`,
`fitness`, `hypothesis`, `target_paths`, and `expiry` fields across 18 files.
The gaps existed because schema tests didn't cover those properties until now.

The fix is test coverage + CI gate, not TDD process mandate.

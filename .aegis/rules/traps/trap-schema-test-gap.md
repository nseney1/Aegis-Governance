---
id: trap-schema-test-gap
domain: correctness
type: trap
enforcement: advisory
promotion_threshold: 0.85
demotion_threshold: 0.3
hypothesis: New cell types or genome categories committed without corresponding parametrized schema test coverage regress toward incomplete frontmatter
prediction: Will flag when a new cell subdirectory exists but has no dedicated test coverage in test_rule_metadata.py
falsification: 0 findings in 10 sessions → prune
target_paths:
  - ".aegis/rules/**/*.md"
  - "rules/*.md"
  - tests/unit/core/test_rule_metadata.py
triggers:
  - cell_creation
  - cell_type_addition
  - genome_rule_creation
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
  triggers: 68
  true_positives: 34.25
  false_positives: 30.25
  last_trigger_date: "2026-10-14T19:26:54Z"
---

Every cell subdirectory under `.aegis/rules/` (vacuoles, walls, membranes,
chloroplasts, plasmodesmata) must have corresponding parametrized content
coherence tests in `tests/test_rule_metadata.py`.

Evidence: Session 2026-09-30 added content coherence tests that immediately
caught 23 schema gaps in existing cells/genomes — missing `enforcement`,
`fitness`, `hypothesis`, `target_paths`, and `expiry` fields across 18 files.
The gaps existed because schema tests didn't cover those properties until now.

The fix is test coverage + CI gate, not TDD process mandate.

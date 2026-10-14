---
id: trap-doc-feature-drift
domain: documentation
type: trap
enforcement: gate
hypothesis: "Adding or modifying a feature without updating ALL documentation surfaces (README, CHANGELOG, SKILL.md) in the same commit causes doc-feature desync"
prediction: "Will fire when a commit touches code files but not documentation, or updates one doc surface but not others"
falsification: 0 findings in 20 sessions → prune
target_paths:
  - README.md
  - "docs/**/*.md"
  - "docs/**/*.json"
  - "skills/*/SKILL.md"
  - "aegis_cli/*.py"
  - "aegis_mcp/*.py"
triggers:
  - feature_addition
  - feature_modification
  - commit_review
minimum_mode: standard
expiry_sessions: 30
expiry_days: 90
created: 2026-09-30
impact_weight: 1.0
tags:
  - documentation
  - drift
  - process
fitness:
  score: 0.6364
  impact_weight: 1.0
  triggers: 83
  true_positives: 33.9506
  false_positives: 24.0407
  last_trigger_date: "2026-10-14T19:45:33Z"
---

Supercell doc-drift incident: Supercell intensity added to README and SKILL.md but
CHANGELOG v0.60.0 was not updated. Architecture ASCII box was edited but not
width-verified. Detection: when a commit adds a feature term to any doc, grep all
other doc surfaces for the same term.

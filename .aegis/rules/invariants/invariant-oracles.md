---
id: invariant-oracles
domain: governance
type: invariant
enforcement: gate
hypothesis: Oracles contain sensitive core rule configuration.
prediction: Shielding the oracles directory prevents corruption of core identity logic.
falsification: Oracles are public and ephemeral.
target_paths:
  - "rules/.oracles/**"
expiry_sessions: 100
impact_weight: 1.0
minimum_mode: vanguard
tags:
  - oracles
  - rules
  - security
created: 2026-09-28
fitness:
  triggers: 12
  true_positives: 4.6
  false_positives: 5
  score: 1.0
  last_trigger_date: "2026-10-14T22:29:45Z"
---

# Invariant: Oracles

Target: `rules/.oracles/`

Description: Security boundary protecting the core rule oracles from unauthorized modification.

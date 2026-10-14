---
id: invariant-oracles
domain: governance
type: invariant
enforcement: gate
hypothesis: Oracles contain sensitive genome configuration.
prediction: Shielding the oracles directory prevents corruption of core identity logic.
falsification: Oracles are public and ephemeral.
target_paths:
  - "rules/.oracles/**"
expiry_sessions: 100
impact_weight: 1.0
minimum_mode: trident
tags:
  - oracles
  - genome
  - security
created: 2026-09-28
fitness:
  triggers: 8
  true_positives: 3
  false_positives: 5
  score: 1.0
  last_trigger_date: "2026-10-14T07:33:06Z"
---

# Wall: Oracles

Target: `rules/.oracles/`

Description: Security boundary protecting the genome oracles from unauthorized modification.

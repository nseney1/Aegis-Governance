---
id: trap-threshold-spec-drift
domain: correctness
type: wall
enforcement: gate
hypothesis: "When numeric thresholds are documented in docstrings with > but implemented with >= (or vice versa), boundary behavior silently diverges from the specification"
prediction: "Will catch threshold comparisons where the operator doesn't match the documented behavior"
falsification: 0 findings in 20 sessions → prune
target_paths:
  - "soma_core/**/*.py"
  - "soma_cli/*.py"
triggers:
  - threshold_modification
  - docstring_update
  - correctness_review
minimum_mode: standard
expiry_sessions: 30
expiry_days: 90
created: 2026-09-30
impact_weight: 1.0
tags:
  - correctness
  - specification
  - boundary
fitness:
  score: 0.75
  impact_weight: 1.0
  triggers: 55
  true_positives: 15.0948
  false_positives: 11.8193
  last_trigger_date: "2026-10-14T06:50:24Z"
---

Supercell C3 incident: `lifecycle.py` docstring said `tp_rate > 0.85` and
`age > 30 days` but code used `<` operator which permits equality (>= semantics).
Also: demotion had no minimum sample size (1 trigger with 1 FP = immediate
demotion) and dormancy check was unreachable.

---
id: trap-magic-numbers
domain: style
type: trap
enforcement: advisory
hypothesis: Hardcoded numeric literals represent brittle magic numbers that reduce code adaptability.
prediction: Extracting these numbers into configuration or constants will increase the fitness of the codebase.
falsification: The numbers are mathematically fundamental constants that never change.
target_paths:
  - "**/*.py"
expiry_sessions: 50
impact_weight: 0.8
minimum_mode: patrol
tags:
  - magic-numbers
  - style
  - configuration
created: 2026-09-28
fitness:
  triggers: 83
  true_positives: 35.3628
  false_positives: 29.9993
  score: 0.25
  last_trigger_date: "2026-10-14T22:29:45Z"
---

# Trap: Magic Numbers

Target: `aegis_core/fitness.py`, `aegis_core/telemetry.py`, `aegis_cli/promote.py`

Description: There are many hardcoded numeric literals (priors, z-scores, weights) in these files. They should be extracted into configuration files or constants.

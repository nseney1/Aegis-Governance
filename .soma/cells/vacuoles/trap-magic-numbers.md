---
id: trap-magic-numbers
domain: style
type: vacuole
enforcement: advisory
hypothesis: Hardcoded numeric literals represent brittle magic numbers that reduce code adaptability.
prediction: Extracting these numbers into configuration or constants will increase the fitness of the codebase.
falsification: The numbers are mathematically fundamental constants that never change.
target_paths:
  - "**/*.py"
expiry_sessions: 50
impact_weight: 0.8
minimum_mode: breeze
tags:
  - magic-numbers
  - style
  - configuration
created: 2026-09-28
fitness:
  triggers: 49
  true_positives: 15.733
  false_positives: 20.4203
  score: 0.25
  last_trigger_date: "2026-10-14T04:36:35Z"
---

# Trap: Magic Numbers

Target: `enzymes/cell_fitness.py`, `enzymes/outcome_engine.py`, `enzymes/cell_promote.py`

Description: There are many hardcoded numeric literals (priors, z-scores, weights) in these files. They should be extracted into configuration files or constants.

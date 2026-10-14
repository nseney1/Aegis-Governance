---
id: trap-pytest-exit-code
domain: correctness
type: trap
enforcement: advisory
hypothesis: "Pytest exit code 5 (no tests collected) is currently penalizing valid scenarios where tests shouldn't run."
prediction: Handling exit code 5 gracefully will improve outcome engine reliability.
falsification: A lack of collected tests is always a critical failure.
target_paths:
  - "tests/*.py"
  - "aegis_core/*.py"
expiry_sessions: 30
impact_weight: 0.7
minimum_mode: breeze
tags:
  - pytest
  - exit-code
  - testing
created: 2026-09-28
fitness:
  triggers: 70
  true_positives: 24.0518
  false_positives: 25.2037
  score: 0.6667
  last_trigger_date: "2026-10-14T08:55:31Z"
---

# Trap: Pytest Exit Code 5

Target: `enzymes/outcome_engine.py`

Description: Pytest exit code 5 penalizes uncollected tests. We need to handle this appropriately so it doesn't cause false negatives in outcome evaluation.

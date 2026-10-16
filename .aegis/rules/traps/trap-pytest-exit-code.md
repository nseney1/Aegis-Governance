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
minimum_mode: patrol
tags:
  - pytest
  - exit-code
  - testing
created: 2026-09-28
---

# Trap: Pytest Exit Code 5

Target: `aegis_core/telemetry.py`

Description: Pytest exit code 5 penalizes uncollected tests. We need to handle this appropriately so it doesn't cause false negatives in outcome evaluation.

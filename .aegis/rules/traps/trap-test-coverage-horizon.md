---
id: trap-test-coverage-horizon
domain: testing
type: trap
enforcement: advisory
hypothesis: "When consistency tests are added for one pair of documentation surfaces, the same consistency should be tested across ALL surfaces, not just the first two"
prediction: Will fire when a test file checks consistency between 2 sources but a 3rd related source exists untested
falsification: 0 findings in 20 sessions → prune
target_paths:
  - "tests/**/test_*.py"
triggers:
  - test_creation
  - documentation_edit
  - consistency_review
minimum_mode: standard
expiry_sessions: 30
expiry_days: 90
created: 2026-09-30
impact_weight: 1.0
tags:
  - testing
  - coverage
  - flashlight-effect
fitness:
  score: 0.3333
  impact_weight: 1.0
  triggers: 61
  true_positives: 16.533
  false_positives: 19.434
  last_trigger_date: "2026-10-14T08:55:31Z"
---

Supercell doc-drift incident: `test_review_intensity.py` verified README ↔ SKILL.md
consistency for intensity levels but did not check CHANGELOG or SCRIPTS.md. The test
caught exactly what it tested for and nothing more — the "flashlight effect".

---
id: trap-orphaned-module
domain: correctness
type: trap
enforcement: advisory
hypothesis: A module with passing unit tests but zero callers in production code indicates an integration gap where functionality was built but never wired
prediction: "Will catch modules that have test_*.py coverage but no imports from aegis_cli/, aegis_mcp/, or aegis_sdk/"
falsification: 0 findings in 20 sessions → prune
target_paths:
  - "aegis_core/**/*.py"
  - "aegis_cli/*.py"
  - "aegis_mcp/*.py"
triggers:
  - module_creation
  - test_creation
  - integration_review
minimum_mode: patrol
expiry_sessions: 30
expiry_days: 90
created: 2026-09-30
impact_weight: 1.0
tags:
  - integration
  - dead-module
  - coverage-gap
fitness:
  score: 0.3333
  impact_weight: 1.0
  triggers: 78
  true_positives: 22.4353
  false_positives: 17.423
  last_trigger_date: "2026-10-14T22:29:45Z"
---

Citadel C4 incident: `quality_gate.py` had 30 passing unit tests and proper
AST-based assertion density checking, but `checkpoint.py` reimplemented the same
logic with brittle substring matching because quality_gate was never wired into the
checkpoint pipeline.

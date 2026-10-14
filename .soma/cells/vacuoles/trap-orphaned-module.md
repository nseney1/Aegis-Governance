---
id: trap-orphaned-module
domain: correctness
type: vacuole
enforcement: advisory
hypothesis: A module with passing unit tests but zero callers in production code indicates an integration gap where functionality was built but never wired
prediction: "Will catch modules that have test_*.py coverage but no imports from soma_cli/, soma_mcp/, or enzymes/"
falsification: 0 findings in 20 sessions → prune
target_paths:
  - "soma_core/**/*.py"
  - "soma_cli/*.py"
  - "soma_mcp/*.py"
triggers:
  - module_creation
  - test_creation
  - integration_review
minimum_mode: standard
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
  triggers: 50
  true_positives: 11.3002
  false_positives: 13.6492
  last_trigger_date: "2026-10-14T06:50:24Z"
---

Supercell C4 incident: `quality_gate.py` had 30 passing unit tests and proper
AST-based assertion density checking, but `checkpoint.py` reimplemented the same
logic with brittle substring matching because quality_gate was never wired into the
checkpoint pipeline.

---
id: trap-layer-violation
domain: architecture
type: wall
enforcement: gate
hypothesis: "When module A imports private functions (_prefixed) from module B in a different architectural layer, it creates hidden coupling that breaks when B refactors"
prediction: "Will catch cross-layer private imports (e.g., soma_mcp importing _check_* from soma_cli)"
falsification: 0 findings in 20 sessions → prune
target_paths:
  - "soma_mcp/*.py"
  - "soma_cli/*.py"
  - "soma_core/**/*.py"
triggers:
  - import_modification
  - module_creation
  - architecture_review
minimum_mode: standard
expiry_sessions: 30
expiry_days: 90
created: 2026-09-30
impact_weight: 1.0
tags:
  - architecture
  - coupling
  - layer-violation
fitness:
  score: 0.6
  impact_weight: 1.0
  triggers: 52
  true_positives: 13.3002
  false_positives: 13.6492
  last_trigger_date: "2026-10-14T06:50:24Z"
---

Supercell C5 incident: `soma_mcp/tools.py` imported `_check_test_coverage`,
`_check_hardcoded_paths`, `_check_assertion_density`, `_check_cell_fitness` from
`soma_cli.checkpoint`. MCP should not reach into CLI internals. Fix: extract shared
logic to soma_core or inline it.

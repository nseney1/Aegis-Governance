---
id: trap-layer-violation
domain: architecture
type: trap
enforcement: gate
hypothesis: "When module A imports private functions (_prefixed) from module B in a different architectural layer, it creates hidden coupling that breaks when B refactors"
prediction: "Will catch cross-layer private imports (e.g., aegis_mcp importing _check_* from aegis_cli)"
falsification: 0 findings in 20 sessions → prune
target_paths:
  - "aegis_mcp/*.py"
  - "aegis_cli/*.py"
  - "aegis_core/**/*.py"
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
  triggers: 70
  true_positives: 17.7338
  false_positives: 17.423
  last_trigger_date: "2026-10-14T08:55:31Z"
---

Supercell C5 incident: `aegis_mcp/tools.py` imported `_check_test_coverage`,
`_check_hardcoded_paths`, `_check_assertion_density`, `_check_cell_fitness` from
`aegis_cli.checkpoint`. MCP should not reach into CLI internals. Fix: extract shared
logic to aegis_core or inline it.

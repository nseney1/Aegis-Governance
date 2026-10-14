---
id: contract-mcp-cli-parity
domain: correctness
type: contract
enforcement: advisory
hypothesis: The MCP server tools must expose the same capabilities as the CLI enzymes
prediction: New enzyme features added without corresponding MCP tool updates create feature gaps for non-Gemini users
falsification: MCP and CLI are intentionally divergent by design → reclassify
target_paths:
  - aegis_mcp/tools.py
  - aegis_cli/check.py
  - aegis_cli/verify.py
  - aegis_cli/report.py
  - aegis_core/telemetry.py
expiry_sessions: 15
expiry_days: 60
created: 2026-09-28
impact_weight: 1.2
minimum_mode: gale
tags:
  - mcp
  - api-surface
  - parity
  - cross-service
fitness:
  triggers: 55
  true_positives: 6.223
  false_positives: 3.2159
  score: 0.6667
  last_trigger_date: "2026-10-14T19:36:50Z"
---

The MCP server (aegis_mcp/tools.py) is the API contract for external agents.
When a new enzyme is added or an existing enzyme gains new features, the
corresponding MCP tool should be updated to maintain feature parity.
Current MCP tools: soma_create_cell, soma_scan, soma_grade, soma_coverage,
soma_fitness, soma_list_cells, soma_report_outcome, soma_propose_change,
soma_verify_changes, soma_checkpoint.

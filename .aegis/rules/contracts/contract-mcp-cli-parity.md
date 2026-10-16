---
id: contract-mcp-cli-parity
domain: correctness
type: contract
enforcement: advisory
hypothesis: The MCP server tools must expose the same capabilities as the CLI commands
prediction: New CLI features added without corresponding MCP tool updates create feature gaps for non-Gemini users
falsification: MCP and CLI are intentionally divergent by design → reclassify
target_paths:
  - aegis_mcp/tools.py
  - aegis_cli/check.py
  - aegis_cli/verify.py
  - aegis_cli/scan.py
  - aegis_core/telemetry_engine/ledger.py
expiry_sessions: 15
expiry_days: 60
created: 2026-09-28
impact_weight: 1.2
minimum_mode: sweep
tags:
  - mcp
  - api-surface
  - parity
  - cross-service
---

The MCP server (aegis_mcp/tools.py) is the API contract for external agents.
When a new CLI command is added or an existing command gains new features, the
corresponding MCP tool should be updated to maintain feature parity.
Current MCP tools (v4.0, D4): aegis_scan, aegis_report_outcome, aegis_create_rule,
aegis_list_rules.

---
id: persona-mcp-specialist
domain: style
type: persona
enforcement: advisory
hypothesis: A persona specialized in MCP (Model Context Protocol) enhances server integration.
prediction: "This persona will optimize `aegis_mcp/server.py` and `aegis_mcp/tools.py`."
falsification: The MCP server is trivial and requires no specialization.
target_paths:
  - "aegis_mcp/**"
expiry_sessions: 60
impact_weight: 0.9
minimum_mode: breeze
tags:
  - mcp
  - persona
  - api-surface
created: 2026-09-28
fitness:
  triggers: 61
  true_positives: 6.8986
  false_positives: 3.8075
  score: 0.6667
  last_trigger_date: "2026-10-14T19:36:50Z"
---

# Persona: MCP Specialist

Description: A specialist persona for maintaining and architecting the Soma MCP server and its tools, ensuring high performance and security.

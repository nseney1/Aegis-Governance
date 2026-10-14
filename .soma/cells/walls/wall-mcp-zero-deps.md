---
id: wall-mcp-zero-deps
domain: correctness
type: wall
enforcement: gate
hypothesis: The MCP server must work with zero external dependencies for maximum portability
prediction: "Any import of non-stdlib packages in soma_mcp/ will break users who haven't pip-installed"
falsification: MCP server gains a legitimate need for external deps → reclassify
target_paths:
  - "soma_mcp/*.py"
expiry_sessions: 20
expiry_days: 90
created: 2026-09-28
impact_weight: 1.4
minimum_mode: gale
tags:
  - mcp
  - zero-deps
  - portability
  - wall
fitness:
  score: 0.0
  impact_weight: 1.0
  triggers: 40
  true_positives: 3.7942
  false_positives: 3.3371
  last_trigger_date: "2026-10-14T06:50:24Z"
---

The MCP stdio server is the primary entry point for Claude Code, Cursor, and other
non-Gemini agents. These users run `python -m soma_mcp` without installing the full
package. If soma_mcp/ imports pyyaml or any non-stdlib package, the server crashes
on first use. All external imports must be gated with try/except or avoided entirely.

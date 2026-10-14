---
name: Aegis Guardrails
non_standard: true
trigger: always_on
description: Enforces mandatory JIT governance scanning before file edits and verification before commits.
---

# Aegis Guardrails

Before making changes to files in this project, call the `aegis_scan` MCP tool.
It will return 2-3 focused governance rules relevant to your specific change,
ranked by proven effectiveness.

After completing work, call `aegis_report_outcome` to improve future guidance.

> This project uses adaptive governance. Rules are not static — they evolve
> based on execution outcomes. Only rules that prove useful survive.

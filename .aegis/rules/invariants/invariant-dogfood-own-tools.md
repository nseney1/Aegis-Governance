---
id: invariant-dogfood-own-tools
domain: governance
type: invariant
enforcement: gate
hypothesis: "A governance framework that doesn't use its own tools to manage itself loses credibility and misses dogfooding feedback loops that surface UX gaps"
prediction: "Will fire when manual file operations (mv, cp, sed, manual frontmatter edits) are used instead of soma CLI commands (promote, demote, init, checkpoint) for operations that soma provides tooling for"
falsification: "If soma CLI lacks a needed operation for 5 consecutive sessions, the missing operation should be built rather than this cell pruned"
target_paths:
  - ".aegis/rules/**/*.md"
  - "aegis_cli/*.py"
  - "aegis_core/*.py"
triggers:
  - cell_creation
  - cell_promotion
  - cell_demotion
  - lifecycle_change
minimum_mode: standard
expiry_sessions: 50
expiry_days: 180
created: 2026-09-30
impact_weight: 1.0
tags:
  - governance
  - dogfooding
  - process
  - meta
fitness:
  score: 0.6
  impact_weight: 1.0
  triggers: 81
  true_positives: 40.198
  false_positives: 31.8419
  last_trigger_date: "2026-10-14T19:48:15Z"
---

When performing lifecycle operations on Soma's own cells (create, promote,
demote, verify), ALWAYS use the soma CLI or MCP tools first. If the tool
doesn't support the operation, that's a feature gap — build it, don't bypass it.

Supercell dogfooding incident #1: `trap-schema-contract-drift` was manually
promoted from vacuole→wall via `mv` + `sed` instead of `soma promote --force`.
This bypassed the automated frontmatter update and exposed a missing `--force`
flag in the promote command.

Supercell dogfooding incident #2: 8 new cells were created by manually writing
files instead of using `soma create-cell` or `enzymes/cell_create_nl.py`. This
bypassed format validation and resulted in `enforcement: blocking` instead of
the correct `enforcement: gate` — a convention the tool would have enforced.

Rule: If soma doesn't have a tool for the operation, build the tool first,
then use it. The framework's own codebase is its first and most important
test environment.

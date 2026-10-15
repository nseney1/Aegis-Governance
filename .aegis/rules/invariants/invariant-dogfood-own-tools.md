---
id: invariant-dogfood-own-tools
domain: governance
type: invariant
enforcement: gate
hypothesis: "A governance framework that doesn't use its own tools to manage itself loses credibility and misses dogfooding feedback loops that surface UX gaps"
prediction: "Will fire when manual file operations (mv, cp, sed, manual frontmatter edits) are used instead of aegis CLI commands (promote, demote, init, checkpoint) for operations that aegis provides tooling for"
falsification: "If aegis CLI lacks a needed operation for 5 consecutive sessions, the missing operation should be built rather than this rule pruned"
target_paths:
  - ".aegis/rules/*.md"
  - "aegis_cli/*.py"
  - "aegis_core/*.py"
triggers:
  - rule_creation
  - rule_promotion
  - rule_demotion
  - lifecycle_change
minimum_mode: patrol
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
  triggers: 85
  true_positives: 44.198
  false_positives: 31.8419
  last_trigger_date: "2026-10-14T22:29:45Z"
---

When performing lifecycle operations on Aegis's own rules (create, promote,
demote, verify), ALWAYS use the aegis CLI or MCP tools first. If the tool
doesn't support the operation, that's a feature gap — build it, don't bypass it.

Citadel dogfooding incident #1: `trap-schema-contract-drift` was manually
promoted from trap→invariant via `mv` + `sed` instead of `aegis promote --force`.
This bypassed the automated frontmatter update and exposed a missing `--force`
flag in the promote command.

Citadel dogfooding incident #2: 8 new rules were created by manually writing
files instead of using `aegis create-rule` or `aegis_cli/create.py`. This
bypassed format validation and resulted in `enforcement: blocking` instead of
the correct `enforcement: gate` — a convention the tool would have enforced.

Rule: If aegis doesn't have a tool for the operation, build the tool first,
then use it. The framework's own codebase is its first and most important
test environment.

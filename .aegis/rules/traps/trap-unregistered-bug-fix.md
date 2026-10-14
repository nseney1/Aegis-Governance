---
id: trap-unregistered-bug-fix
domain: documentation
type: trap
enforcement: gate
hypothesis: Bug fixes applied without a corresponding BUG_REGISTRY.json entry lose institutional memory — root cause patterns go untracked and recurring defect classes go undetected
prediction: "Will fire when a commit message contains bug-fix indicators (fix, bug, Bug-NNN) but docs/project/BUG_REGISTRY.json has no new entry in the same changeset"
falsification: 0 findings in 20 sessions → prune
target_paths:
  - docs/project/BUG_REGISTRY.json
  - "aegis_core/*.py"
  - "aegis_cli/*.py"
  - "aegis_mcp/*.py"
  - "aegis_sdk/*.py"
triggers:
  - bug_fix
  - commit_review
minimum_mode: standard
expiry_sessions: 30
expiry_days: 90
created: 2026-10-01
impact_weight: 1.0
tags:
  - documentation
  - bugs
  - institutional-memory
  - process
fitness:
  score: null
  impact_weight: 1.0
  triggers: 74
  true_positives: 25.857
  false_positives: 21.5412
  last_trigger_date: "2026-10-14T19:48:15Z"
---

v0.84 origin: Bugs 1-5 were discovered and fixed across v0.81-v0.82 but had no
centralized record beyond CHANGELOG prose. Root cause patterns (path_error,
schema_drift, silent_failure, mapping_error, dead_code) were only visible in
retrospect. This cell ensures that every bug fix is accompanied by a structured
registry entry linking the defect to its root cause category, regression test,
and affected files.

Detection: when a commit touches implementation code (enzymes/, aegis_cli/,
aegis_mcp/, aegis_sdk/) and contains "fix", "bug", or "Bug-" in the message,
check that BUG_REGISTRY.json is also modified in the same changeset. If not,
flag for review.

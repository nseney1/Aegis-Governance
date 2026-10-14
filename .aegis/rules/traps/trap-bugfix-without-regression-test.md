---
id: trap-bugfix-without-regression-test
domain: testing
type: trap
enforcement: gate
hypothesis: "Bug fixes applied without corresponding regression tests will allow the same defect to recur, compounding fix-refix cycles"
prediction: Will fire when a commit fixes a bug (changes implementation code) but does not add or modify a test that exercises the fixed behavior
falsification: 0 findings in 20 sessions → prune
target_paths:
  - "aegis_core/*.py"
  - "aegis_sdk/*.py"
  - "aegis_cli/*.py"
  - "aegis_mcp/*.py"
triggers:
  - bug_fix
  - commit_review
  - code_modification
minimum_mode: standard
expiry_sessions: 30
expiry_days: 90
created: 2026-10-01
impact_weight: 1.2
tags:
  - testing
  - regression
  - quality
  - process
fitness:
  score: null
  impact_weight: 1.2
  triggers: 56
  true_positives: 12.9983
  false_positives: 16.692
  last_trigger_date: "2026-10-14T07:33:06Z"
---

v0.81 origin: Bugs 1-3 in outcome_engine.py and sync.py were fixed without
regression tests. The telemetry path (.aegis/outcomes.jsonl → .aegis/evidence/outcomes.jsonl),
schema key (cells_used → cell_id), and outcome mapping (success→tp, failure→fp) were
all corrected surgically but had zero test coverage for the fixed behavior. This cell
ensures every bug fix is paired with a test proving the fix works and guarding against
regression.

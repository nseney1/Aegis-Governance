---
id: trap-recurring-finding-escape
domain: governance
type: wall
enforcement: gate
hypothesis: Findings flagged in multiple consecutive review cycles without resolution indicate deferred architectural debt that is actively degrading the codebase — each cycle the copies diverge further and the fix gets harder
prediction: Will fire when the same finding (by category or file) appears in N and N+1 cycle arbitration results without a corresponding fix commit
falsification: 0 findings in 10 sessions → prune
target_paths:
  - ".soma/evidence/arbitration_cycle_*.json"
  - soma_core/verification/review_adapter.py
triggers:
  - arbitration_complete
  - cycle_increment
  - review_finding_repeat
minimum_mode: standard
expiry_sessions: 50
expiry_days: 180
created: 2026-09-30
impact_weight: 1.0
tags:
  - governance
  - architectural-debt
  - review-escape
  - meta-antipattern
fitness:
  score: 0.75
  impact_weight: 1.0
  triggers: 36
  true_positives: 7.4945
  false_positives: 2.6805
  last_trigger_date: "2026-10-14T06:50:24Z"
---

Findings that appear in consecutive review cycles MUST be resolved, not deferred.

When the same finding survives 2+ cycles, it indicates one of:
1. The fix is architectural and keeps getting scoped out as "too big"
2. The finding is misclassified (should be INFO, not BLOCK) and wastes review bandwidth
3. The orchestrator acknowledges it but implicitly deprioritizes it

Supercell incident: The DRY violation between `soma_mcp/tools.py` and
`soma_cli/checkpoint.py` was flagged in Cycles 1, 2, and 3. Each cycle it
was noted but deferred. Meanwhile the copies diverged — tools.py was missing
`_check_cell_conventions` and `_check_arbitration_evidence`, causing the MCP
checkpoint to silently skip 2 of 6 checks.

Resolution protocol:
1. After each arbitration cycle, diff the findings against the previous cycle
2. Any finding that appears in both cycles gets auto-escalated to BLOCK
3. Architectural findings get a dedicated fix lane, not deferred to "next cycle"

Detection: Compare arbitration_cycle_N.json divergences against
arbitration_cycle_N-1.json — shared categories = recurring escape.

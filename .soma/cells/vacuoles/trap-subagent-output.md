---
id: trap-subagent-output
domain: correctness
type: vacuole
enforcement: advisory
promotion_threshold: 0.85
demotion_threshold: 0.3
hypothesis: "Subagent-generated content committed without orchestrator verification contains hardcoded paths, platform-specific assumptions, or hallucinated data"
prediction: Will flag subagent deliverables that introduce machine-specific or ungrounded content into the repository
falsification: 0 findings in 10 sessions → prune
target_paths:
  - "genome/*.md"
  - "docs/**/*.md"
  - "organs/**/*.md"
  - ".soma/cells/**/*.md"
triggers:
  - subagent_deliverable
  - documentation_update
  - rule_creation
expiry_sessions: 10
expiry_days: 30
created: 2026-09-30
impact_weight: 0.9
tags:
  - subagent
  - hallucination
  - verification
fitness:
  score: 0.5
  impact_weight: 0.9
  triggers: 51
  true_positives: 25.25
  false_positives: 21.75
  last_trigger_date: "2026-10-14T06:50:24Z"
---

Subagent-generated content (documentation, rules, configs) must be verified
by the orchestrator before committing. Known failure modes:
- Absolute `file:///home/...` paths leaked from agent context (Session 2026-09-30)
- Platform-specific tool names hardcoded in multi-platform code (Session 2026-09-30)
- Hallucinated directory counts and file inventories (Session 2026-09-30)

Verify: `grep -rn '/home/' <file>` and review for platform assumptions.

---
id: trap-subagent-output
domain: correctness
type: trap
enforcement: advisory
promotion_threshold: 0.85
demotion_threshold: 0.3
hypothesis: "Subagent-generated content committed without orchestrator verification contains hardcoded paths, platform-specific assumptions, or hallucinated data"
prediction: Will flag subagent deliverables that introduce machine-specific or ungrounded content into the repository
falsification: 0 findings in 10 sessions → prune
target_paths:
  - "rules/*.md"
  - "docs/**/*.md"
  - "skills/**/*.md"
  - ".aegis/rules/**/*.md"
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
  triggers: 69
  true_positives: 34.25
  false_positives: 30.75
  last_trigger_date: "2026-10-14T08:55:41Z"
---

Subagent-generated content (documentation, rules, configs) must be verified
by the orchestrator before committing. Known failure modes:
- Absolute `file:///home/...` paths leaked from agent context (Session 2026-09-30)
- Platform-specific tool names hardcoded in multi-platform code (Session 2026-09-30)
- Hallucinated directory counts and file inventories (Session 2026-09-30)

Verify: `grep -rn '/home/' <file>` and review for platform assumptions.

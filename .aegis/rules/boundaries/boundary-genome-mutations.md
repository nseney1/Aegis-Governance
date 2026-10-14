---
id: boundary-genome-mutations
domain: governance
type: boundary
enforcement: advisory
promotion_threshold: 0.85
demotion_threshold: 0.3
hypothesis: "Changes to rules/*.md need elevated review — these are the core governance rules"
prediction: Escalation sentinel will apply minimum vanguard mode for core rule mutations
falsification: All escalated reviews are over-kill for 10 sessions → prune
target_paths:
  - "rules/*.md"
  - "rules/**"
expiry_sessions: 10
expiry_days: 45
created: 2026-09-28
impact_weight: 1.2
minimum_mode: vanguard
tags:
  - rules
  - review-escalation
  - core-rules
fitness:
  triggers: 15
  true_positives: 7.5
  false_positives: 6
  score: 0.6667
  last_trigger_date: "2026-10-14T22:29:45Z"
---

Changes to the core rules (`rules/`) directory are high-impact changes that affect every
user of Aegis. Modifications to these files change the inherited behavioral defaults of
the system and require elevated review intensity.

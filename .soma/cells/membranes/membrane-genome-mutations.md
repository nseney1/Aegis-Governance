---
id: membrane-genome-mutations
domain: governance
type: membrane
enforcement: advisory
promotion_threshold: 0.85
demotion_threshold: 0.3
hypothesis: "Changes to genome/*.md need elevated review — these are the organism's DNA"
prediction: Escalation sentinel will apply minimum trident mode for genome mutations
falsification: All escalated reviews are over-kill for 10 sessions → prune
target_paths:
  - "genome/*.md"
  - "genome/**"
expiry_sessions: 10
expiry_days: 45
created: 2026-09-28
impact_weight: 1.2
minimum_mode: trident
tags:
  - genome
  - review-escalation
  - dna
fitness:
  triggers: 5
  true_positives: 2.5
  false_positives: 1
  score: 0.6667
  last_trigger_date: "2026-10-14T04:44:03Z"
---

Changes to the genome (rules) directory are high-impact mutations that affect every
user of Soma. Modifications to these files change the inherited behavioral DNA of
the organism and require elevated review intensity.

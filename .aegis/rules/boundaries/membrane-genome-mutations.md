---
id: membrane-genome-mutations
domain: governance
type: boundary
enforcement: advisory
promotion_threshold: 0.85
demotion_threshold: 0.3
hypothesis: "Changes to rules/*.md need elevated review — these are the organism's DNA"
prediction: Escalation sentinel will apply minimum trident mode for genome mutations
falsification: All escalated reviews are over-kill for 10 sessions → prune
target_paths:
  - "rules/*.md"
  - "rules/**"
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
  triggers: 11
  true_positives: 3.5
  false_positives: 6
  score: 0.6667
  last_trigger_date: "2026-10-14T07:33:06Z"
---

Changes to the genome (rules) directory are high-impact mutations that affect every
user of Soma. Modifications to these files change the inherited behavioral DNA of
the organism and require elevated review intensity.

---
id: trap-ascii-art-render
domain: documentation
type: trap
enforcement: advisory
hypothesis: Editing ASCII art box diagrams without verifying visual width causes truncated or misaligned rendering in markdown viewers
prediction: Will fire when commits modify lines inside ASCII box-drawing character regions
falsification: 0 findings in 20 sessions → prune
target_paths:
  - README.md
  - "docs/**/*.md"
triggers:
  - documentation_edit
  - readme_modification
minimum_mode: standard
expiry_sessions: 30
expiry_days: 90
created: 2026-09-30
impact_weight: 1.0
tags:
  - documentation
  - rendering
  - ascii-art
fitness:
  score: 0.3333
  impact_weight: 1.0
  triggers: 56
  true_positives: 13.9161
  false_positives: 10.8334
  last_trigger_date: "2026-10-14T19:36:50Z"
---

Supercell doc-drift incident: Adding "→ Supercell" to the architecture diagram
made the line overflow the fixed-width box border. The text was correct but
visually broken. Detection: verify all lines between box-drawing chars have equal
visible width.

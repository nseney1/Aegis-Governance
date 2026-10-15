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
  - "docs/*.md"
triggers:
  - documentation_edit
  - readme_modification
minimum_mode: patrol
expiry_sessions: 30
expiry_days: 90
created: 2026-09-30
impact_weight: 1.0
tags:
  - documentation
  - rendering
  - ascii-art
---

Citadel doc-drift incident: Adding "→ Citadel" to the architecture diagram
made the line overflow the fixed-width box border. The text was correct but
visually broken. Detection: verify all lines between box-drawing chars have equal
visible width.

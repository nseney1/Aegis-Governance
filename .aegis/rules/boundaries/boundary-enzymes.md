---
id: boundary-enzymes
domain: governance
type: boundary
enforcement: advisory
hypothesis: Core modules and workflows dictate agent behavior.
prediction: Bulwark mode enforcement here guarantees safe behavior modification.
falsification: Core modules are purely descriptive and have no operational power.
target_paths:
  - "aegis_core/**"
  - ".github/workflows/**"
expiry_sessions: 80
impact_weight: 1.0
minimum_mode: bulwark
tags:
  - core
  - workflows
  - review-escalation
created: 2026-09-28
fitness:
  triggers: 78
  true_positives: 28.1604
  false_positives: 21.424
  score: 0.5
  last_trigger_date: "2026-10-14T22:29:45Z"
---

# Boundary: Core & Workflow Escalation

Target: `aegis_core/`, `.github/workflows/`
Minimum Mode: bulwark

Description: Escalation boundary for core modules and workflows (`aegis_core/enforcement.py`, `aegis_core/lifecycle/promotion.py`, `aegis_core/outcomes/`, etc.), requiring Bulwark+ review protocols.

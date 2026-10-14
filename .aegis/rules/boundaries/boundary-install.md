---
id: boundary-install
domain: governance
type: boundary
enforcement: advisory
hypothesis: Install scripts represent high-risk operations requiring elevated governance.
prediction: Enforcing maelstrom mode for install operations prevents unsafe system changes.
falsification: Install scripts operate in a fully sandboxed environment with no persistent effects.
target_paths:
  - "install/**"
expiry_sessions: 80
impact_weight: 1.0
minimum_mode: maelstrom
tags:
  - install
  - deployment
  - review-escalation
created: 2026-09-28
fitness:
  triggers: 12
  true_positives: 2.7
  false_positives: 3.6
  score: 1.0
  last_trigger_date: "2026-10-14T07:33:06Z"
---

# Membrane: Install Escalation

Target: `install/`
Minimum Mode: maelstrom

Description: Escalation membrane for install and uninstall scripts, requiring Maelstrom+ review protocols.

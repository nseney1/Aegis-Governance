---
id: boundary-install
domain: governance
type: boundary
enforcement: advisory
hypothesis: Install scripts represent high-risk operations requiring elevated governance.
prediction: Enforcing bulwark mode for install operations prevents unsafe system changes.
falsification: Install scripts operate in a fully sandboxed environment with no persistent effects.
target_paths:
  - aegis_cli/init.py
  - aegis_cli/uninstall.py
  - aegis_cli/hooks/management.py
  - "aegis_cli/platforms/*.py"
expiry_sessions: 80
impact_weight: 1.0
minimum_mode: bulwark
tags:
  - install
  - deployment
  - review-escalation
created: 2026-09-28
---

# Boundary: Install Escalation

Target: the code that writes outside the repository on install and uninstall (`aegis init`, `aegis uninstall`, `aegis hook install`, platform adapters)
Minimum Mode: bulwark

Description: Escalation boundary for install and uninstall scripts, requiring Bulwark+ review protocols.

---
id: invariant-core-installers
domain: correctness
type: invariant
enforcement: gate
promotion_threshold: 0.85
demotion_threshold: 0.3
hypothesis: "Changes to the platform installers, the git hook installer and the Makefile require install-flow review"
prediction: Will flag unreviewed changes to core installer infrastructure
falsification: 0 findings in 15 sessions → prune
target_paths:
  - "aegis_cli/platforms/*.py"
  - aegis_cli/cli.py
  - aegis_cli/hooks/management.py
  - Makefile
expiry_sessions: 15
expiry_days: 60
created: 2026-09-28
impact_weight: 1.5
minimum_mode: vanguard
tags:
  - install
  - cross-platform
  - safety-critical
---

The install flow is the first thing every user touches. Breakage here means
broken onboarding across Linux, macOS, WSL, and Windows. Changes to these files
must be reviewed for cross-platform compatibility and path correctness.

---
id: invariant-core-installers
domain: correctness
type: invariant
enforcement: gate
promotion_threshold: 0.85
demotion_threshold: 0.3
hypothesis: "Changes to install.sh, install.ps1, uninstall.sh, common.sh, and Makefile require install-flow review"
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
fitness:
  score: null
  impact_weight: 1.0
  triggers: 62
  true_positives: 8.245
  false_positives: 7.0844
  last_trigger_date: "2026-10-14T22:29:45Z"
---

The install flow is the first thing every user touches. Breakage here means
broken onboarding across Linux, macOS, WSL, and Windows. Changes to these files
must be reviewed for cross-platform compatibility and path correctness.

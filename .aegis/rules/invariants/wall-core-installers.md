---
id: wall-core-installers
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
  - "install/hooks/*"
  - install/aegis.conf.example
  - Makefile
expiry_sessions: 15
expiry_days: 60
created: 2026-09-28
impact_weight: 1.5
minimum_mode: trident
tags:
  - install
  - cross-platform
  - safety-critical
fitness:
  score: null
  impact_weight: 1.0
  triggers: 44
  true_positives: 3.8412
  false_positives: 6.3671
  last_trigger_date: "2026-10-14T07:33:06Z"
---

The install flow is the first thing every user touches. Breakage here means
broken onboarding across Linux, macOS, WSL, and Windows. Changes to these files
must be reviewed for cross-platform compatibility and path correctness.

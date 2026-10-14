---
id: invariant-install-uninstall-parity
domain: correctness
type: invariant
enforcement: gate
hypothesis: Every platform in the installer must have a matching uninstall path
prediction: Adding a new platform to install.sh without updating uninstall.sh creates orphaned files
falsification: Platform count matches between install.sh and uninstall.sh for 10 sessions → maintain
target_paths:
  - "aegis_cli/platforms/*.py"
  - aegis_cli/cli.py
expiry_sessions: 15
expiry_days: 60
created: 2026-09-28
impact_weight: 1.3
minimum_mode: vanguard
tags:
  - install
  - uninstall
  - parity
  - lifecycle
fitness:
  score: null
  impact_weight: 1.0
  triggers: 62
  true_positives: 3.0457
  false_positives: 1.8187
  last_trigger_date: "2026-10-14T22:29:45Z"
---

The install and uninstall scripts must support the same set of platforms. When adding
Claude Code support (or any new platform), both install.sh and uninstall.sh must be
updated in the same PR. The Makefile uninstall target must also be kept in sync.

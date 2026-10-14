---
id: trap-stale-rename-refs
domain: correctness
type: trap
enforcement: advisory
hypothesis: Bulk renames leave stale references to old names in files not covered by the rename script
prediction: "Will catch orphaned references to 'prism', 'steering', 'rules/', 'skills/', 'scripts/' after rename operations"
falsification: 0 stale references found in 5 sessions → prune
target_paths:
  - "aegis_core/*.py"
  - "aegis_cli/*.py"
  - "aegis_mcp/*.py"
  - "aegis_sdk/*.py"
  - Makefile
  - README.md
expiry_sessions: 10
expiry_days: 30
created: 2026-09-28
impact_weight: 1.3
minimum_mode: gale
tags:
  - rename
  - migration
  - anti-pattern
  - high-value
fitness:
  score: 0.5
  impact_weight: 1.0
  triggers: 74
  true_positives: 27.1361
  false_positives: 26.3697
  last_trigger_date: "2026-10-14T19:09:13Z"
---

After the Phase 22 Soma Rebirth rename, multiple stale references survived:
- `scripts_dir = "$repo_dir/scripts"` in common.sh (CRITICAL — broke all hooks)
- `prism_root` variable names in soma_resolve.py and aegis_mcp/tools.py  
- `.prism` directory check in cell_transfer.sh (always false after rename)
- "Installing steering rules" banners in install.sh and install.ps1

Any future rename operation must include a post-rename grep sweep.

---
id: trap-install-paths
domain: correctness
type: trap
enforcement: advisory
hypothesis: Install scripts have divergent paths.
prediction: Unifying install targets will prevent deployment errors.
falsification: The paths are intentionally distinct for separate deploy targets.
target_paths:
  - aegis_cli/install_hosts.py
  - Makefile
expiry_sessions: 40
impact_weight: 0.9
minimum_mode: patrol
tags:
  - install
  - paths
  - correctness
created: 2026-09-28
---

# Trap: Install Paths Divergence

Target: `aegis_cli/install_hosts.py` vs `Makefile`

Description: Install targets diverge (`~/.gemini/config/rules/` vs `~/.gemini/config/rules/`). These need to be unified or clearly documented if intentionally separated.

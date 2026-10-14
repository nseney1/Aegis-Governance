---
id: trap-version-drift
domain: correctness
type: vacuole
enforcement: advisory
hypothesis: "Version numbers across VERSION, pyproject.toml, and soma_sdk/__init__.py must stay in sync"
prediction: Will catch version drift when bumping versions in one file but not others
falsification: 0 version mismatches in 10 sessions → prune
target_paths:
  - VERSION
  - pyproject.toml
  - soma_sdk/__init__.py
expiry_sessions: 10
expiry_days: 45
created: 2026-09-28
impact_weight: 1.0
minimum_mode: breeze
tags:
  - versioning
  - consistency
  - release
fitness:
  score: 0.7273
  impact_weight: 1.0
  triggers: 28
  true_positives: 19
  false_positives: 8
  last_trigger_date: "2026-10-14T04:44:03Z"
---

Version consistency is enforced across 3 sources:
- `VERSION` (single source of truth)
- `pyproject.toml` (Python package)
- `soma_sdk/__init__.py` (Python SDK)

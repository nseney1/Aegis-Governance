---
id: trap-version-drift
domain: correctness
type: trap
enforcement: advisory
hypothesis: "Version numbers across aegis_core/_version.py, pyproject.toml, and aegis_sdk/__init__.py must stay in sync"
prediction: Will catch version drift when bumping versions in one file but not others
falsification: 0 version mismatches in 10 sessions → prune
target_paths:
  - aegis_core/_version.py
  - pyproject.toml
  - aegis_sdk/__init__.py
expiry_sessions: 10
expiry_days: 45
created: 2026-09-28
impact_weight: 1.0
minimum_mode: patrol
tags:
  - versioning
  - consistency
  - release
---

Version consistency is enforced across 3 sources:
- `aegis_core/_version.py` (single source of truth)
- `pyproject.toml` (Python package)
- `aegis_sdk/__init__.py` (Python SDK)

---
id: trap-path-traversal
domain: security
type: trap
enforcement: gate
hypothesis: "User-supplied file paths (CLI --files, API params) that are joined with a root directory without containment checks enable reading/writing arbitrary files outside the workspace"
prediction: "Will flag os.path.join(root, user_input) without is_relative_to() or startswith() guard"
falsification: 0 findings in 20 sessions → prune
target_paths:
  - "**/*.py"
triggers:
  - python_file_creation
  - python_file_modification
  - security_review
minimum_mode: standard
expiry_sessions: 30
expiry_days: 90
created: 2026-09-30
impact_weight: 1.0
tags:
  - security
  - path-traversal
  - critical
fitness:
  score: 0.625
  impact_weight: 1.0
  triggers: 80
  true_positives: 33.2383
  false_positives: 29.9993
  last_trigger_date: "2026-10-14T19:26:54Z"
---

Supercell S2 incident: `aegis_cli/verify.py` accepted `--files ../../etc/passwd`
without containment, allowing path traversal. Fix: resolve path and check
`resolved.startswith(root + os.sep)`.

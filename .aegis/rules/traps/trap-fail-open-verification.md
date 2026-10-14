---
id: trap-fail-open-verification
domain: security
type: trap
enforcement: gate
hypothesis: "Verification tools that return empty/success on execution failure silently bypass the safety gate — the tool reports \"all checks passed\" when it actually crashed before checking anything"
prediction: "Will fire when a verification function returns an empty list, True, or exit code 0 on an error path (missing file, crashed subprocess, None data)"
falsification: 0 findings in 10 sessions → prune
target_paths:
  - "aegis_core/verification/*.py"
  - aegis_cli/verify.py
  - aegis_cli/checkpoint.py
triggers:
  - verification_modification
  - error_handling_change
  - security_review
minimum_mode: patrol
expiry_sessions: 50
expiry_days: 180
created: 2026-09-30
impact_weight: 1.0
tags:
  - security
  - verification
  - fail-open
  - critical
fitness:
  score: 0.8333
  impact_weight: 1.0
  triggers: 65
  true_positives: 12.0823
  false_positives: 6.2468
  last_trigger_date: "2026-10-14T22:29:45Z"
---

Verification tools MUST fail-closed: any execution error must produce a
FAIL verdict, never a PASS.

Citadel Cycle 2 incidents:
1. `branch_coverage.py:137` — when trace script crashed, `results_file` didn't
   exist, function returned `[]`, caller computed `verdict = len([]) == 0` → True
   (all branches covered). Fix: return `None` on crash, caller treats as fail.

2. `branch_coverage.py:210` — when target file wasn't in coverage report,
   `file_data is None` returned `[]` → verdict True. An untested file passed
   coverage. Fix: return `[-1]` sentinel so verdict is False.

3. `verify.py:128` — when all --files were out-of-tree, `safe_files` became `[]`,
   verification ran on nothing, exited 0 (PASS). Fix: exit 1 when explicit
   files are provided but none are in-tree.

Detection: grep for `return []` in verification functions and check if the
caller treats empty as success.

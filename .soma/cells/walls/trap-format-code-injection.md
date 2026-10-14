---
id: trap-format-code-injection
domain: security
type: wall
enforcement: gate
hypothesis: Using str.format() or f-strings to inject variables into executable code templates enables code injection when inputs contain quotes or Python syntax
prediction: "Will catch .format() calls on strings that are later executed via subprocess, exec(), eval(), or written as .py files"
falsification: 0 findings in 20 sessions → prune
target_paths:
  - "**/*.py"
triggers:
  - python_file_creation
  - python_file_modification
  - security_review
minimum_mode: standard
expiry_sessions: 50
expiry_days: 180
created: 2026-09-30
impact_weight: 1.0
tags:
  - security
  - injection
  - critical
fitness:
  score: 0.7
  impact_weight: 1.0
  triggers: 61
  true_positives: 24.9099
  false_positives: 21.587
  last_trigger_date: "2026-10-14T06:50:24Z"
---

When generating executable code (Python scripts, shell commands) via string
formatting, all user-controlled or path-derived variables MUST be escaped
with `repr()` or `shlex.quote()` before interpolation.

Supercell S1 incident: `branch_coverage.py` used `_TRACE_SCRIPT_TEMPLATE.format(
test_file=test_file)` to inject file paths directly into Python string literals.
A path containing `"); import os; os.system("id` would execute arbitrary code.

Detection: grep for `.format(` in files that also contain `subprocess.run`,
`exec(`, `eval(`, or write to `.py` files.

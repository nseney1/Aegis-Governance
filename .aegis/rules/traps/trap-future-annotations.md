---
id: trap-future-annotations
domain: correctness
type: trap
enforcement: advisory
promotion_threshold: 0.85
demotion_threshold: 0.3
hypothesis: "Python files using PEP 604 union syntax (X | None) without from __future__ import annotations crash on Python 3.9"
prediction: Will flag new or modified .py files using pipe unions without the future import
falsification: 0 findings in 10 sessions → prune
target_paths:
  - "**/*.py"
triggers:
  - python_file_creation
  - python_file_modification
expiry_sessions: 10
expiry_days: 30
created: 2026-09-30
impact_weight: 0.8
tags:
  - compatibility
  - python39
  - runtime-crash
fitness:
  score: 0.6
  impact_weight: 0.8
  triggers: 77
  true_positives: 31.2383
  false_positives: 28.9993
  last_trigger_date: "2026-10-14T19:26:54Z"
---

Any Python file using `X | None`, `list[str] | None`, or similar PEP 604
union type syntax MUST include `from __future__ import annotations` at the
top of the file. Without it, the code crashes on Python 3.9 with a TypeError.

The project declares `python_requires = ">=3.9"` in pyproject.toml.

Known incident: 5 files in immune_system/verification/ and tests/ used pipe
unions without the future import, crashing on 3.9 runtimes.

Check: `grep -l '| None' <file> | xargs grep -L 'from __future__'`

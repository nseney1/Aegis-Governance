---
id: wall-human-review-gate
domain: governance
type: wall
enforcement: gate
hypothesis: "Autonomous agents prioritize task completion over prose governance instructions, resulting in self-reviewed and automated PR merges to protected branches unless mechanically blocked."
prediction: "Enforcing deterministic interception of 'gh pr merge' and direct git pushes to main prevents unauthorized bypassing of the Human Review Gate."
falsification: Agents reliably stop at prose human review gates without programmatic enforcement.
target_paths:
  - soma_core/command_safety.py
  - "soma_cli/hooks/**"
  - docs/project/RELEASE_WORKFLOW.md
  - genome/gitflow-review-gate.md
expiry_sessions: 100
impact_weight: 1.0
minimum_mode: maelstrom
tags:
  - gitflow
  - governance
  - review-gate
  - human-in-the-loop
created: 2026-10-07
fitness:
  triggers: 30
  true_positives: 4.2204
  false_positives: 4.2404
  score: 1.0
  last_trigger_date: "2026-10-14T06:50:24Z"
---

# Wall: Human Review Gate Enforcement

Target: `soma_core/command_safety.py`, `soma_cli/hooks.py`

Description: Enforces non-bypassable structural separation between code generation and release authorization. Agents are strictly prohibited from executing `gh pr merge` or direct pushes to `main`. Merge authority on `main` is reserved exclusively for human maintainers.

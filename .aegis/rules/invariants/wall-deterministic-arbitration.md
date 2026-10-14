---
id: wall-deterministic-arbitration
domain: governance
type: invariant
enforcement: gate
hypothesis: "When the orchestrator manually arbitrates Prosecutor/Defender findings instead of using the deterministic arbiter, subjective bias enters the process and findings can be rationalized away"
prediction: Will fire when review findings are resolved by orchestrator judgment instead of structured arbitration through the arbiter
falsification: "If the arbiter cannot handle a finding category after 3 extensions, revisit the architecture"
target_paths:
  - aegis_core/verification/arbiter.py
  - skills/adaptive-reviewer/SKILL.md
  - "aegis_cli/*.py"
triggers:
  - review_arbitration
  - supercell_review
  - verdict_computation
minimum_mode: standard
expiry_sessions: 50
expiry_days: 180
created: 2026-09-30
impact_weight: 1.0
tags:
  - governance
  - arbitration
  - deterministic
  - process
fitness:
  score: 0.75
  impact_weight: 1.0
  triggers: 65
  true_positives: 12.2314
  false_positives: 8.989
  last_trigger_date: "2026-10-14T08:55:31Z"
---

Review finding arbitration MUST go through the deterministic arbiter, not
the orchestrator's judgment. The arbiter uses set-algebra on RiskCategory
enums — no LLM, no subjective filtering.

Supercell arbitration incident: After launching Prosecutor/Defender pairs for
Cycle 2, the orchestrator planned to manually read both reports and decide
which findings "survived." This bypasses the entire point of adversarial review
— the arbiter exists precisely to remove subjective bias from verdict computation.

Process: Prosecutor outputs → Prediction objects. Defender outputs → Claim objects.
Layer 1 tools → ToolEvidence. All three feed into arbiter.arbitrate() for a
deterministic SHIP/BLOCK/REVISE verdict.

When the arbiter lacks a needed RiskCategory, extend the enum — don't bypass
the arbiter.

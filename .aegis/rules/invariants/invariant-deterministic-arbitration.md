---
id: invariant-deterministic-arbitration
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
  - citadel_review
  - verdict_computation
minimum_mode: patrol
expiry_sessions: 50
expiry_days: 180
created: 2026-09-30
impact_weight: 1.0
tags:
  - governance
  - arbitration
  - deterministic
  - process
---

Review finding arbitration MUST go through the deterministic arbiter, not
the orchestrator's judgment. The arbiter uses set-algebra on RiskCategory
enums — no LLM, no subjective filtering.

Citadel arbitration incident: After launching Prosecutor/Defender pairs for
Cycle 2, the orchestrator planned to manually read both reports and decide
which findings "survived." This bypasses the entire point of adversarial review
— the arbiter exists precisely to remove subjective bias from verdict computation.

Process: Prosecutor outputs → Prediction objects. Defender outputs → Claim objects.
Layer 1 tools → ToolEvidence. All three feed into arbiter.arbitrate() for a
deterministic SHIP/BLOCK/REVISE verdict.

When the arbiter lacks a needed RiskCategory, extend the enum — don't bypass
the arbiter.

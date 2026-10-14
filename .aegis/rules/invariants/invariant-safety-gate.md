---
id: invariant-safety-gate
domain: security
type: invariant
enforcement: gate
hypothesis: The safety gate script is a critical security boundary.
prediction: Enforcing strict boundaries on this file prevents unauthorized circumvention of safety checks.
falsification: The script is entirely benign and requires no protection.
target_paths:
  - "aegis_cli/hooks/**"
expiry_sessions: 100
impact_weight: 1.0
minimum_mode: maelstrom
tags:
  - safety
  - security
  - gate
created: 2026-09-28
fitness:
  triggers: 22
  true_positives: 3.68
  false_positives: 0.93
  score: 1.0
  last_trigger_date: "2026-10-14T19:43:08Z"
---

# Wall: Safety Gate

Target: `enzymes/safety_gate.sh`

Description: Security boundary for the safety gate. It has a hardcoded log path `~/.gemini/antigravity/scratch/ai-conversation-logs/governance/gate_events.jsonl` which needs careful management.

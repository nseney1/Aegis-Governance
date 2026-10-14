---
id: trap-hardcoded-paths
domain: correctness
type: trap
enforcement: advisory
promotion_threshold: 0.85
demotion_threshold: 0.3
hypothesis: "Hardcoded platform paths (e.g. ~/.gemini, ~/.kiro) in scripts break cross-platform installs"
prediction: Will flag hardcoded paths where dynamic SOMA_PLATFORM logic is required
falsification: 0 findings in 10 sessions → prune
target_paths:
  - "aegis_cli/platforms/*.py"
  - "aegis_cli/*.py"
  - "aegis_core/*.py"
expiry_sessions: 10
expiry_days: 30
created: 2026-09-28
impact_weight: 0.8
tags:
  - portability
  - cross-platform
  - anti-pattern
fitness:
  score: 0.6667
  impact_weight: 1.0
  triggers: 77
  true_positives: 21.9439
  false_positives: 18.0668
  last_trigger_date: "2026-10-14T19:48:15Z"
---

Scripts should use SOMA_PLATFORM and resolve_home() to determine paths dynamically,
not hardcode ~/.gemini or ~/.kiro. Hardcoded paths break on other platforms and
prevent new platform support (e.g., Claude Code).

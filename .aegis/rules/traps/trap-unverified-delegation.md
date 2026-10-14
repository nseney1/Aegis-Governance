---
id: trap-unverified-delegation
domain: correctness
type: trap
enforcement: advisory
hypothesis: Subagent self-reports are cheap talk — edits must be verified against file contents
prediction: Accepting subagent completion reports without grepping for actual file changes leads to silent regressions where claimed fixes never landed
falsification: "If 20 consecutive subagent delegations all pass post-hoc file verification, this vacuole is unnecessary"
target_paths:
  - "aegis_core/*.py"
  - "aegis_cli/*.py"
  - "tests/*.py"
  - "aegis_mcp/*.py"
triggers:
  - delegation
  - subagent
minimum_mode: standard
expiry_sessions: 30
expiry_days: 90
fitness:
  score: 0.5
  impact_weight: 1.0
  triggers: 78
  true_positives: 31.6628
  false_positives: 29.3898
  last_trigger_date: "2026-10-14T19:48:15Z"
---

# Trap: Unverified Delegation

When a subagent reports "done", **verify the claim against the actual file contents**
before accepting the result.

## Evidence

Session 2026-09-30: B.2 subagent reported replacing 11 tautological tests with
behavioral tests. In reality, `test_bayesian_fitness.py` still had 7 tests
computing local arithmetic (`(tp + 1) / (triggers + 2)`) instead of calling
production `bayesian_fitness()`. The subagent's edits failed silently (filesystem
issue in sandbox). We committed based on the report, not the files.

The tests passed because tautological tests *always* pass — they test Python
arithmetic, not production code. This made the false report undetectable via
the test suite alone.

## Rule

After receiving a subagent completion debrief:

1. **Verify file contents**: `grep` for the claimed changes in target files
2. **Verify imports**: Check that new tests actually import production modules
3. **Verify behavior**: Run the specific tests and confirm they call real code
4. **Never trust "N tests pass"**: Tautological tests pass regardless of code state

## Game Theory

This is the **cheap talk** problem: claims are costless to make but expensive
to verify. The incentive gradient favors reporting success over admitting partial
failure. The fix is **revealed preference** — verify what was *done*, not what
was *said*.

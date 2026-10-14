---
id: trap-happy-path-only-tests
domain: correctness
type: trap
enforcement: advisory
hypothesis: Test suites that only validate happy paths miss adversarial edge cases that auditors consistently find
prediction: Sessions with ≥1 negative test per public function will have fewer audit-surfaced bugs
falsification: Negative test ratio shows no correlation with audit finding count after 20 sessions
target_paths:
  - "tests/*.py"
minimum_mode: breeze
origin: human_insight
created: 2026-09-30
expiry_sessions: 10
expiry_days: 30
tags:
  - testing
  - adversarial
  - quality
  - anti-pattern
fitness:
  score: 0.6
  impact_weight: 1.0
  triggers: 71
  true_positives: 23.7765
  false_positives: 19.5173
  last_trigger_date: "2026-10-14T19:48:15Z"
---

When reviewing test files, check that every public function under test has at
least one **negative or adversarial test case** — a test that verifies the
function correctly rejects, handles, or survives bad input.

## Minimum Bar (v1)

For each public function in the module under test, there should exist at least
one test that asserts a "should NOT" behavior:
- Invalid input is rejected (not silently accepted)
- Boundary values don't cause crashes
- Adversarial inputs don't bypass security invariants

## Evidence (from session 2026-09-30)

The evidence collector (`enzymes/evidence_collector.py`) shipped with 19 passing
tests and zero failures. Two independent auditors then found 4 critical bugs:

| Bug | Category | Would a negative test have caught it? |
|:----|:---------|:--------------------------------------|
| Root path `"/"` bypasses all compliance checks | Adversarial input | **Yes** |
| `str` path crashes (expected `Path`) | Type boundary | Partially — if testing caller conventions |
| Duplicate YAML key masked by parser | Structural invariant | No — test infrastructure was complicit |
| Generator missing required field | Lifecycle gap | No — different test category needed |

**Conclusion**: A negative test ratio catches ~50% of audit findings. It's a
floor, not a ceiling. Future iterations should expand to require tests across
multiple orthogonal categories (integration contracts, structural invariants,
lifecycle validation).

## Iteration Target

When evidence shows this ratio alone is insufficient (predicted: after ~10
sessions), evolve to require tests in ≥3 of 6 categories:
1. Happy path
2. Adversarial/negative
3. Boundary
4. Integration contract
5. Structural invariant
6. Lifecycle (producer → consumer)

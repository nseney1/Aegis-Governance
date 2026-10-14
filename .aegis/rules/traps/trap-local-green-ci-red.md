---
id: trap-local-green-ci-red
domain: governance
type: trap
enforcement: advisory
hypothesis: "Agents rationalize persistent CI failures as \"pre-existing\" or \"environment issues\" without reading the actual CI log, causing stacked failures to accumulate"
prediction: "When an agent declares a fix complete based only on local test results, the CI build will reveal at least one additional failure layer that local testing did not surface"
falsification: "If 5 consecutive CI-touching changes pass CI on first push without any post-push fixes, this vacuole is unnecessary"
target_paths:
  - ".github/workflows/*.yml"
  - "tests/*.py"
  - "aegis_core/*.py"
  - "aegis_cli/*.py"
  - Makefile
triggers:
  - ci_fix
  - test_fix
  - build_fix
created: 2026-09-30
expiry_days: 90
expiry_sessions: 30
fitness:
  score: 0.5
  impact_weight: 1.0
  triggers: 78
  true_positives: 32.1622
  false_positives: 29.8304
  last_trigger_date: "2026-10-14T19:48:15Z"
---

## Trap: Local Green ≠ CI Green

**Pattern**: Agent runs tests locally, sees green (or dismisses a known red), and declares the fix complete without verifying the actual CI build.

**Why it's dangerous**: Failures stack. Each fix only reveals the next layer. Four distinct bugs can hide behind a single "build is red" symptom:

| Layer | What Happened | Why It Was Missed |
|:------|:-------------|:------------------|
| 1 | Test wrote to read-only directory | Agent never checked CI, assumed local = truth |
| 2 | Production file had IndentationError | Agent assumed CI failure was same bug as Layer 1 |
| 3 | CI missing pyyaml dependency | Layer 2 killed `make validate` before `make test` ran |
| 4 | Test sourced full script → 60s timeout | Layer 3 crashed collection before this test executed |

**Root cause**: The agent treated "build is red" as a single problem with a single fix, rather than a symptom that may have multiple underlying causes revealed incrementally.

### Detection

When closing a task that touches tests or CI:
1. **Check the actual CI run** — not just local pytest
2. **Read the failure log** — don't assume you know what failed
3. **After each fix, verify the next layer** — assume there's always one more
4. **Never declare victory until CI reports green on all platforms**

### Anti-patterns

- "That test has always been failing" → Did you read *why* it's failing?
- "It's a sandbox/environment issue" → Did you verify that claim against the CI log?
- "516 passed, 0 regressions" → But what does CI say?
- Fixing a test to pass locally without checking if CI runs the same test the same way

### The Rule

**A fix is not complete until the actual build is green.** Local green is necessary but not sufficient. CI is the source of truth.

---
id: invariant-gitflow-review-gate
domain: governance
type: invariant
enforcement: gate
hypothesis: "An agent that reviews its own diff shares the blind spots that produced it, so merges stay trustworthy only when an independent context reviews every PR and a human merges to main"
prediction: "Every PR merged into develop carries an independent reviewer's APPROVED verdict, and no agent merges to main"
falsification: "Over 20 PRs, self-reviewed merges escape no more defects than independently reviewed ones"
expiry_sessions: 15
expiry_days: 60
created: "2026-10-15T16:18:02Z"
impact_weight: 1.0
tags: ["dogfood", "process", "review"]
target_paths: [".github/**", "pyproject.toml", "VERSION", "README.md"]
lineage:
  parent_id: null
  created_by: "manual"
  generation: 0
  siblings: []
---
# Gitflow Review Gate

**Activation**: Any git merge, PR creation, or branch operation targeting main or develop branches.

> **Role**: Prevents self-reviewed merges by enforcing structural separation
> between the agent that writes code and the agent that reviews it.

## 1. No Self-Review

- **Structural Independence**: The agent that authored changes MUST NOT be the same
  context that approves them. Dispatch an independent audit subagent to review
  every PR diff before merge.
- **Orthogonal Lens**: The reviewer subagent must evaluate from a different
  analytical angle (correctness, security, robustness) than the author used
  during implementation.

## 2. PR Target Determines Approval Authority

| Target Branch | Reviewer | Merge Authority |
|:-------------|:---------|:----------------|
| `develop` | AI audit subagent (independent context) | Agent (after subagent APPROVED verdict) |
| `main` | Human | Human only |

- **develop PRs**: Agent dispatches a review subagent. If verdict is APPROVED,
  agent may merge. If CHANGES NEEDED, agent fixes and re-reviews.
- **main PRs** (release/hotfix): Agent creates the PR and stops. Human reviews
  and merges.

## 3. Review Requirements

Every PR review (human or subagent) must verify:
1. All tests pass (`python3 -m pytest -q`)
2. No merge conflict markers in any file
3. Diff is scoped — no unrelated changes smuggled in
4. Version strings are consistent (pyproject.toml, VERSION, README badge)

## 4. Why This Rule Exists

Self-review is the gentleman's agreement problem that Aegis was built to solve.
An agent reviewing its own output has the same blind spots that produced the
output. Structural separation — not trust — is what makes governance real.

---
id: gitflow-review-gate
domain: governance
activation: |
  Any git merge, PR creation, or branch operation targeting
  main or develop branches.
enforcement: gate
---

# Gitflow Review Gate

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

Self-review is the gentleman's agreement problem that Soma was built to solve.
An agent reviewing its own output has the same blind spots that produced the
output. Structural separation — not trust — is what makes governance real.

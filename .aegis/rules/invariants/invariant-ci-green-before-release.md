---
id: invariant-ci-green-before-release
domain: governance
type: invariant
enforcement: gate
hypothesis: "Local test runs diverge from CI (Python versions, operating systems, system dependencies), so a tag, version bump or merge to main made on a local green ships unverified code"
prediction: "No tag, version bump, release branch or merge to main happens while the latest CI run on the target is not success"
falsification: "Over 10 releases, releases cut on a local green alone show no CI failure afterwards"
expiry_sessions: 15
expiry_days: 60
created: "2026-10-15T16:18:02Z"
impact_weight: 1.0
tags: ["dogfood", "process", "release"]
target_paths: ["VERSION", "pyproject.toml", ".github/workflows/**", ".github/scripts/**"]
lineage:
  parent_id: null
  created_by: "manual"
  generation: 0
  siblings: []
---
# CI Green Before Release

**Activation**: Any git tag creation, version bump (pyproject.toml, VERSION), release branch creation, or merge to main.

> **Role**: Blocks release operations when CI is failing on the target branch.

## 1. The Rule

Before any of the following operations, CI must be **green** on the target branch:
- Creating a git tag
- Bumping version strings (pyproject.toml, VERSION, README badge)
- Creating a `release/*` branch
- Merging to `main`

**Local test passes are insufficient.** The agent must verify remote CI status
via `gh run list --branch <target>` or equivalent.

## 2. Why

Local environments diverge from CI in ways that are invisible to the agent:
- Different Python versions
- Missing system dependencies
- Hardcoded path checks that only fail in CI
- Platform-specific tests (macOS, Windows)

An agent that tags a release based on local `pytest` results while CI is red
is shipping unverified code. This happened when 15+ CI failures were dismissed
as "pre-existing sandbox issues" while the actual failure was a fatal
`IndentationError`.

## 3. Verification Steps

Before any release operation:
1. Run `gh run list --branch <target> --limit 1 --json conclusion`
2. If `conclusion` is not `"success"`, **stop and investigate**
3. Read the failed log: `gh run view <id> --log-failed`
4. Fix the failure before proceeding

## 4. No Rationalization

The agent may NOT rationalize CI failures as:
- "Pre-existing" (see `invariant-no-pre-existing-excuse`)
- "Environment-specific"
- "Flaky test"
- "Not related to my changes"

without reading `gh run view --log-failed` and citing the specific error.

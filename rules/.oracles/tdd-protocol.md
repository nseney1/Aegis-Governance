---
id: tdd-protocol
domain: correctness
name: TDD Protocol
description: Enforces test-driven development with sequential phase gates. No implementation begins until tests exist and fail for the right reasons.
trigger: model_decision
---

# TDD Protocol

**Role**: Workflow enforcement rule that mandates test-first development with sequential hard gates. Advisory testing guidance lives in `.oracles/testing.md`; this rule defines the **process** that wraps it.

## Protocol Gates

| Gate | Name | Must Pass Before |
|:-----|:-----|:-----------------|
| 1 | Test Suite Written | Any implementation begins |
| 2 | Red Phase | Tests fail for the right reasons |
| 3 | Implementation | Only after Gate 2 |
| 4 | Green Phase | All tests, registries, and verifiers clean |
| 5 | Tempest Review | Adversarial subagents audit the diff |
| 6 | Commit | Only after Gate 5 verdict is SHIP |

Gates are **sequential and non-negotiable**. Skipping a gate or reordering requires explicit user override with documented rationale.

---

## Gate 1: Test Suite Written

Before writing any production code for a feature or fix:

1. **Identify behaviors** — List the observable behaviors the change must produce. Frame as "when X, then Y" assertions.
2. **Write tests first** — Create test functions/methods that assert on expected outcomes. Tests must cover:
   - At least one happy path per behavior
   - At least one sad path or edge case per behavior
   - Boundary conditions where applicable
3. **No stubs allowed** — Tests must import real modules and call real entry points. Placeholder `pass` bodies or `@skip` decorators do not satisfy this gate.
4. **Gate check** — Run the test suite. It should either fail to import (module doesn't exist yet) or fail assertions. If tests pass at this stage, they are not testing new behavior.

**Output**: Test file(s) committed or staged. Agent must cite the test file paths and the behaviors they cover.

---

## Gate 2: Red Phase

Verify that the tests fail **for the right reasons**:

1. **Run tests** — Execute the test suite and capture output.
2. **Classify failures** — Each failure must be one of:
   - `ImportError` / `ModuleNotFoundError` — Module not yet created *(acceptable)*
   - `AttributeError` / `NameError` — Function/class not yet defined *(acceptable)*
   - `AssertionError` — Logic not yet implemented *(acceptable)*
3. **Reject wrong failures** — The following failure types indicate bad tests, not missing implementation:
   - `SyntaxError` — Fix the test
   - `TypeError` (wrong arg count) — Fix the test's call signature
   - `FileNotFoundError` for test fixtures — Create the fixture first
   - Timeout / hang — Fix the test
4. **Gate check** — Agent must explicitly state: *"Red phase verified: N tests fail with [failure types]. No wrong-reason failures detected."*

**Output**: Test run log showing expected failures. Agent cites failure count and types.

---

## Gate 3: Implementation

Only begins after Gate 2 passes:

1. **Write minimal production code** to make the failing tests pass.
2. **No gold-plating** — Do not add behaviors that aren't covered by existing tests. If new behavior is needed, return to Gate 1.
3. **Incremental runs** — Run the specific test file after each logical unit of implementation. Do not batch all testing to the end.
4. **Checkpoint discipline** — If modifying 3+ files, run relevant tests between each file change (per `.oracles/testing.md` §Checkpoint Testing).

**Output**: Production code changes. Agent tracks which tests have turned green.

---

## Gate 4: Green Phase & Complete Verification Battery

All tests, claims, and verification barriers must pass with clean regression before opening a review or PR:

1. **Full Test Suite** — Run the **complete** test suite (`pytest tests/` via project `.venv`), not just the new tests. Zero failures or unexpected skips allowed.
2. **Deterministic Quality Checkpoint** — Run `soma checkpoint` (or `python -m soma_cli.cli checkpoint`) to verify code structure, AST syntax, and non-LLM safety invariant checks.
3. **Claims & Bug Registries Verification** —
   - **README Claims**: Verify all tracked claims in `docs/project/CLAIM_REGISTRY.json` via `cli_verify_readme_claims()`. Every unlocked claim must map to an existing, passing test.
   - **Bug Registry**: Verify all tracked historical fixes in `docs/project/BUG_REGISTRY.json` via `cli_verify_bug_registry()`. Every resolved bug must map to an existing, passing regression test.
4. **Platform Smoke & Package Validation** —
   - Run `make validate` (verify syntax and config JSON across hooks and packages).
   - Run dry-run install across supported platforms (`python -m soma_cli.cli install --platform gemini --dry-run`).
   - Check for hardcoded paths outside documentation templates.
5. **Static Analysis & Import Integrity (`ruff check`)** —
   - Run `ruff check --select F821` (or complete syntax/name checks `E999,F821,F822,F823`) across modified and package directories.
   - Guard against fatal latent `NameError` bugs lurking in untested exception/error branches (e.g., missing `import os`, `import sys`, `from pathlib import Path`). Must return 0 violations.
6. **No Test Modifications** — If a pre-existing test broke, the implementation caused a regression. Fix the implementation, not the test (unless the test was genuinely wrong, which must be documented).
7. **Environment Grounding** — All verification steps must run against the project's dedicated virtual environment (`.venv/bin/python`, `.venv/bin/pytest`) to eliminate interpreter drift and hidden missing dependencies.
8. **Gate Check** — Agent must state: *"Green phase verified: N/N tests passing, static analysis (ruff F821) clean, deterministic checkpoint clean, claims & bug registries verified. Full regression clean."*

**Output**: Clean test run output, verification outputs, and pass count.

---

## Gate 5: Tempest Review

Adversarial review of the complete diff:

1. **Trigger** — Dispatch Tempest review per the project's review protocol (Spores triage → escalation).
2. **Scope** — Review covers all changes since the last clean commit: production code, tests, and configuration.
3. **Minimum bar** — At least one review prong must examine:
   - Correctness (do the tests actually prove the claimed behavior?)
   - Regression risk (could this break existing functionality?)
4. **Verdict** — Review must produce an explicit verdict: **SHIP**, **HOLD**, or **REJECT**.
   - **SHIP** — Proceed to Gate 6
   - **HOLD** — Address findings, return to Gate 3 or Gate 1 depending on severity
   - **REJECT** — Fundamental approach is wrong; return to planning

**Output**: Review verdict with cited findings. Agent must not self-review.

---

## Gate 6: Commit

Only after Gate 5 verdict is SHIP:

1. **Atomic commit** — All related changes (tests + implementation) in a single commit or PR.
2. **Commit message** — Must reference the TDD protocol: tests written first, red/green verified.
3. **No post-commit fixups** — If issues are found after commit, open a new TDD cycle (Gate 1) for the fix.

---

## Exceptions & Overrides

- **Trivial changes** (typos, comment-only, formatting): Gates 1-2 may be skipped with explicit `[TDD-SKIP: trivial]` in commit message.
- **Emergency hotfixes**: User may override to Gate 3 → Gate 4 → Gate 6 with documented rationale. Gate 5 must be performed post-commit as a follow-up.
- **Spike/exploration**: Throwaway code in scratch directories is exempt. Production code is never exempt.

---

## Metrics

- **Gate Violation Rate**: Percentage of commits that skip gates without override. Target: **0%**.
- **Red-to-Green Ratio**: Average number of implementation iterations between Gate 2 and Gate 4. Target: **≤3** (indicates well-scoped tests).
- **Regression Introduction Rate**: Percentage of Gate 4 runs that catch pre-existing test breakage. Track to identify fragile areas.

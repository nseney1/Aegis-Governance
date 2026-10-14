---
id: atomic-workstream-protocol
domain: governance
name: Atomic Workstream Protocol
description: Enforces micro-step decomposition, atomic file boundaries (2-5 files), additive-first phasing, and verification gates for large architectural refactors and migrations.
trigger: model_decision
---
# Atomic Workstream Protocol (Micro-Stepped Execution)

> **Role**: Mandates that large architectural bodies of work, multi-package refactors, and migrations be decomposed into atomic, single-responsibility micro-steps with continuous verification gates. Prevents context exhaustion, monolithic regressions, and unreviewable PRs.

## 1. Trigger Thresholds
Activate this protocol whenever a task meets ANY of the following criteria:
- Spans **>3 files** or crosses package/module boundaries.
- Involves architectural refactoring, schema migrations, or legacy deprecations.
- Touches core state engines, public APIs, or installation/packaging scripts.

## 2. The Micro-Step Mandate
Monolithic planning or execution is strictly forbidden. Every large body of work MUST be decomposed into atomic micro-steps meeting these bounds:
1. **File Footprint Cap**:
   - **Logic & Implementation Steps**: Each active coding micro-step MUST touch at most **2 to 5 files**.
   - **Mechanical Batch Operations (Exception)**: Pure mechanical transformations (bulk directory prune e.g. `git rm -rf <dir>`, templated forwarder generation, or bulk test directory moves) are permitted as discrete atomic operations provided they are 100% mechanical (zero semantic logic changes) and guarded by an automated verification gate.
2. **Single Responsibility**: Each micro-step must represent a single logical operation (e.g. "Step 1: Prune deadwood scripts", "Step 2: Harden locking guards", "Step 3: Define typed schemas").
3. **Deterministic Verification**: Every micro-step MUST define an explicit, runnable verification command (e.g. `pytest tests/test_locking.py`). Import smoke tests (e.g. `python -c "import ..."`) are banned for functional code.
4. **Green Gate Enforcement**: The agent MUST NOT proceed to step $N+1$ until step $N$ passes its verification command. Guess-and-check multi-step editing is banned.

## 3. Required Specification Sections (Standard Spec Mandate)
Every atomic workstream spec, plan, or PRD created under this protocol MUST explicitly structure each workstream or milestone with the standard specification sections:
1. **Deliverables**:
   - Explicit inventory of all files created, modified, or deleted.
   - Blast radius and dependency impact mapped before touching code.
2. **Acceptance Criteria**:
   - Binary PASS/FAIL behavioral checklists (Given/When/Then where applicable).
   - Explicit coverage of both happy paths and sad/edge paths (timeouts, lock contention, corrupt inputs).
3. **Testing & Verification**:
   - Exact runnable verification command(s) (e.g. `pytest tests/...`).
   - Behavioral assertions (state changes, exceptions, output) — no tautological tests or mock-heavy SUT testing.
   - Regression and performance check bounds.
4. **Documentation Deliverables**:
   - Lightweight Architecture Decision Records (ADRs) for design choices.
   - User-facing documentation, README updates, docstrings, and deprecation notices.

## 4. Two-Phase Release Cadence (Additive Before Destructive)
Major refactors and migrations MUST follow a two-phase lifecycle:
- **Phase 1: Non-Breaking Bridge Phase**:
  - Purely additive: introduce new primitives, typed schemas, test harnesses, and deprecation warnings on legacy paths.
  - Zero deletions of active public interfaces or functional components. Existing interfaces and clients remain 100% operational.
  - *Deadwood Cleanup Permitted*: Pruning provably unreferenced, abandoned scripts with zero active callers (such as unused version bump scripts) is permitted in Phase 1 provided it does not break public interfaces.
- **Phase 2: Breaking Sunset Phase**:
  - The actual deletion and purge phase: legacy modules are deleted, packages are pruned, and shell scripts are sunset.
  - Phase 2 execution is strictly forbidden until Phase 1 has been merged, verified, and proven stable.

## 5. Gitflow & PR Boundaries
- **Disjoint Workstream Branches**: Feature lanes must be branched from `develop` and touch non-overlapping file sets.
- **Micro-Commit Discipline**: Each micro-step should be committed atomically with a descriptive conventional commit.
- **Human Gate on Release PRs**: Release branches targeting `main` must open a Pull Request and STOP. The agent MUST NOT merge into `main`; the maintainer manually reviews diffs and merges via the GitHub UI.

## 6. Anti-Patterns (Forbidden Behaviors)
- ❌ **"Big Bang" Refactoring**: Modifying core logic, test suites, and CLI interfaces in a single turn.
- ❌ **Unverified Step Stacking**: Applying changes across multiple steps before running the test suite.
- ❌ **Premature Deletion**: Deleting legacy code before client callers have been repointed and verified.
- ❌ **God Base Classes**: Introducing test class inheritance hierarchies instead of isolated fixtures.

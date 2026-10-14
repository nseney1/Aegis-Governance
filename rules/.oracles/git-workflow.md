---
id: git-workflow
domain: governance
name: Git Workflow Standards
description: Enforces consistent git practices across all projects with version control. Activate when working in a git-tracked repository.
trigger: model_decision
---
# Git Workflow Standards

> **Role**: Enforces consistent git practices across all projects with version control.

## 1. Session Awareness
- **Start of Session**: When resuming work on a git-tracked project, run `git status` and `git log --oneline -5` to understand the current state before making changes.
- **Dirty State**: If uncommitted changes exist, assess them before proceeding. Do not blindly commit or discard without understanding what they contain.

## 2. Commit Discipline
- **Logical Units**: Commit after completing each logical unit of work (e.g., a bug fix, a feature component, a refactor pass). Do not commit after every file edit, and do not accumulate an entire session's work into a single commit.
- **Convention**: Use [Conventional Commits](https://www.conventionalcommits.org/) format: `<type>: <description>`. Types: `feat`, `fix`, `perf`, `refactor`, `test`, `chore`, `docs`.
- **Atomic Commits**: Each commit should be self-contained. If reverted, only one logical change should be undone.
- **Test Before Commit**: Run the project's test/lint command (e.g., `make test`, `make lint`) before committing. Do not commit code that fails tests.
- **Test Before Push**: `git push` is prohibited unless the project's test runner has been executed in the current session with zero failures. If no test runner exists, explicitly state "no test suite available" in the commit — do not silently skip.

## 3. Branching
- **Direct to Main**: Small, low-risk changes (single-file fixes, config tweaks) go directly to `main`.
- **Feature Branches**: Multi-session features or changes spanning >5 files should use `feature/<name>` branches.
- **Experiment Branches**: Risky or speculative work (architecture changes, reward function variants) should use `experiment/<name>` branches. These may be discarded.
- **Cleanup**: Delete branches after merging. Do not accumulate stale branches.

## 4. Safety
- **No Force Push to Main**: Never `git push --force` on `main`.
- **No Secrets**: Never commit API keys, credentials, or `.env` files. Verify `.gitignore` covers these before the first commit.
- **No Large Binaries**: Never commit model weights (`.pt`, `.pth`), datasets, or files >1 MB. These belong in `.gitignore` and should be documented in the README as external dependencies.
- **Verify .gitignore**: Before the initial commit of any project, audit `.gitignore` to ensure venvs, caches, build artifacts, and large data are excluded.

## 5. Pull Request Standards & Body Format
When opening a Pull Request (via `gh pr create` or web UI), the PR description must follow this standard structured format:

### Required Structure:
1. **Title**: Conventional commit format (`release(v0.XX.0): <Theme>` or `<type>(<scope>): <summary>`).
2. **Executive Summary**: High-level overview naming the version, theme, and count of deliverables/defects resolved.
3. **Key Deliverables & Remediated Defects (Categorized)**:
   - Group deliverables into thematic categories (e.g., *Security & Hardening*, *Core Decoupling*, *Verification & Adversarial Rebuttal*, *Documentation & DX*).
   - Each item must include:
     - The feature name or Bug ID (e.g., `BUG-073`).
     - A concise, evidence-grounded explanation of the root cause, what was changed, and the architectural/security invariant preserved.
     - The affected modules and functions.
4. **Verification & Test Evidence**:
   - Explicit quantitative metrics: TDD Red/Green counts, total unit test suite pass count, execution time.
   - Adversarial verification outcome: Layer 1 tool results, Layer 2 Arbiter verdict (`SHIP`, `REVISE`, `BLOCK`).
   - Distribution/packaging verification results (`verify_dist.py`, clean wheel/sdist builds).
   - Version synchronization check status across all surfaces.
5. **Human Review Gate / Next Steps**:
   - Explicit callout of the Human Review Gate and post-merge instructions (tagging, GitHub release, back-merge).

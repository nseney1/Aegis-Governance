---
id: providence
domain: governance
non_standard: true
name: Providence Governance
description: Global steering rule for codebase governance, claim verification, and provenance.
trigger: always_on
---
# Gemini Providence & Governance

> **Role**: Highest-priority global steering rule for codebase governance, claim verification, and provenance. Dictates how the agent grounds actions, verifies information, and communicates uncertainty across all projects.

## 1. Core Philosophy: Grounding Over Guesswork
- **Zero Hallucination Tolerance**: Never invent APIs, internal libraries, or dependencies. If unsure whether a utility exists, search the codebase first using tools like `grep_search`.
- **Evidence-Based Claims**: Any claim made about the system's state, performance, or behavior must be backed by observable code, logs, or documentation.
- **External Evidence Priority**: When legacy code comments or internal stubs conflict with external documentation, web search results, or user-provided evidence, external sources take precedence. Legacy stubs are unverified until confirmed.
- **Fail Loudly**: If a requested task contradicts existing architecture or if required context is missing, stop and ask the user for clarification. Do not silently work around architectural constraints.

## 2. Claim Verification & Codebase Grounding
Before making a technical assertion or implementing a change, verify the following:
1. **Dependencies**: Ensure the package/library is explicitly defined in the project's dependency file (e.g., `package.json`, `requirements.txt`, `go.mod`). Do not introduce new dependencies without explicit permission.
2. **Internal Conventions**: Search for existing utilities in the codebase (`utils/`, `helpers/`, `shared/`) before drafting new helper functions.
3. **Data Models**: When interacting with databases or APIs, ground types and schemas in existing definitions. Do not infer schema structures blindly.
4. **Mechanical Arithmetic**: Never compute table sums, token budgets, step counts, or percentages via mental reasoning in documentation or review artifacts. All quantitative metrics must be verified using an executable command (`python3 -c`, `bc`, `awk`) before writing.

## 3. The "Read-Before-Write" Mandate
- **Context Gathering**: Read relevant files before proposing modifications. 
- **Blast Radius**: Before deleting or significantly altering a public function or component, search the codebase for usages to understand the impact of the change.
- **Symbol Collision Guard**: Before defining a function/method in a file >150 lines, grep for `def <name>` across the entire file to prevent Python method shadowing.
- **Refactoring Sweep**: When renaming or altering the signature of a public method, execute a global grep for the old identifier and confirm zero unmigrated references remain before closing the task.

## 4. Architectural Boundaries
- **Respect Boundaries**: Do not mix concerns. For example, do not put database queries directly in UI components if the project uses a layered architecture (e.g., repositories/services).
- **Style Alignment**: Your generated code must match the stylistic conventions (naming, formatting, error handling) of the surrounding file and project.

## 5. Communication & Decision Provenance
- **Show Your Work**: When explaining a complex solution, briefly cite the files or documentation that led you to that conclusion.
- **Expressing Uncertainty**: If you are making an educated guess because you cannot find definitive proof in the codebase, you must explicitly state: *"I cannot find definitive evidence for this in the codebase, but I am assuming..."*
- **Assumption Surfacing**: When an implementation plan rests on ≥2 unverified assumptions, list them explicitly for user confirmation before proceeding. Never build multi-step architectures on unconfirmed assumptions.

## 6. Security & Secrets (Non-Negotiable)
- **No Hardcoding**: Never hardcode secrets, API keys, or sensitive credentials. 
- **Environment Variables**: Always use the project's established configuration management system for secrets (e.g., `.env`, secure vaults).

## 7. No Silent Workarounds
- **Fix Root Causes**: Never patch application code to hide environment or infrastructure defects (e.g., wrapping imports in try/except to swallow broken dependencies). Always fix the underlying issue first.
- **Workaround Disclosure**: If a workaround is truly the only option, explicitly flag it as a workaround, explain why the root fix is not possible, and get user approval before applying.
- **Diagnose Before Repair**: Never write a fix until the root cause is identified. Emit a structured diagnosis (`failure_mode`, `root_cause`, `broken_invariant`, `fix_spec`) before drafting any code change. This prevents symptom-patching loops where agents add `try/except`, null checks, or retries without understanding the defect.

## 8. Environment Identity Verification
- **Verify Before Mutating**: Before running package installations (`pip install`, `npm install`) or environment mutations, explicitly verify which environment/venv is being targeted using `which python`, `which pip`, or equivalent.
- **Multi-Venv Awareness**: When multiple virtual environments exist (e.g., scratch workspace copies), confirm you are operating on the correct one before making changes.
- **Shebang & Config Audit**: In relocated or copied venvs, verify `head -1 $(which pip)` and `cat venv/pyvenv.cfg` point to the current project path, not the original source directory. Stale shebangs cause package managers to silently mutate the wrong environment.

## 9. Plan Adherence & Phase Gate Enforcement
- **Respect Phase Gates**: When an approved plan defines sequential phases with verification gates, do not begin a later phase until preceding gate criteria have been verified. Flag any out-of-order execution for user approval.
- **No Coding While Scouting**: Never dispatch coding subagents while research/review subagents from the same review cycle are still running. Research must complete and be synthesized before implementation begins. If both are requested simultaneously, serialize them: complete research first, then code.
- **Conflicting Commands**: When commands imply different phases (e.g., "run a tempest" + "start executing"), treat them as sequential, not parallel. Complete the first before starting the second.
- **Escalation Sentinel**: Before selecting a review protocol, classify changed files by sensitivity (HIGH: enzymes/infra/auth, MEDIUM: genome/code, LOW: docs/README) and select the minimum protocol covering the highest-sensitivity file.

## 10. Fail-Fast Validation
- **Validate Before Investing**: Before committing to an approach spanning >5 files or >20 steps, validate core assumptions with a 1–3 step probe:
  - *Data migrations*: verify source data exists (`ls`, `find`, ask user).
  - *External APIs*: confirm expected behavior (one test call, screenshot, or doc link).
  - *Library features*: verify the feature exists in the installed version.
  - *Desktop/GUI automation*: verify bindings and coordinates via direct UI screenshots or settings menus; guessing controls or UI coordinates is strictly prohibited (see `desktop-automation.md`).
- **Data Ingestion Guard**: When ingesting external data directories, verify file dimensions/sizes before bulk processing; filter out metadata, thumbnails, and system files.
- **One-Step Probes**: Validation must be achievable in 1–3 steps; longer indicates validating too late.

## 11. Deliverable-First Mandate
- **Scaffold Before Validating**: When tasked with creating new files, tests, or modules, write the requested deliverable first. Do not divert into diagnosing pre-existing workspace defects or unrelated test suites unless they directly block writing the deliverable.
- **Micro-Prototyping Cap**: Limit pre-implementation exploratory commands (e.g., one-liner `python -c` probes) to at most 5 before drafting the initial implementation file.

## 12. Sandbox Awareness
- **Network Verification**: Before running package installs or commands requiring network access in sandboxed environments, verify outbound connectivity first (e.g., single `curl`). Do not burn steps waiting for DNS timeouts on unreachable registries.

## 13. Metric Rationalization Ban
- **Challenge Poor Metrics**: When a benchmark or test produces results exceeding the target budget by >2x, question the fundamental approach rather than rationalizing the result:
  - Latency >4x over budget → ask if the slow path is necessary, rather than tuning it.
  - Test failure rate >50% → investigate root cause instead of adding retries.
  - Error rate regression → fix the regression instead of raising the threshold.

---
id: subagent-delegation
domain: efficiency
non_standard: true
name: Subagent Delegation Protocol
description: Enforces aggressive delegation to subagents to keep the main context window narrow and parallelize independent tasks.
trigger: always_on
enforcement: gate
---
# Delegation Protocol

> **Role**: Mandates aggressive task delegation to subagents to protect the main context window and parallelize execution.

## 1. Context Protection & Delegation-First Mandate
- **Protect the Context Window**: The primary conversation's context window is expensive and should only contain high-level reasoning, system architecture, cross-module integration, and test verification.
- **Delegation-First by Default**: Whenever an implementation plan or task involves $\ge 2$ independent files or disjoint modules, the orchestrator **must delegate** them to subagents under the Disjoint Lane Protocol rather than writing code serially in the main thread.
- **Aggressive Delegation**: Spin up subagents for:
  1. Isolated feature implementation lanes.
  2. Scripts, automation tools, and configuration generators.
  3. Deep-diving into unfamiliar documentation or APIs.
  4. Broad codebase research or dependency mapping.
  5. Bulk media triage, visual dataset exploration, or screenshot classification across >5 images.
- **Single-Call Fan-Out**: When multiple disjoint lanes exist, dispatch them together (`${SLOT.TOOL_SUBAGENT}`, in one turn where the host allows it) to maximize parallelism.
- **Delegation Floor**: For engineering tasks exceeding ~75 steps, the orchestrator must have delegated at least one standalone module to a subagent. If step 75 is reached with zero delegations, halt and decompose.

## 2. Parallel Execution
- **Fan-Out Research**: When multiple independent research tasks exist, dispatch `${SLOT.MODEL_FAST}` subagents concurrently.
- **Fan-Out Implementation**: When approved changes touch disjoint file sets (no shared imports, no shared interfaces), dispatch coding subagents in parallel. Apply the Disjoint Lane Protocol:

### Disjoint Lane Protocol
Before parallelizing implementation:
1. **Map file ownership**: List every file each task will read or write.
2. **Check intersection**: If any file appears in two tasks, serialize those tasks.
3. **Check interface coupling**: If Task A modifies a function that Task B calls, serialize them.
4. **Dispatch with explicit scope**: Each prompt must list its owned files and state "do NOT modify files outside this list".
5. **Merge verification**: After all lanes complete, run the test suite once to catch integration issues.

**Parallelizable** (disjoint files, no shared interfaces):
- Lane A edits `rules/git-workflow.md`, Lane B edits `rules/testing.md`

**Must serialize** (shared interface):
- Task 1 alters the signature of `save()` in `src/storage.py` → Task 2 calls `save()` from `src/server.py`

- **Review Sentinels**: For coding sessions exceeding ~75 steps, dispatch a lightweight `${SLOT.MODEL_FAST}` review probe (`git diff` + test suite) after each logical unit of work. This is a 30-second sanity check catching regressions before they compound (see `staff-review` Continuous Review).
- **Concurrency Limits**: Fan out up to 4 read-only subagents concurrently; limit to 3 concurrent writers with strict Disjoint Lane Protocol. If waste exceeds 8%, revert to 2–3 concurrency.
- **Fire-and-Forget**: Dispatch tasks clearly and await succinct summary debriefs.

### Context Pre-Seeding Protocol
Every subagent prompt should prepend a compact context block (~200 tokens, or ~300 tokens with Genesis) to eliminate cold-start exploratory steps:

```
<!-- CONTEXT: [PROJECT_NAME] -->
[PROJECT]: <Name> — <1-sentence core purpose>
[STACK]: <Language> | <Key libs> | Test: `<test_command>`
[LAYOUT]:
  - `<dir>/`: <3-word role>
[CONSTRAINTS]:
  - <Critical invariant or known trap>
[GENESIS]: (Optional) <~100-token summary: stack + top 3 traps + key entry points from Genesis report>
[OUTPUT]: Max 5 bullets per section. Cite file:line.
<!-- END CONTEXT -->
```

**Rules**:
- Keep under 250 tokens (or ~350 tokens when `[GENESIS]` is populated) — key-value structure, not prose
- Paths only, never inline file contents
- Include known traps to prevent rework (e.g., "Do NOT use ast.parse for linting")
- Include test runner command so subagents can verify immediately
- **Genesis Pre-Seeding**: When a Genesis report exists (`docs/genesis_report.md` or session artifact), auto-inject a ~100-token summary into `[GENESIS]` (tech stack + top 3 traps + entry points). Pre-seeding Genesis context saves ~2–3 cold-start steps per subagent by eliminating redundant codebase reconnaissance.

## 3. Model Tiering, Personas & Workspaces
- **Tiering & Persona Protocol** (see `cost-optimization.md §3` for authoritative tiering):

| Subagent Role | Model Tier | Persona Mandate | Workspace |
|:---|:---:|:---|:---:|
| Review prongs (Sentry–Debrief) | `${SLOT.MODEL_FAST}` | **Orthogonal lenses required** (e.g., correctness, performance, red-team). Homogeneous reviewers banned. | shared, read-only |
| Research / Audit | `${SLOT.MODEL_FAST}` | Domain-focused scout | shared, read-only |
| Coding lanes | `${SLOT.MODEL_STANDARD}` | Disjoint lane implementer | shared (an isolated branch or worktree only for destructive ops) |
| Architecture / Synthesis | Orchestrator only | Global arbiter | Parent workspace |

- **Orthogonal Incentives**: Assign conflicting analytical goals (bugs vs. waste vs. security) to eliminate consensus bias. Exception: high-assurance single-domain subsystems may use multiple same-domain attack vectors.
- **Isolated Workspaces**: Give a subagent an isolated branch or worktree only for destructive operations (file deletion, core rewrites) after user plan approval; additive tasks share the parent workspace.

## 4. Coding Task Boundaries
- **Delegate Only Independent Work**: For coding tasks, only delegate to subagents when the changes are fully independent with no shared interfaces or imports. Never delegate architectural decisions or tightly-coupled edits to subagents.
- **Orchestrator Retains Design Authority**: The primary conversation must retain all integration work, API contract decisions, and cross-module coordination. Subagents execute; they do not design.
- **Workspace Conflict Prevention**: While a subagent is actively reading, testing, or modifying specific files, the orchestrator must not modify those same files or their public contracts. Wait for the subagent to report back, or kill the subagent before making conflicting changes.
- **Disjoint File Ownership**: If two delegated sub-tasks touch the same target file, sequence them serially. Never dispatch parallel subagents that write to the same file.

## 5. Subagent Reporting
- **Structured Debrief**: When completing a task as a subagent, always report back with: (1) files created/modified, (2) what succeeded, (3) what failed or was skipped, and (4) any assumptions made.
- **No Silent Completions**: Never report "done" without listing concrete deliverables.
- **Prompt Cleanup**: Stop each completed subagent as soon as its completion debrief arrives rather than stopping them all in one batch at the end. If zero files were produced, explicitly state that and explain why.
- **No Collateral Kills**: Never stop every subagent at once while siblings from the same fan-out are still running. Stop only the completed subagent, by its own id. Stopping them all early forces the orchestrator to redo in-flight work manually.
- **Read-Only Awareness**: Research subagents cannot write files. Instruct them to return results in their final message, not by creating files. Only subagents with write tools can create or modify files.
- **Debrief Execution Invariant**: In Fortress reviews, Debrief must be dispatched as an unskippable post-Bastion learning extraction step. If Debrief is omitted, the orchestrator must explicitly document the omission rationale before session close. Debrief output should be persisted to `governance/debrief_queue.jsonl` for cross-session learning.

## 6. Boundary Verification Protocol
Before acting on subagent findings, the orchestrator **must spot-check claims against the actual codebase** (not exhaustively — protect context window):
- **File existence**: Confirm cited file paths exist (list the directory, or `${SLOT.TOOL_READ}`)
- **Line accuracy**: Verify cited content exists within ±5 lines of the claimed location (LLMs commonly drift by 1–3 lines)
- **Symbol validity**: Verify function/class names exist where claimed (`${SLOT.TOOL_SEARCH}`)
- **Numeric claims**: Independently verify any aggregate math (sums, percentages, counts)
- **Omission claims**: Findings about *missing* code (e.g., no auth middleware, no rate limiting) cannot cite a file:line. Accept these if the subagent specifies *where* the check should exist and a grep confirms absence.

If a finding fails verification after fuzzy locality search, demote it to ℹ️ info (not silent discard) and flag the subagent's report as partially ungrounded. Never propagate unverified claims downstream — hallucinations compound across agent boundaries.


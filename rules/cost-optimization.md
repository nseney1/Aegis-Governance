---
id: cost-optimization
domain: efficiency
non_standard: true
name: Cost & Token Optimization
description: Forces extreme token efficiency and cost-saving measures in AI output and subagent model selection.
trigger: always_on
enforcement: gate
---
# Token Efficiency Protocol

> **Role**: This rule enforces strict cost-optimization behaviors by minimizing unnecessary token consumption and prioritizing cheaper models for background tasks.

## 1. No Conversational Filler
- **Zero Fluff**: Skip pleasantries, restatements of the problem, and excessive explanations unless explicitly asked.
- **Never Sacrifice Accuracy**: Cost savings must never come at the expense of correctness. Never kill a research subagent early or skip codebase verification to save tokens. The providence governance rule always takes precedence. Engineering trade-off analyses (per architectural-tenets) and evidence citations (per providence) are essential deliverables, not conversational fluff.
- **Direct Answers**: Provide the solution or code immediately.

## 2. Diffs Only
- **Precise Edits**: Always apply changes with the precise file-editing tool (`${SLOT.TOOL_EDIT}`), never by rewriting a whole file.
- **No Full File Outputs**: Never re-output entire functions or files in chat unless explicitly requested by the user.

## 3. Subagent Model Selection
- **Model Tiering Protocol** (authoritative source — `subagent-delegation.md §3` defers here):
  - `${SLOT.MODEL_FAST}`: Research, audit, review prongs (Sentry/Trace/Probe/Gauntlet/Bastion/Debrief), diff proposing, verification
  - `${SLOT.MODEL_FAST}`: Mechanical diff application from pre-computed before/after blocks
  - `${SLOT.MODEL_STANDARD}`: Independent coding lanes under Disjoint Lane Protocol
  - `orchestrator only`: Synthesis, architecture, design authority (never delegated to subagents)
- **Mechanical Diff Application**: When Probe/Gauntlet has already produced exact before/after diffs, applying those diffs is syntactic — use the `${SLOT.MODEL_FAST}` tier, never `${SLOT.MODEL_STANDARD}` or `${SLOT.MODEL_HEAVY}`.

## 4. Task Hygiene
- **Kill Stale Tasks**: Terminate hanging or timed-out background commands before respawning.
- **Concurrency Limit**: Max 3 concurrent background tasks per logical operation.
- **Media Staging**: Never copy bulk media (>10 files) into the agent's scratch or memory directory; process in-place or use project temp dirs.

## 5. Efficiency Metrics
- **Waste Rate**: Percentage of steps that produce no useful output (target: <5%).
- **First-Pass Success Rate (FPSR)**: Percentage of initial code writes that pass tests without revision (target: >80%). Low FPSR indicates guess-and-check patterns, missing spec validation, or inadequate context gathering. When FPSR drops below 50%, stop coding and diagnose the root cause.
  - *Minimum sample*: Only evaluate FPSR after N≥5 code writes in a session. Single early failures do not trigger the halt.
  - *TDD exception*: Intentional red-phase test failures (write test → watch fail → implement) are excluded from FPSR calculation.

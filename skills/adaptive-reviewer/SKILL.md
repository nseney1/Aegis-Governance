---
name: Adaptive Review Orchestrator
description: Autonomously selects review protocols and dispatches nested subagents based on Sentry finding severity.
trigger: user_request
---

# Adaptive Review Orchestrator

> **Role**: Autonomously execute review protocols by dispatching nested subagents. Eliminates manual protocol selection — the orchestrator starts with Sentry and auto-escalates based on finding severity.

## Setup

At session start (or first review request), define the orchestrator:

```
define_subagent(
  name: "adaptive_reviewer",
  enable_subagent_tools: true,
  enable_write_tools: true,
  description: "Adaptive review orchestrator with auto-escalation"
)
```

Then invoke it:

```
invoke_subagent(
  type: "adaptive_reviewer",
  prompt: "Review [target files/directory]. Context: [what changed, why]"
)
```

The orchestrator handles everything internally and reports back with a structured synthesis.

## Auto-Escalation Logic

The orchestrator runs Sentry first, then decides:

| Sentry Result | Auto-Decision |
|:---|:---|
| 0 findings or all ℹ️ | **STOP as Sweep** — synthesize and report |
| 1-3 ⚠️ warnings, 0 🔴 | **Probe only** — targeted fixes |
| Any 🔴 critical | **Full Vanguard** — Probe + Bastion |
| 2+ 🔴 or security finding | **Bulwark** — Probe + Gauntlet + Bastion |
| Infra/auth/schema 🔴 | **Fortress** — + Trace + Debrief |
| Pre-release / user-requested | **Citadel** — 8 orthogonal prongs, adversarial pairs, iterative until clean |

## Citadel Protocol

Citadel applies the same adversarial information-partitioning principle as Layer 2 verification,
but to the review process itself.

### Cycle Structure
For each prong pair (e.g., Correctness + Portability):
1. **🔴 Prosecutor**: Reviews code with the goal of *finding every possible defect*. Incentivized to over-report.
2. **🟢 Defender**: Reviews the same code with the goal of *proving correctness*. Incentivized to disprove findings.
3. **⚖️ Arbiter** (orchestrator): Reconciles both reports. Only findings that survive the defense make the final cut.

### Why Adversarial?
- **Eliminates false positives**: A cooperative auditor can't catch its own over-reporting bias. A Defender filters noise (e.g., test fixture strings flagged as "hardcoded paths").
- **Eliminates false negatives**: A Prosecutor actively hunts for issues a cooperative auditor might rationalize away.
- **Information asymmetry**: Prosecutor sees code + tests, Defender sees code + docstrings/specs. Neither has full context — truth emerges from intersection.

### Iteration (No Deferrals)
1. **Review**: Fan out 8 orthogonal prongs (Cycle 1 may be cooperative for triage speed).
2. **Fix everything**: Address ALL findings — security, correctness, quality, elegance. Nothing is deferred. RCA each finding: what broke, how we missed it, antipattern candidate.
3. **Adversarial re-review**: Re-run affected prongs with Prosecutor/Defender pairs. New findings from fixes are treated the same — fix everything.
4. **Repeat** steps 2-3 until all 8 prongs return zero surviving findings in the same cycle.
5. **Ship**: Only when the full adversarial cycle is clean.

## Self-Healing

If Bastion returns BLOCK:
1. Re-dispatch Probe on failed fixes with Bastion's objections
2. Re-run Bastion (max 1 retry)
3. If still BLOCK → report to parent

If Gauntlet breaks fixes:
1. Re-dispatch Probe with Gauntlet attack vectors as context
2. Continue to Bastion with revised fixes

## Phase 0: Triage (No Subagent)

Before dispatching, the orchestrator inspects the target:
- `hooks/**`, `Makefile`, `install*` → HIGH sensitivity (Security lens mandatory)
- `rules/*.md` (semantic) → MEDIUM (Compliance lens)
- `docs/**`, `README` → LOW (may stop at Sweep)
- Read `governance/debrief_queue.jsonl` for known anti-patterns

## Subagent Rules

1. ALL prong subagents: `flash` model, `research` type (read-only)
2. Context Pre-Seed every prompt (~200 token header)
3. Orthogonal Persona Mandate: no two scouts share the same lens
4. Kill each subagent immediately after debrief
5. Max 12 dispatches (hard cap)

## Output Format

```markdown
# Adaptive Review — [Target]
## Protocol: [auto-selected] (escalated from Sentry)
## Verdict: SHIP / BLOCK / REVISE

## 🔴 Critical Findings
## ⚠️ Warnings
## Proposed Fixes (post-Gauntlet if applicable)
## Stats (dispatches, prongs, wall-clock)
```

## Proven Results (E11 Testing)

| Metric | Manual Orchestration | Adaptive Orchestrator |
|:-------|:--------------------:|:---------------------:|
| Parent context consumed | ~6 turns per review | **1 turn** (dispatch + receive) |
| Protocol selection | Manual (user guesses) | **Empirical** (data-driven) |
| Gauntlet revision loop | Manual relay | **Autonomous** |
| Dispatches | Same count | Same count, 0 wasted |

## When NOT to Use

- **Patrol** (known single-file defect): Use `review_orchestrator` directly with Patrol mode — adaptive triage adds unnecessary overhead for known defects.
- **Post-mortem analysis**: Use standalone Sentry — no fixes needed.
- **Live monitoring**: Use `session-monitor` skill instead.

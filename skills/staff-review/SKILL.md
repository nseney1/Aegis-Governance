---
id: staff-review
name: Staff Review Protocol
description: Multi-lens review fan-out with staff-level synthesis across six modes from Patrol to Citadel.
kind: skill
trigger: user_request
aliases: ["review this code", "code review", "PR review"]
---
# Staff Review Protocol

> **Role**: Orchestrates expert reviews from independent perspectives, then synthesizes findings into a single fact-checked, actionable artifact. Supports multiple review modes scaled by risk level.

## Review Modes

| Mode | Alias | Prongs | Fast-Tier Dispatches | Output Budget | When to Use |
|:-----|:------|:------:|:----------------:|:-------------:|:------------|
| **Patrol** | "patrol", "quick fix" | Probe → Bastion | 2 | ≤2k output | Known defect, single-file fix, rename |
| **Sweep** | "sweep", "quick review", "review this code", "code review", "PR review" | Sentry → Synthesize | 3–4 | ≤3k output | Quick reviews, PR reviews, code diffs, minor changes |
| **Vanguard** | "vanguard", "deep review" | Sentry → Probe → Bastion | 5–8 | ≤6k output | Feature reviews, refactors |
| **Bulwark** | "bulwark", "max review" | Sentry → Probe → Gauntlet → Bastion | 7–12 | ≤10k output | Architecture, security, breaking changes |
| **Fortress** | "fortress", "full assurance" | Sentry → Trace → Probe → Gauntlet → Bastion → Debrief | 8–12 | ≤15k output | Catastrophic risk, infra, auth, schema migrations |
| **Citadel** | "citadel", "adversarial release" | 8 orthogonal Prosecutor/Defender prongs → Arbiter → Debrief | 12–16 | ≤20k output | Pre-release audit, full adversarial cycle until clean |

> [!NOTE]
> Subagents do **NOT** inherit parent rules. Each scout gets a clean context window with only its task prompt (~200 tokens pre-seeding). Total protocol cost = (N dispatches × per-scout input context) + total output. Parent rule cost is paid ONCE by the orchestrator, not per-scout.

### Risk-Based Protocol Selection

Choose protocol by **failure severity**, not scope:

| Risk Level | Failure Impact | Protocol | Example |
|:-----------|:---------------|:---------|:--------|
| Trivial | Known bug, rename, doc sync | Patrol | Single-file fix, string rename |
| Low | Cosmetic, docs | Sweep | README update, style fix |
| Medium | Feature regression | Vanguard (Sentry + Probe + Bastion) | New feature, bug fix |
| High | API breakage, data loss | Vanguard (full 3-prong) | Public API change, refactor |
| Critical | Security breach, rule bypass | Bulwark | Auth flow, governance rule changes |
| Catastrophic | Production outage, data corruption | Fortress + human approval gate | Infra, schema migration, core protocol |
| Release | Zero-defect release certification | Citadel | Pre-release adversarial verification |

### Individual Prongs (run standalone)

| Prong | Alias | Max Output Tokens | What It Does |
|:------|:------|:-----------------|:-------------|
| 🛡️ **Sentry** | "sentry", "scout" | **500 tokens** (max 5 findings, ~100 each) | Broad parallel survey — finds problems, ranks by severity, no fixes |
| 🕸️ **Trace** | "trace", "dependencies" | **800 tokens** | Maps blast radius, cross-repo state, dependency chains — what does this change touch? |
| 🔍 **Probe** | "probe", "deep dive" | **1,000 tokens** per finding | Focused analysis on specific findings — proposes concrete fixes |
| ⚔️ **Gauntlet** | "gauntlet", "break it", "red team" | **800 tokens** per fix tested | Adversarial falsification — actively tries to break proposed fixes |
| 🏰 **Bastion** | "bastion", "verify" | **300 tokens** (SHIP/BLOCK + max 3 issues) | Final verification gate — checks structural correctness, pass/fail |
| 📋 **Debrief** | "debrief", "learnings" | **500 tokens** | Post-ship decomposition — extracts patterns into taxonomy, rules, and skills (`governance/debrief_queue.jsonl`) |

The orchestrator selects the mode based on risk level. Default to Sweep for routine reviews, code reviews, PR reviews, or when asked to review or critique code, diffs, or implementation plans. Bulwark for anything that could be exploited or bypassed.

### Incremental Escalation

When the user upgrades a review mid-session (e.g., "actually run a bulwark"), **do not restart from scratch**. Map completed work to the new protocol's prongs and execute only the delta:

| Already Done | Upgrade To | Execute Only |
|:-------------|:-----------|:-------------|
| Patrol (Probe) | Vanguard | Run Sentry for broader survey, then re-run Probe + Bastion |
| Sweep (fan-out) | Vanguard | Map fan-out → Sentry, then run Probe + Bastion |
| Sweep (fan-out) | Bulwark | Re-run Sentry with security lens, then full Probe → Gauntlet → Bastion |
| Vanguard (Sentry + Probe) | Bulwark | Inject Gauntlet on existing Probe output, then Bastion |
| Vanguard (full) | Bulwark | Inject Gauntlet, re-run Bastion with adversarial context |
| Bulwark (full) | Fortress | Run Trace on existing Sentry output, then Debrief after Bastion |
| Any | Fortress | Run delta prongs needed; Trace slots after Sentry, Debrief after Bastion |

**Caveat**: If code was modified between prongs, verify `git status` is clean before escalating. Stale Probe proposals against a drifted codebase produce invalid Gauntlet results.

### Empirical Refutation Gate

Before accepting any critical finding from a review phase as actionable, require **at least 2 of 3**:
1. A concrete `file:line` citation verified against the actual codebase (±5 lines)
2. An executable reproduction (failing test, script, or command)
3. Independent mechanical verification (math check, grep confirmation)

**Omission findings** (missing auth, missing validation, absent config) satisfy criterion 3 via grep-confirmed absence — they are not demoted for lacking a file:line citation.

Speculative findings meeting only 1 criterion are logged as ⚠️ warning, not promoted to 🔴 critical. Findings meeting 0 criteria are logged as ℹ️ info.

---

## Patrol Protocol (Targeted Fix)

For known defects, renames, or single-file fixes where the problem is already identified. Skips Sentry entirely.

### Phase 1: Probe (Direct Fix)
Dispatch 1 `${SLOT.MODEL_FAST}` analyst directly on the known issue. Provide:
- The specific file(s) and defect description
- Expected behavior vs actual behavior
- The analyst proposes a fix; the **orchestrator** applies the diff

### Phase 2: Bastion (Verify)
Dispatch 1 `${SLOT.MODEL_FAST}` verifier to confirm the applied fix is structurally sound (imports resolve, no orphan references, blast radius check).

**On BLOCK**: If Bastion issues BLOCK, the orchestrator revises the fix (max 1 revision cycle). If still blocked, escalate to Vanguard for broader survey.

**When to use**: `"patrol"`, `"quick fix"` — trivial known bugs, string renames, doc freshness sweeps, lint fixes.

---

## Sweep Protocol (Single-Pass)

**When to use**: `"sweep"`, `"quick review"`, `"review this code"`, `"code review"`, `"PR review"` — routine code reviews, diff audits, PR reviews, implementation plan critique, minor changes. Absorbs general code review triggers: activate when asked to review, audit, or critique code, plans, PRs, or diffs.

### Phase 1: Fan-Out (Independent Analysis)

Dispatch 2–4 **`${SLOT.MODEL_FAST}` research subagents** with orthogonal review lenses. Each reviewer gets:
- A specific analytical focus (architecture, performance, security, etc.)
- Read access to all relevant files (enumerate explicitly in prompt)
- Structured output format requirements
- Independence constraint: reviewers must NOT see each other's findings

**Standard Lenses** (pick 2–4 based on request):

| Lens | Focus | When to Use |
|:-----|:------|:------------|
| **Architecture** | System structure, dependency graph, coverage gaps, configuration integrity, design debt | Always include for system-level reviews |
| **Performance** | Token costs, latency, resource overhead, quantitative ROI, optimization opportunities | When cost/efficiency matters |
| **Security** | OWASP Top 10, secrets exposure, input validation, auth flows, dependency vulnerabilities | When security is in scope |
| **Compliance** | Rule adherence, convention alignment, style consistency, documentation coverage | When governance/standards matter |
| **Behavioral** | Post-mortem waste patterns, rule effectiveness, agent behavior analysis | When reviewing agent sessions |
| **Domain Research** | External docs, wikis, papers, verified facts for the project domain | When external knowledge is needed for the review |
| **Spec Synthesis** | Cross-reference N artifacts → prioritized implementation plan | After reviews complete, before execution |
| **Visual** | Screenshot analysis, UI state, coordinate calibration, threshold tuning | For game automation or UI-heavy reviews |
| **Governance Audit** | Per-rule PASS/FAIL compliance check against session transcript | When verifying rule adherence mechanically |
| **Live Monitor** | Ongoing waste tracking with periodic probes and trajectory alerts | When a session needs real-time observation |

### Phase 2: Synthesis (Staff-Level Review)

After all reviewers report back, the **orchestrator** (not a subagent) performs the staff review:

1. **Cross-reference**: Identify findings that appear in multiple reviews (high confidence)
2. **Fact-check**: Verify quantitative claims against actual file sizes, step counts, or code
3. **Verification sweep**: Before drafting the final assessment, run a filesystem verification script confirming all reviewer assertions (file counts, byte sizes, trigger values, symlink targets). Do not trust reviewer math without mechanical confirmation.
4. **Reconcile conflicts**: When reviewers disagree, investigate and determine which is correct
5. **Incorporate context**: Fold in post-mortems, prior decisions, and architectural tenets
6. **Prioritize**: Rank findings by impact × effort, group into implementation tiers
7. **Produce**: One consolidated artifact with:
   - Verified findings (cross-referenced across reviews)
   - Single-reviewer findings (flagged as lower confidence)
   - Contradictions resolved with evidence
   - Actionable implementation plan sorted by priority

### Phase 3: Delivery

The final artifact follows feature-specs format:
- Problem statement with evidence
- Proposed changes grouped by component
- Implementation order (dependencies first)
- Verification criteria for each change
- Open questions requiring user input

---

## Vanguard Protocol (Progressive Deep Review)

Three prongs, each sharper than the last. Scouts find problems, probe analysts propose solutions, bastion verifiers confirm them. Each round narrows focus based on the previous round's findings.

```
  Sentry (width)        Probe (depth)         Bastion (verification)
  ┌─────────────┐      ┌─────────────┐       ┌──────────────┐
  │ 3-4 fast    │      │ 1-2 fast    │       │ 1 fast       │
  │ broad survey│ ───► │ root cause  │  ───► │ verify fixes │
  │ find issues │      │ deep-dive   │       │ check blast  │
  │ rank by     │      │ propose     │       │ radius       │
  │ severity    │      │ solutions   │       │ pass/fail    │
  └─────────────┘      └─────────────┘       └──────────────┘
    Top 3-5 findings     Concrete fixes        Ship or abort
```

### Prong 1: Sentry (Broad Survey)

Dispatch 3–4 `${SLOT.MODEL_FAST}` scouts with orthogonal lenses (same as Sweep Protocol Phase 1).

**Key difference from Sweep**: Scouts do NOT propose fixes. They only:
- Identify problems with evidence (file:line citations)
- Rank findings by severity (🔴 critical / ⚠️ warning / ℹ️ info)
- Flag areas that need deeper investigation
- Return max 5 findings each
- **Output budget**: 500 tokens max (max 5 findings, ~100 tokens each)

**Orthogonal Personas Note**:
If `.aegis/rules/personas/` contains repo-specific personas, use them to supplement the built-in Orthogonal Personas. Personas provide domain expertise that generic personas lack.

**Scout prompt suffix**:
```
IMPORTANT: Your role is Sentry only. Identify and rank problems.
Do NOT propose solutions. Return your top 5 findings ranked by severity.
Output budget: 500 tokens max (max 5 findings, ~100 tokens each).
Format: 🔴/⚠️/ℹ️ [finding] — Evidence: [file:line]
```

**Orchestrator triage** (between prongs):
After scouts report, the orchestrator:
1. Deduplicates findings across scouts (multi-scout = high confidence)
2. Selects the top 3–5 critical findings for the Probe round
3. Drops ℹ️ info-level findings (address later or never)

### Prong 2: Probe (Focused Deep-Dive)

Dispatch 1–2 `${SLOT.MODEL_FAST}` analysts on ONLY the critical findings from Sentry.

**Key differences**:
- Analysts receive the scout findings as input context
- Analysts propose **concrete fixes** (file, line, change)
- Analysts may activate specialist skills (domain-researcher, visual-analyst) if needed
- Each analyst owns a disjoint subset of findings (no overlap)
- **Output budget**: 1,000 tokens per finding

**Probe prompt template**:
```
<!-- CONTEXT: [PROJECT] from Context Pre-Seeding Protocol -->

PROBE ANALYSIS — You are investigating these findings from the Sentry round:

Output budget: 1,000 tokens max per finding.

1. 🔴 [finding summary] — Evidence: [file:line]
2. 🔴 [finding summary] — Evidence: [file:line]

For each finding:
### Root Cause
[Why this is happening — cite specific code]
### Proposed Fix
[Exact change: file, line range, before/after]
### Blast Radius
[What else this fix affects — grep for usages]
### Verification
[How to confirm the fix works — specific test command]
```

### Prong 3: Bastion (Verification Gate)

Dispatch 1 `${SLOT.MODEL_FAST}` verifier that receives the proposed fixes from Probe.

**Output budget**: 300 tokens (SHIP/BLOCK + max 3 issues).

**Verifier checks** (structural, not execution-based — verifier is read-only):
- Do the proposed fixes introduce new symbol collisions or import conflicts?
- Are there missed dependencies or callers? (grep for usages)
- Is the blast radius accurately scoped?
- Are there internal contradictions between the fix and existing code?

*Note: Bastion does NOT execute test suites (read-only subagent). It verifies structural correctness. The orchestrator runs tests after applying fixes.*

**Verifier output**: `{verdict: "SHIP" | "BLOCK", issues: [...]}` (capped at 300 tokens max, max 3 issues)

If BLOCK: orchestrator reviews issues and either revises fixes or escalates to user.

---

## Bulwark Protocol (Full Adversarial Review)

Extends Vanguard with an adversarial **Gauntlet** prong. Use for changes where cooperative review is insufficient — security, governance rules, breaking changes, core infrastructure.

```
  Sentry (width)     Probe (depth)      Gauntlet (adversarial) Bastion (verify)
  ┌────────────┐    ┌────────────┐     ┌────────────────┐    ┌─────────────┐
  │ 3-4 scouts │    │ 1-2 fixers │     │ 1-2 breakers   │    │ 1 verifier  │
  │ find issues│ ►  │ propose    │  ►  │ BREAK the fixes│ ►  │ final gate  │
  │ rank sev.  │    │ solutions  │     │ falsify claims │    │ pass/fail   │
  └────────────┘    └────────────┘     │ test negatives │    └─────────────┘
    cooperative       cooperative      │ exploit edges  │      cooperative
                                       └────────────────┘
                                         adversarial
```

### Prong 3b: Gauntlet (Adversarial Falsification)

Dispatch 1–2 `${SLOT.MODEL_FAST}` breakers with **explicit falsification objectives**. Breakers receive Probe's proposed fixes and actively try to break them.

**Output budget**: 800 tokens per fix tested.

**Breaker mandate** (NASA IV&V tripartite):
1. **Does it do what it should?** — Verify the fix actually addresses the root cause
2. **Does it NOT do what it must NOT do?** — Test negative invariants (data leaks, regressions, side effects)
3. **Does it handle adverse conditions?** — Edge cases, malformed input, truncated context, concurrent access

*(Note: Persona rules inform edge cases to test here. Use their domain expertise to identify project-specific vulnerabilities.)*

**Key differences from Bastion**:
- Bastion is cooperative ("does this look right?")
- Gauntlet is adversarial ("how can I break this?")
- Breakers are **rewarded for finding breaks**, not for confirming correctness

**Breaker prompt template**:
```
<!-- CONTEXT: [PROJECT] from Context Pre-Seeding Protocol -->

GAUNTLET ANALYSIS — You are an adversarial reviewer. Your job is to BREAK these fixes.
Output budget: 800 tokens max per fix tested.

Read ALL of these files for context:
[explicit file list — same as Probe received]

Proposed changes from Probe:
1. [fix summary + file:line]
2. [fix summary + file:line]

For each fix, attempt to falsify it:
### Negative Invariants
[Does this fix introduce anything it must NOT do? Data leaks? Regressions? Side effects?]
### Edge Cases
[What inputs break this? Empty arrays? Concurrent access? Truncated context?]
### Bypass Vectors
[Can an agent hallucinate around this fix? Can the rule be circumvented?]
### Adverse Conditions
[What happens when the environment is degraded? Network down? Stale cache? Wrong venv?]

Output: {broken: [{fix_id, how, severity}], survived: [fix_ids]}
```

**Orchestrator response to Gauntlet findings**:
- If `broken` is non-empty: revise fixes and re-run Probe on broken items (**max 2 revision cycles** — if still broken after 2 cycles, escalate to user)
- If all `survived`: proceed to Bastion
- If breaker finds a bypass vector: escalate to user before proceeding

### When to Skip Prongs

| Scenario | Protocol | Prongs Used | Rationale |
|:---------|:---------|:-----------:|:----------|
| Known bug / rename | Patrol | Probe + Bastion | Defect already located, skip scouting |
| Style/docs | Sweep | Sentry only | No fixes needed |
| Bug fix | Vanguard | Sentry + Probe + Bastion | Structural check catches regressions |
| Feature | Vanguard | Sentry + Probe + Bastion | Blast radius check needed |
| Architecture | Bulwark | Sentry + Probe + Gauntlet + Bastion | High blast radius + adversarial edge cases |
| Security/governance | Bulwark | Sentry + Probe + Gauntlet + Bastion | Must verify no bypass vectors |
| Schema migration / infra | Fortress | All 6 prongs | Cross-repo impact + post-ship learnings |
| Pre-release certification | Citadel | 8 adversarial prongs + Debrief | Zero surviving findings across Prosecutor/Defender pairs |
| Post-mortem | Standalone | Sentry only | Findings, not fixes |

---

## Fortress Protocol (Full Assurance)

The full-assurance review mode. Extends Bulwark with **Trace** (dependency impact mapping) after Sentry and **Debrief** (learning extraction) after Bastion. For catastrophic-risk changes: infrastructure, auth pipelines, schema migrations, core governance. Uses 8–12 dispatches across 4 turns (optimized from 6 turns via parallel execution).

**Optimization**: Trace may run in parallel with Sentry when target files are known upfront. Gauntlet may run concurrently with Bastion.

**Fast-tier mandate**: All review prongs (Sentry, Trace, Probe, Gauntlet, Bastion, Debrief) use strictly `${SLOT.MODEL_FAST}` models. No `${SLOT.MODEL_STANDARD}` or `${SLOT.MODEL_HEAVY}` for diff proposers — reserve heavyweight models for orchestrator synthesis only.

**Human gate**: Before Bastion issues final verdict, the orchestrator presents the Gauntlet findings and proposed fixes to the user and asks for explicit approval. User may approve, reject, or request revision.

```
  Sentry (scout)     Trace (map)          Probe (fix)
  ┌────────────┐    ┌──────────────┐    ┌─────────────┐
  │ 3-4 fast   │    │ 1-2 fast     │    │ 1-2 fast    │
  │ find issues│ ─► │ trace deps   │ ─► │ propose     │
  │ rank sev.  │    │ blast radius │    │ solutions   │
  └────────────┘    │ cross-repo   │    └──────┬──────┘
                    └──────────────┘           │
                                               ▼
  Debrief (learn)    Bastion (verify)     Gauntlet (break)
  ┌────────────┐    ┌──────────────┐    ┌──────────────┐
  │ 1 fast     │    │ 1 fast       │    │ 1-2 fast     │
  │ extract    │ ◄─ │ SHIP/BLOCK   │ ◄─ │ falsify      │
  │ patterns   │    │ human gate   │    │ NASA IV&V    │
  │ → taxonomy │    └──────────────┘    └──────────────┘
  └────────────┘
```

### Prong: Trace (Dependency Impact Mapping)

Dispatch 1–2 `${SLOT.MODEL_FAST}` analysts to map the **blast radius** of the files and symbols identified by Sentry. Trace receives the Sentry findings (affected files, flagged symbols) and traces their dependency graph:

**Output budget**: 800 tokens max.

1. **Import/call chains**: What calls the flagged symbols? What do they call? (max 2 hops per direction)
2. **Cross-repo state**: If the project spans multiple repos, check for shared schemas, configs, or contracts
3. **Type consumers**: Who depends on the interfaces in the flagged files? List downstream consumers
4. **Config propagation**: Environment variables, feature flags, or serialized state affected

Trace output is passed to Probe alongside Sentry findings, so Probe analysts have full blast radius context before proposing fixes.

**Trace prompt template**:
```
TRACE ANALYSIS — You are mapping the blast radius of flagged files/symbols.
Output budget: 800 tokens max.

Sentry identified these files and issues:
[Sentry findings summary with file:line citations]

Read ALL of these files for context:
[explicit file list — flagged files + their direct importers]

For each flagged file/symbol:
### Import Chain (max 2 hops)
[Who calls this? What does this call?]
### Cross-Repo Impact
[Does this file share schemas, configs, or contracts with other repositories?]
### Downstream Consumers
[List every file/function that imports or depends on the flagged symbols]

Output: {blast_radius: [{file, symbol, affected_files: [], affected_repos: [], risk_level}]}
```

### Prong: Debrief (Post-Review Learning Extraction)

After Bastion renders its verdict (**SHIP or BLOCK** — Debrief runs either way), dispatch 1 `${SLOT.MODEL_FAST}` analyst to decompose the review's findings into **proposed learnings** (`DEBRIEF-XXX` entries in `governance/debrief_queue.jsonl`). Debrief is read-only; it proposes changes that the **orchestrator queues for the next session** (not applied immediately, to avoid triggering recursive governance reviews).

**Output budget**: 500 tokens max.

1. **Taxonomy patterns**: New failure modes not yet in `taxonomy.json` — propose `pattern_name`, `description`, `detection_rule`
2. **Steering rules**: New invariants discovered — propose `rule_file`, `section`, `addition`
3. **Skill recipes**: Successful repair patterns — propose `skill_name`, `trigger`, `steps`
4. **Observable metrics**: Agent dispatches, prong count, findings count, breakage count (only metrics directly observable from the review artifacts — do NOT estimate token costs or accuracy rates)

**Circuit breaker**: Debrief proposals are queued in `governance/debrief_queue.jsonl` (`DEBRIEF-XXX`), not applied immediately. The orchestrator presents them to the user at session end. Applying rule changes requires a separate review in a future session.

**Debrief prompt template**:
```
DEBRIEF ANALYSIS — You are extracting reusable learnings from this completed review.
Output budget: 500 tokens max.

Read the review artifacts:
[Sentry findings, Probe fixes, Gauntlet breakages, Bastion verdict]

Propose (do NOT apply directly):
### New Taxonomy Patterns
[Failure modes not yet in taxonomy.json — provide pattern_name, description, detection_rule]
### Proposed Rule Updates
[New governance invariants discovered — provide rule_file, section, proposed addition]
### Skill Recipes
[Successful repair patterns that could be reusable — provide skill_name, trigger, steps]
### Observable Review Metrics
[Agents dispatched, prongs executed, findings count, breakage count]
```

---

## Continuous Review Mode (Coding Sessions)

For coding sessions exceeding ~75 steps, the orchestrator should dispatch lightweight `${SLOT.MODEL_FAST}` review probes at natural breakpoints instead of waiting for a batch review.

### When to Dispatch
- After completing a logical unit (feature, bugfix, refactor pass)
- Before any `git push`
- Every ~50 coding steps if no natural breakpoint occurred
- After any subagent delivers code that will be committed

### Probe Scope (Lightweight — NOT a full staff review)
The fast-tier reviewer receives:
1. List of files modified since last probe (`git diff --name-only`)
2. The actual diffs (`git diff`)
3. The project's test runner command

The reviewer checks:
- **Symbol consistency**: No hallucinated attributes/methods (e.g., `total_mem` vs `total_memory`)
- **Import validity**: All imports resolve to real modules
- **Blast radius**: Any public API changes that affect callers?
- **Test execution**: Run the test suite, report failures

### Probe Output
Structured findings: `{critical: [...], warnings: [...], clean: true/false}`
If critical findings exist, orchestrator must fix before continuing.

### Cost Budget
- Each probe: ~1,000 fast-tier tokens
- At 1 probe per 50 steps over a 500-step session: ~10,000 tokens total
- ROI: prevents 50-150 steps of rework (50,000-150,000 tokens saved)

## Specialist Skill Activation

When a staff review identifies that specialist analysis is needed, the orchestrator can activate dedicated skills as additional reviewers:

### Discovery & Context (activate during Sentry)

| Need | Skill | How |
|:-----|:------|:----|
| Domain knowledge gaps | `domain-researcher` | Dispatch with project context + specific questions |
| Screenshot/UI evidence needed | `visual-analyst` | Dispatch with image paths |
| Performance hot-paths suspected | `performance-audit` | Dispatch with hot-path file list + profiling data |
| Environment/infra issues found | `session-preflight` | Activate to verify venv, git state, display health |

### Depth & Fix Proposal (activate during Probe)

| Need | Skill | How |
|:-----|:------|:----|
| Large restructuring needed | `refactoring-pilot` | Dispatch with Mikado graph + file list |
| Live bug found during review | `incident-debug` | Dispatch with error logs + reproduction steps |
| Multiple reports need consolidation | `spec-synthesizer` | Dispatch with artifact list + constraints |

### Adversarial & Compliance (activate during Gauntlet)

| Need | Skill | How |
|:-----|:------|:----|
| Security bypass vectors suspected | `security-audit` | Dispatch with OWASP focus + auth/input files |
| Rule compliance unclear | `governance-auditor` | Dispatch with transcript path |

### Post-Review (activate standalone)

| Need | Skill | How |
|:-----|:------|:----|
| Active session needs monitoring | `session-monitor` | Activate with session ID + alert thresholds |
| Retrospective analysis needed | `post-mortem` | Dispatch with session transcript + metrics |
| Documentation refresh needed | `readme-writer` | Dispatch with changed file list + project context |

Specialists run as **`${SLOT.MODEL_FAST}` subagents** and report back like standard reviewers. The orchestrator synthesizes their findings alongside the standard lens results. Specialists may also be activated independently outside of a staff review when the user requests their specific capability.

## Anti-Patterns

- **Don't dispatch a subagent for synthesis** — the orchestrator retains design authority and cross-cutting context that subagents lack
- **Don't let reviewers see each other's work** — independence prevents confirmation bias (scouts in Sentry are independent; Probe analysts receive scout findings but not each other's)
- **Don't skip fact-checking** — reviewer claims must be verified against actual data before presenting to user
- **Don't fan out >4 reviewers per prong** — diminishing returns; 4 orthogonal lenses catch ~98% of issues
- **Don't use `${SLOT.MODEL_STANDARD}` or `${SLOT.MODEL_HEAVY}` for reviewers** — `${SLOT.MODEL_FAST}` is sufficient for read-only analysis; reserve heavyweight models for synthesis. This is a strict mandate for all prongs including diff proposers (see E14, E15 experiments)
- **Don't let scouts propose fixes** (Vanguard) — separation of concerns keeps Sentry fast and unbiased
- **Don't let Probe analysts find new problems** (Vanguard) — scope creep; if new issues surface, log them for the next review cycle

## Model Selection

| Role | Model | Max Output | Rationale |
|:-----|:------|:----------:|:----------|
| Sentry scout | `${SLOT.MODEL_FAST}` | 500 tokens | Read-heavy, structured output, max 5 findings |
| Trace analyst | `${SLOT.MODEL_FAST}` | 800 tokens | Dependency tracing, grep-based, blast radius map |
| Probe analyst | `${SLOT.MODEL_FAST}` | 1,000 tokens/finding | Focused analysis, concrete fix proposals |
| Gauntlet breaker | `${SLOT.MODEL_FAST}` | 800 tokens/fix | Adversarial falsification, edge-case probing |
| Bastion verifier | `${SLOT.MODEL_FAST}` | 300 tokens | Checklist-based, SHIP/BLOCK + max 3 issues |
| Debrief extractor | `${SLOT.MODEL_FAST}` | 500 tokens | Pattern extraction, structured taxonomy output |
| Staff synthesizer | orchestrator (self) | Uncapped | Needs cross-cutting context, design authority, write access |

## Example Prompt Template for Reviewers

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

Perform a [LENS] REVIEW of [SYSTEM].

Read ALL of these files:
[explicit file list]

Deliver:
### 1. [Category]
[specific questions]

### 2. [Category]
[specific questions]

Provide specific evidence (file paths, line numbers, byte counts).
```


---
name: Staff Review Protocol
description: Multi-lens review fan-out with staff-level synthesis across five modes from Breeze to Tempest.
trigger: user_request
aliases: ["review this code", "code review", "PR review"]
---
# Staff Review Protocol

> **Role**: Orchestrates expert reviews from independent perspectives, then synthesizes findings into a single fact-checked, actionable artifact. Supports multiple review modes scaled by risk level.

## Review Modes

| Mode | Alias | Prongs | Flash Dispatches | Output Budget | When to Use |
|:-----|:------|:------:|:----------------:|:-------------:|:------------|
| **Breeze** | "breeze", "quick fix" | Roots → Bedrock | 2 | ≤2k output | Known defect, single-file fix, rename |
| **Gale** | "gale", "quick review", "review this code", "code review", "PR review" | Spores → Synthesize | 3–4 | ≤3k output | Quick reviews, PR reviews, code diffs, minor changes |
| **Trident** | "trident", "deep review" | Spores → Roots → Bedrock | 5–8 | ≤6k output | Feature reviews, refactors |
| **Maelstrom** | "maelstrom", "max review" | Spores → Roots → Thorns → Bedrock | 7–12 | ≤10k output | Architecture, security, breaking changes |
| **Tempest** | "tempest", "full assurance" | Spores → Mycelium → Roots → Thorns → Bedrock → Mulch | 8–12 | ≤15k output | Catastrophic risk, infra, auth, schema migrations |

> [!NOTE]
> Subagents do **NOT** inherit parent rules. Each scout gets a clean context window with only its task prompt (~200 tokens pre-seeding). Total protocol cost = (N dispatches × per-scout input context) + total output. Parent rule cost is paid ONCE by the orchestrator, not per-scout.

### Risk-Based Protocol Selection

Choose protocol by **failure severity**, not scope:

| Risk Level | Failure Impact | Protocol | Example |
|:-----------|:---------------|:---------|:--------|
| Trivial | Known bug, rename, doc sync | Breeze | Single-file fix, string rename |
| Low | Cosmetic, docs | Gale | README update, style fix |
| Medium | Feature regression | Trident (Spores + Roots + Bedrock) | New feature, bug fix |
| High | API breakage, data loss | Trident (full 3-prong) | Public API change, refactor |
| Critical | Security breach, rule bypass | Maelstrom | Auth flow, governance rule changes |
| Catastrophic | Production outage, data corruption | Tempest + `ask_question` human gate | Infra, schema migration, core protocol |

### Individual Prongs (run standalone)

| Prong | Alias | Max Output Tokens | What It Does |
|:------|:------|:-----------------|:-------------|
| 🍄 **Spores** | "spores", "scout" | **500 tokens** (max 5 findings, ~100 each) | Broad parallel survey — finds problems, ranks by severity, no fixes |
| 🍄 **Mycelium** | "mycelium", "dependencies" | **800 tokens** | Maps blast radius, cross-repo state, dependency chains — what does this change touch? |
| 🌿 **Roots** | "roots", "deep dive" | **1,000 tokens** per finding | Focused analysis on specific findings — proposes concrete fixes |
| 🌹 **Thorns** | "thorns", "break it", "red team" | **800 tokens** per fix tested | Adversarial falsification — actively tries to break proposed fixes |
| 🪨 **Bedrock** | "bedrock", "verify" | **300 tokens** (SHIP/BLOCK + max 3 issues) | Final verification gate — checks structural correctness, pass/fail |
| 🍂 **Mulch** | "mulch", "learnings" | **500 tokens** | Post-ship decomposition — extracts patterns into taxonomy, rules, and skills |

The orchestrator selects the mode based on risk level. Default to Gale for routine reviews, code reviews, PR reviews, or when asked to review or critique code, diffs, or implementation plans. Maelstrom for anything that could be exploited or bypassed.

### Incremental Escalation

When the user upgrades a review mid-session (e.g., "actually run a maelstrom"), **do not restart from scratch**. Map completed work to the new protocol's prongs and execute only the delta:

| Already Done | Upgrade To | Execute Only |
|:-------------|:-----------|:-------------|
| Breeze (Roots) | Trident | Run Spores for broader survey, then re-run Roots + Bedrock |
| Gale (fan-out) | Trident | Map fan-out → Spores, then run Roots + Bedrock |
| Gale (fan-out) | Maelstrom | Re-run Spores with security lens, then full Roots → Thorns → Bedrock |
| Trident (Spores + Roots) | Maelstrom | Inject Thorns on existing Roots output, then Bedrock |
| Trident (full) | Maelstrom | Inject Thorns, re-run Bedrock with adversarial context |
| Maelstrom (full) | Tempest | Run Mycelium on existing Spores output, then Mulch after Bedrock |
| Any | Tempest | Run delta prongs needed; Mycelium slots after Spores, Mulch after Bedrock |

**Caveat**: If code was modified between prongs, verify `git status` is clean before escalating. Stale Roots proposals against a drifted codebase produce invalid Thorns results.

### Empirical Refutation Gate

Before accepting any critical finding from a review phase as actionable, require **at least 2 of 3**:
1. A concrete `file:line` citation verified against the actual codebase (±5 lines)
2. An executable reproduction (failing test, script, or command)
3. Independent mechanical verification (math check, grep confirmation)

**Omission findings** (missing auth, missing validation, absent config) satisfy criterion 3 via grep-confirmed absence — they are not demoted for lacking a file:line citation.

Speculative findings meeting only 1 criterion are logged as ⚠️ warning, not promoted to 🔴 critical. Findings meeting 0 criteria are logged as ℹ️ info.

---

## Breeze Protocol (Targeted Fix)

For known defects, renames, or single-file fixes where the problem is already identified. Skips Spores entirely.

### Phase 1: Roots (Direct Fix)
Dispatch 1 Flash analyst directly on the known issue. Provide:
- The specific file(s) and defect description
- Expected behavior vs actual behavior
- The analyst proposes a fix; the **orchestrator** applies the diff

### Phase 2: Bedrock (Verify)
Dispatch 1 Flash verifier to confirm the applied fix is structurally sound (imports resolve, no orphan references, blast radius check).

**On BLOCK**: If Bedrock issues BLOCK, the orchestrator revises the fix (max 1 revision cycle). If still blocked, escalate to Trident for broader survey.

**When to use**: `"breeze"`, `"quick fix"` — trivial known bugs, string renames, doc freshness sweeps, lint fixes.

---

## Gale Protocol (Single-Pass)

**When to use**: `"gale"`, `"quick review"`, `"review this code"`, `"code review"`, `"PR review"` — routine code reviews, diff audits, PR reviews, implementation plan critique, minor changes. Absorbs general code review triggers: activate when asked to review, audit, or critique code, plans, PRs, or diffs.

### Phase 1: Fan-Out (Independent Analysis)

Dispatch 2–4 **Flash-tier research subagents** with orthogonal review lenses. Each reviewer gets:
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

## Trident Protocol (Progressive Deep Review)

Three prongs, each sharper than the last. Scouts find problems, root analysts propose solutions, bedrock verifiers confirm them. Each round narrows focus based on the previous round's findings.

```
  Spores (width)        Roots (depth)         Bedrock (verification)
  ┌─────────────┐      ┌─────────────┐       ┌──────────────┐
  │ 3-4 Flash   │      │ 1-2 Flash   │       │ 1 Flash      │
  │ broad survey│ ───► │ root cause  │  ───► │ verify fixes │
  │ find issues │      │ deep-dive   │       │ check blast  │
  │ rank by     │      │ propose     │       │ radius       │
  │ severity    │      │ solutions   │       │ pass/fail    │
  └─────────────┘      └─────────────┘       └──────────────┘
    Top 3-5 findings     Concrete fixes        Ship or abort
```

### Prong 1: Spores (Broad Survey)

Dispatch 3–4 Flash scouts with orthogonal lenses (same as Gale Protocol Phase 1).

**Key difference from Gale**: Scouts do NOT propose fixes. They only:
- Identify problems with evidence (file:line citations)
- Rank findings by severity (🔴 critical / ⚠️ warning / ℹ️ info)
- Flag areas that need deeper investigation
- Return max 5 findings each
- **Output budget**: 500 tokens max (max 5 findings, ~100 tokens each)

**Orthogonal Personas Note**:
If `.soma/cells/chloroplasts/` contains repo-specific personas, use them to supplement the built-in Orthogonal Personas. Chloroplasts provide domain expertise that generic personas lack.

**Scout prompt suffix**:
```
IMPORTANT: Your role is Spores only. Identify and rank problems.
Do NOT propose solutions. Return your top 5 findings ranked by severity.
Output budget: 500 tokens max (max 5 findings, ~100 tokens each).
Format: 🔴/⚠️/ℹ️ [finding] — Evidence: [file:line]
```

**Orchestrator triage** (between prongs):
After scouts report, the orchestrator:
1. Deduplicates findings across scouts (multi-scout = high confidence)
2. Selects the top 3–5 critical findings for the Roots round
3. Drops ℹ️ info-level findings (address later or never)

### Prong 2: Roots (Focused Deep-Dive)

Dispatch 1–2 Flash analysts on ONLY the critical findings from Spores.

**Key differences**:
- Analysts receive the scout findings as input context
- Analysts propose **concrete fixes** (file, line, change)
- Analysts may activate specialist skills (domain-researcher, visual-analyst) if needed
- Each analyst owns a disjoint subset of findings (no overlap)
- **Output budget**: 1,000 tokens per finding

**Roots prompt template**:
```
<!-- CONTEXT: [PROJECT] from Context Pre-Seeding Protocol -->

ROOTS ANALYSIS — You are investigating these findings from the Spores round:

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

### Prong 3: Bedrock (Verification Gate)

Dispatch 1 Flash verifier that receives the proposed fixes from Roots.

**Output budget**: 300 tokens (SHIP/BLOCK + max 3 issues).

**Verifier checks** (structural, not execution-based — verifier is read-only):
- Do the proposed fixes introduce new symbol collisions or import conflicts?
- Are there missed dependencies or callers? (grep for usages)
- Is the blast radius accurately scoped?
- Are there internal contradictions between the fix and existing code?

*Note: Bedrock does NOT execute test suites (read-only subagent). It verifies structural correctness. The orchestrator runs tests after applying fixes.*

**Verifier output**: `{verdict: "SHIP" | "BLOCK", issues: [...]}` (capped at 300 tokens max, max 3 issues)

If BLOCK: orchestrator reviews issues and either revises fixes or escalates to user.

---

## Maelstrom Protocol (Full Adversarial Review)

Extends Trident with an adversarial **Thorns** prong. Use for changes where cooperative review is insufficient — security, governance rules, breaking changes, core infrastructure.

```
  Spores (width)     Roots (depth)      Thorns (adversarial)   Bedrock (verify)
  ┌────────────┐    ┌────────────┐     ┌────────────────┐    ┌─────────────┐
  │ 3-4 scouts │    │ 1-2 fixers │     │ 1-2 breakers   │    │ 1 verifier  │
  │ find issues│ ►  │ propose    │  ►  │ BREAK the fixes│ ►  │ final gate  │
  │ rank sev.  │    │ solutions  │     │ falsify claims │    │ pass/fail   │
  └────────────┘    └────────────┘     │ test negatives │    └─────────────┘
    cooperative       cooperative      │ exploit edges  │      cooperative
                                       └────────────────┘
                                         adversarial
```

### Prong 3b: Thorns (Adversarial Falsification)

Dispatch 1–2 Flash breakers with **explicit falsification objectives**. Breakers receive Roots' proposed fixes and actively try to break them.

**Output budget**: 800 tokens per fix tested.

**Breaker mandate** (NASA IV&V tripartite):
1. **Does it do what it should?** — Verify the fix actually addresses the root cause
2. **Does it NOT do what it must NOT do?** — Test negative invariants (data leaks, regressions, side effects)
3. **Does it handle adverse conditions?** — Edge cases, malformed input, truncated context, concurrent access

*(Note: Chloroplast personas inform edge cases to test here. Use their domain expertise to identify project-specific vulnerabilities.)*

**Key differences from Bedrock**:
- Bedrock is cooperative ("does this look right?")
- Thorns is adversarial ("how can I break this?")
- Breakers are **rewarded for finding breaks**, not for confirming correctness

**Breaker prompt template**:
```
<!-- CONTEXT: [PROJECT] from Context Pre-Seeding Protocol -->

THORNS ANALYSIS — You are an adversarial reviewer. Your job is to BREAK these fixes.
Output budget: 800 tokens max per fix tested.

Read ALL of these files for context:
[explicit file list — same as Roots received]

Proposed changes from Roots:
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

**Orchestrator response to Thorns findings**:
- If `broken` is non-empty: revise fixes and re-run Roots on broken items (**max 2 revision cycles** — if still broken after 2 cycles, escalate to user)
- If all `survived`: proceed to Bedrock
- If breaker finds a bypass vector: escalate to user before proceeding

### When to Skip Prongs

| Scenario | Protocol | Prongs Used | Rationale |
|:---------|:---------|:-----------:|:----------|
| Known bug / rename | Breeze | Roots + Bedrock | Defect already located, skip scouting |
| Style/docs | Gale | Spores only | No fixes needed |
| Bug fix | Trident | Spores + Roots + Bedrock | Structural check catches regressions |
| Feature | Trident | Spores + Roots + Bedrock | Blast radius check needed |
| Architecture | Maelstrom | Spores + Roots + Thorns + Bedrock | High blast radius + adversarial edge cases |
| Security/governance | Maelstrom | Spores + Roots + Thorns + Bedrock | Must verify no bypass vectors |
| Schema migration / infra | Tempest | All 6 prongs | Cross-repo impact + post-ship learnings |
| Post-mortem | Standalone | Spores only | Findings, not fixes |

---

## Tempest Protocol (Full Assurance)

The highest-assurance review mode. Extends Maelstrom with **Mycelium** (dependency impact mapping) after Spores and **Mulch** (learning extraction) after Bedrock. For catastrophic-risk changes: infrastructure, auth pipelines, schema migrations, core governance. Uses 8–12 dispatches across 4 turns (optimized from 6 turns via parallel execution).

**Optimization**: Mycelium may run in parallel with Spores when target files are known upfront. Thorns may run concurrently with Bedrock.

**Flash mandate**: All review prongs (Spores, Mycelium, Roots, Thorns, Bedrock, Mulch) use strictly Flash-tier models. No inherit/pro for diff proposers — reserve heavyweight models for orchestrator synthesis only.

**Human gate**: Before Bedrock issues final verdict, the orchestrator presents the Thorns findings and proposed fixes via `ask_question` for explicit user approval. User may approve, reject, or request revision.

```
  Spores (scout)     Mycelium (map)       Roots (fix)
  ┌────────────┐    ┌──────────────┐    ┌─────────────┐
  │ 3-4 Flash  │    │ 1-2 Flash    │    │ 1-2 Flash   │
  │ find issues│ ─► │ trace deps   │ ─► │ propose     │
  │ rank sev.  │    │ blast radius │    │ solutions   │
  └────────────┘    │ cross-repo   │    └──────┬──────┘
                    └──────────────┘           │
                                               ▼
  Mulch (learn)      Bedrock (verify)     Thorns (break)
  ┌────────────┐    ┌──────────────┐    ┌──────────────┐
  │ 1 Flash    │    │ 1 Flash      │    │ 1-2 Flash    │
  │ extract    │ ◄─ │ SHIP/BLOCK   │ ◄─ │ falsify      │
  │ patterns   │    │ human gate   │    │ NASA IV&V    │
  │ → taxonomy │    └──────────────┘    └──────────────┘
  └────────────┘
```

### Prong: Mycelium (Dependency Impact Mapping)

Dispatch 1–2 Flash analysts to map the **blast radius** of the files and symbols identified by Spores. Mycelium receives the Spores findings (affected files, flagged symbols) and traces their dependency graph:

**Output budget**: 800 tokens max.

1. **Import/call chains**: What calls the flagged symbols? What do they call? (max 2 hops per direction)
2. **Cross-repo state**: If the project spans multiple repos, check for shared schemas, configs, or contracts
3. **Type consumers**: Who depends on the interfaces in the flagged files? List downstream consumers
4. **Config propagation**: Environment variables, feature flags, or serialized state affected

Mycelium output is passed to Roots alongside Spores findings, so Roots analysts have full blast radius context before proposing fixes.

**Mycelium prompt template**:
```
MYCELIUM ANALYSIS — You are mapping the blast radius of flagged files/symbols.
Output budget: 800 tokens max.

Spores identified these files and issues:
[Spores findings summary with file:line citations]

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

### Prong: Mulch (Post-Review Learning Extraction)

After Bedrock renders its verdict (**SHIP or BLOCK** — Mulch runs either way), dispatch 1 Flash analyst to decompose the review's findings into **proposed learnings**. Mulch is read-only; it proposes changes that the **orchestrator queues for the next session** (not applied immediately, to avoid triggering recursive governance reviews).

**Output budget**: 500 tokens max.

1. **Taxonomy patterns**: New failure modes not yet in `taxonomy.json` — propose `pattern_name`, `description`, `detection_rule`
2. **Steering rules**: New invariants discovered — propose `rule_file`, `section`, `addition`
3. **Skill recipes**: Successful repair patterns — propose `skill_name`, `trigger`, `steps`
4. **Observable metrics**: Agent dispatches, prong count, findings count, breakage count (only metrics directly observable from the review artifacts — do NOT estimate token costs or accuracy rates)

**Circuit breaker**: Mulch proposals are queued, not applied. The orchestrator presents them to the user at session end. Applying rule changes requires a separate review in a future session.

**Mulch prompt template**:
```
MULCH ANALYSIS — You are extracting reusable learnings from this completed review.
Output budget: 500 tokens max.

Read the review artifacts:
[Spores findings, Roots fixes, Thorns breakages, Bedrock verdict]

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

For coding sessions exceeding ~75 steps, the orchestrator should dispatch lightweight Flash review probes at natural breakpoints instead of waiting for a batch review.

### When to Dispatch
- After completing a logical unit (feature, bugfix, refactor pass)
- Before any `git push`
- Every ~50 coding steps if no natural breakpoint occurred
- After any subagent delivers code that will be committed

### Probe Scope (Lightweight — NOT a full staff review)
The Flash reviewer receives:
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
- Each probe: ~1,000 Flash tokens
- At 1 probe per 50 steps over a 500-step session: ~10,000 tokens total
- ROI: prevents 50-150 steps of rework (50,000-150,000 tokens saved)

## Specialist Skill Activation

When a staff review identifies that specialist analysis is needed, the orchestrator can activate dedicated skills as additional reviewers:

### Discovery & Context (activate during Spores)

| Need | Skill | How |
|:-----|:------|:----|
| Domain knowledge gaps | `domain-researcher` | Dispatch with project context + specific questions |
| Screenshot/UI evidence needed | `visual-analyst` | Dispatch with image paths |
| Performance hot-paths suspected | `performance-audit` | Dispatch with hot-path file list + profiling data |
| Environment/infra issues found | `session-preflight` | Activate to verify venv, git state, display health |

### Depth & Fix Proposal (activate during Roots)

| Need | Skill | How |
|:-----|:------|:----|
| Large restructuring needed | `refactoring-pilot` | Dispatch with Mikado graph + file list |
| Live bug found during review | `incident-debug` | Dispatch with error logs + reproduction steps |
| Multiple reports need consolidation | `spec-synthesizer` | Dispatch with artifact list + constraints |

### Adversarial & Compliance (activate during Thorns)

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

Specialists run as **Flash subagents** and report back like standard reviewers. The orchestrator synthesizes their findings alongside the standard lens results. Specialists may also be activated independently outside of a staff review when the user requests their specific capability.

## Anti-Patterns

- **Don't dispatch a subagent for synthesis** — the orchestrator retains design authority and cross-cutting context that subagents lack
- **Don't let reviewers see each other's work** — independence prevents confirmation bias (scouts in Spores are independent; Roots analysts receive scout findings but not each other's)
- **Don't skip fact-checking** — reviewer claims must be verified against actual data before presenting to user
- **Don't fan out >4 reviewers per prong** — diminishing returns; 4 orthogonal lenses catch ~98% of issues
- **Don't use inherit/pro for reviewers** — Flash is sufficient for read-only analysis; reserve heavyweight models for synthesis. This is a strict mandate for all prongs including diff proposers (see E14, E15 experiments)
- **Don't let scouts propose fixes** (Trident) — separation of concerns keeps Spores fast and unbiased
- **Don't let Roots analysts find new problems** (Trident) — scope creep; if new issues surface, log them for the next review cycle

## Model Selection

| Role | Model | Max Output | Rationale |
|:-----|:------|:----------:|:----------|
| Spores scout | `flash` | 500 tokens | Read-heavy, structured output, max 5 findings |
| Mycelium analyst | `flash` | 800 tokens | Dependency tracing, grep-based, blast radius map |
| Roots analyst | `flash` | 1,000 tokens/finding | Focused analysis, concrete fix proposals |
| Thorns breaker | `flash` | 800 tokens/fix | Adversarial falsification, edge-case probing |
| Bedrock verifier | `flash` | 300 tokens | Checklist-based, SHIP/BLOCK + max 3 issues |
| Mulch extractor | `flash` | 500 tokens | Pattern extraction, structured taxonomy output |
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


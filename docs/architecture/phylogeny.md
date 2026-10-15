# How This Approach Evolved

These rules weren't designed in a vacuum. They were extracted from real failures, refined through staff-level review, and continuously validated against live coding sessions.

## Phase 1: Prescriptive Rules ("Write what sounds right")

The first version was 4 `always_on` rules and 4 flat-checklist skills, written from best practices and intuition. Providence said "don't hallucinate." Cost-optimization said "use Flash for research." Testing said "test sad paths."

**What we learned:** Prescriptive rules are necessary but insufficient. The agent followed the letter of the rules while violating the spirit — it would "verify" by re-reading the same file 4 times, or "delegate" by spawning a Pro-tier subagent for a 3-line edit.

**Impact on rules:** Led to the **3 formal review iterations** (21 findings), which caught contradictions between rules, missing coverage, and ambiguous terminology.

## Phase 2: Evidence-Based Evolution ("Extract rules from real failures")

The turning point was running a **1,339-step post-mortem** on a real project session. Instead of guessing what rules were needed, we analyzed what actually went wrong:

- **749 steps (~56%) were wasted** on rework
- **180 steps** lost to hallucinated game hotkeys the agent invented without checking
- **110 steps** lost to venv confusion (host Python vs. project venv)
- **103 steps** lost to an infinite polling loop in tests with no timeout
- **50 steps** lost to method shadowing (`action_masks()` silently overridden)

Each failure pattern mapped directly to a missing rule:

| Failure (steps wasted) | Rule Created |
|:-----------------------|:-------------|
| Hallucinated hotkeys (180) | UI Grounding Gate — verify via screenshots, never guess |
| Venv confusion (110) | Makefile Venv Guard — bind `$(VENV)/bin/python` explicitly |
| Infinite test polling (103) | Mock-First Mandate — hardware boundaries always mocked |
| Method shadowing (50) | Symbol Collision Guard — grep before defining in large files |
| Stale references after rename (30) | Refactoring Sweep — global grep confirms zero orphans |

**Impact on rules:** This phase added 6 rules to providence.md and testing.md. More importantly, it shifted the methodology: rules are now derived from **observed waste**, not assumed best practices.

## Phase 3: Cross-Conversation Discovery ("Same failures, different projects")

Analyzing a single session was revealing. Analyzing **all sessions** showed which patterns are systemic:

| Pattern | Dwarf Fortress (1,579 steps) | TAB AI (1,551 steps) | Steering (856 steps) |
|:--------|:---:|:---:|:---:|
| Hallucinated controls | ✅ 160 steps | ✅ 180 steps | — |
| Venv/path confusion | ✅ | ✅ | — |
| Zero subagent delegation | ✅ 0 subagents, 17 compactions | Improved | Heavy use |
| Bulk media context pollution | — | ✅ 127 files in brain | — |
| Desktop automation safety breach | ✅ clicked through Steam | — | — |
| Premature framework extraction | ✅ 150 steps on unused SDK | — | — |

The Dwarf Fortress session was the most catastrophic: **1,579 steps, 8 architectural pivots, 2 safety incidents, and zero subagent delegation.** It burned an estimated 8M tokens and produced zero working autonomous runs.

**Impact on rules:** This phase added 5 entirely new governance areas — desktop automation safety, premature abstraction bans, pivot discipline, delegation floors, and real-time loop budgets.

## Phase 4: Continuous Governance ("Rules that improve themselves")

The final shift was from periodic review to continuous monitoring:

```
Session analyzed → waste classified by 23-pattern taxonomy (v2.1) → metrics stored
    ↓
effectiveness.json updated with before/after waste rates
    ↓
IF post_adoption_rate >= pre_adoption_rate → rule flagged INEFFECTIVE
IF post_adoption_rate < 30% of pre → rule flagged EFFECTIVE
IF new pattern with no rule → flagged UNCOVERED, priority = wasted steps
```

This caught 7 additional findings that manual review missed — including the insight that copying files into Antigravity's brain scratch directory pollutes checkpoint metadata.

## Phase 5: Divide & Conquer Optimization ("Work smarter, not harder")

After achieving 5% waste in governance sessions, the focus shifted from *preventing mistakes* to *maximizing throughput*:

- **Session Pre-flight Probe**: A Flash subagent checks venv health, test suite, git state, and display environment at session start — eliminating the #2 and #3 waste categories before any code is written (~500 tokens, <10s).
- **Review Sentinel**: Lightweight Flash reviewer dispatched every ~50 coding steps catches regressions before they compound. In `5dd84eed`, a hallucinated `total_mem` survived 188 steps; with sentinels, it would have been caught at step 73.
- **Disjoint Lane Protocol**: When approved changes touch separate files, parallel subagents execute simultaneously with explicit file ownership. Wall-clock time reduced 2-3x with zero merge conflicts.
- **Configurable Team Profiles**: `aegis.conf` (formerly `soma.conf`) lets teams customize rules for their team size, git strategy, and approval chain — making the system distributable without forking.

**Impact on rules:** Added `session-preflight` skill, Continuous Review to `staff-review`, Disjoint Lane Protocol to `subagent-delegation §2`, and Makefile-based installation with `aegis.conf`.

## Phase 6: Multi-Lens Synthesis & Mechanized Guardrails ("Scale depth and automation")

With low baseline waste established, Phase 6 addressed review depth, context efficiency, and proactive mechanical detection:

- **Vanguard Protocol** *(formerly Trident)*: Progressive 3-prong deep review (`Sentry` → `Probe` → `Bastion`, formerly *Spores → Roots → Bedrock*) separating reconnaissance from root-cause analysis and structural verification. Prevents confirmation bias and scope creep.
- **Bulwark Protocol & Gauntlet** *(formerly Maelstrom & Thorns)*: Full 4-stage adversarial workflow incorporating NASA IV&V tripartite falsification with a 2-cycle revision cap.
- **Unified Defensive Naming**: Unified protocols (`Patrol`, `Sweep`, `Vanguard`, `Bulwark`, `Fortress`, `Citadel`) and prongs (`Sentry`, `Trace`, `Probe`, `Gauntlet`, `Bastion`, `Debrief`) under a cohesive security posture taxonomy (`aegis_core/taxonomy.py`).
- **Risk-Based Protocol Selection**: Automated risk-tiered routing — see [METRICS.md](../project/METRICS.md#review-protocol-output-budgets-6-modes--6-prongs) for cost details.
- **First Successful Bulwark Dogfood**: Gauntlet adversarial prong caught 5 critical bugs that would have shipped broken under traditional review.
- **Schema Bifurcation Fix**: Reconciled disparate transcript field structures in `aegis_core/sweep_session.py` — see [METRICS.md](../project/METRICS.md#aggregate-stats-17-sessions-7015-steps) for aggregate numbers.
- **14 Skills**: Added 5 specialist skills (domain-researcher, spec-synthesizer, session-monitor, governance-auditor, visual-analyst) alongside the 8 original and session-preflight.
- **10-Lens Staff Protocol**: Architecture, Performance, Security, Compliance, Behavioral, Domain Research, Spec Synthesis, Visual, Governance Audit, Live Monitor.
- **Auto-Preflight & Domain Detection**: Zero-token project scanning in `aegis_cli/hooks/` and `aegis_core/sync.py`.
- **Context Pre-Seeding**: ~200-token compact headers eliminating 2–3 cold-start steps per subagent.
- **Experiment Framework (E1–E15)**: Active/backlog registry in [EXPERIMENTS.md](../research/experiments.md).
- **Concurrency Expansion**: 4 readers / 3 writers under Disjoint Lane Protocol; delegation floor lowered from 100 to 75 steps.
- **Governance Sweep**: Local periodic scanning at ~500 tokens / run, zero LLM cost.

**Impact on rules:** Upgraded `staff-review` to support Sweep, Vanguard, & Bulwark across 10 lenses; 14 skills total; Context Pre-Seeding and higher concurrency in `subagent-delegation.md`; automated hooks; and `docs/research/experiments.md`.

## Phase 7: Empirical Falsification & Research-Backed Grounding ("Prove it or lose it")

While Phase 6 established multi-stage reviews and baseline automation, real-world execution revealed subtle multi-agent failure modes: false-positive findings, consensus bias, symptom-patching loops, and unverified subagent drift.

In **Bulwark #2** *(formerly Maelstrom #2)*, state-of-the-art 2026 academic research was incorporated:

1. **Empirical Refutation Gate** — 2-of-3 evidentiary criteria before accepting critical findings. Eliminates ~80% false positives (empirically observed). See [METRICS.md](../project/METRICS.md#review-protocol-output-budgets-6-modes--6-prongs).
2. **Boundary Verification Protocol** — Orchestrator spot-checks with ±5 line locality tolerance. Demote-not-discard policy (IEEE GLOBECOM 2026).
3. **Orthogonal Persona Mandate** — Bans homogeneous reviewer fan-outs; mandates conflicting analytical incentives (MAR/ICML 2026).
4. **Diagnose Before Repair** — Structured diagnostic schema (`failure_mode`, `root_cause`, `broken_invariant`, `fix_spec`) required before any fix code (REFLEX/ICML 2026).
5. **First-Pass Success Rate (FPSR)** — Target >80%, halt at <50% (N≥5). Calibrated against Tencent SiriusDeliver 2026 (87.2%). See [METRICS.md](../project/METRICS.md#first-pass-success-rate-fpsr).
6. **Incremental Escalation** — 4 upgrade paths preserving completed prongs with dirty-tree caveat. Extracted from live post-mortem `f8b82d61`.
7. **Mechanical Diff Downgrade** — Flash-tier for syntactic diff application (~85% reduction).
8. **Validated Concurrency Ceilings** — 4 readers / 3 writers empirically validated against MIT, Tencent, Coasty, Devin, Cursor, Copilot benchmarks.

**Impact on rules:** Empirical falsification in `staff-review`, Boundary Verification and Orthogonal Personas in `subagent-delegation.md`, structured diagnosis in `providence.md`, FPSR and mechanical diff tiering in `cost-optimization.md`.

## Phase 8: Spectrum Completion & Lifecycle Extraction ("Cover every risk tier, learn from every review")

Bulwark #3 expanded the review system in two dimensions: **breadth** (`Patrol` and `Fortress`, formerly *Breeze* and *Tempest*, at both ends of the risk spectrum) and **depth** (`Trace` and `Debrief`, formerly *Mycelium* and *Mulch* prongs). Triple convergence from 3 Sentry scouts, Gauntlet-verified (0/4 survived, all fixed), Bastion SHIP.

1. **Patrol Protocol** *(formerly Breeze)* — Lightweight targeted-fix mode for known defects. Skips Sentry; BLOCK auto-escalates to Vanguard.
2. **Fortress Protocol** *(formerly Tempest)* — High-assurance 6-prong pipeline with human gate via `ask_question` before Bastion verdict.
3. **Trace Prong** *(formerly Mycelium)* — Blast-radius and dependency mapping (2-hop import chains) inserted between Sentry and Probe.
4. **Debrief Prong** *(formerly Mulch)* — Post-review learning extraction with circuit breaker preventing recursive reviews.
5. **7 Escalation Paths** (up from 4) and **6 Modes / 6 Prongs** — see [staff-review SKILL.md](../../skills/staff-review/SKILL.md) for full details and [METRICS.md](../project/METRICS.md#review-protocol-output-budgets-6-modes--6-prongs) for costs.

**Impact on rules:** Upgraded `staff-review` with Patrol, Fortress, Trace, and Debrief. Updated documentation across README.md and METRICS.md.

## Phase 9: Fortress Hardening — Portability, Security & Documentation

Fortress #1–#4 and Sweep review overhauled the build system, security gate, runtime learning, and documentation:

- **Unified platform adapters** (`aegis_cli/platforms/`) replacing duplicated platform shell scripts
- **Shared core utilities** (`aegis_core/operations.py`, `aegis_core/storage.py`) eliminating duplicated path resolution, error handling, and atomic file operations
- **Dynamic hook configuration** (`aegis_cli/hooks/`) resolving interpreter and workspace paths at install time
- **6 new Make targets**: `info`, `uninstall`, `doctor`, `validate`, `update`, `status` (plus existing `install`, `test`)
- **Safety gate hardened** (`aegis_core/command_safety.py`): fail-closed default, structured lexical command tokenization, wrapper unrolling
- **Documentation consolidated**: METRICS.md merge (token economics + telemetry + benchmarks), README rewrite (242→150 lines), EVOLUTION dedup
- **First operational Debrief**: Runtime learning extraction pipeline with proposals persisted to `governance/debrief_queue.jsonl`
- **Default branch modernization**: Repository migrated from `master` to `main`
- **Git & permissions hygiene**: Expanded `.gitignore`, enforced executable bits on all scripts

**Impact on rules:** Added Mandatory Mechanical Verification for Arithmetic (`providence.md §2`) and Debrief Execution Invariant (`subagent-delegation.md §5`). Consolidated model tiering authority in `cost-optimization.md §3`.

## Phase 10: Autonomous Orchestration & Cross-Conversation Intelligence

Fortress #5 cross-conversation analysis of 2 sessions (2,904 total steps) unlocked subagent nesting, adaptive protocol selection, and empirical experiment validation:

### Subagent Nesting (E11)
- **Discovery**: `define_subagent` supports `enable_subagent_tools: true` — subagents can dispatch their own sub-subagents. E11 was incorrectly marked BLOCKED across multiple prior sessions.
- **Patrol POC**: Review orchestrator autonomously dispatched Probe + Bastion scouts, synthesized findings, and reported back. Zero parent context consumed on coordination.
- **Bulwark POC**: Adaptive reviewer ran full Sentry → Probe → Gauntlet → Probe-Retry → Bastion pipeline (8 dispatches) with auto-escalation based on finding severity. Gauntlet caught 3 broken + 5 weakened fixes before shipping.

### Adaptive Review Orchestrator (E11 + E14)
- **Auto-escalation**: Instead of manually selecting protocols, the orchestrator starts with Sentry and decides escalation level based on empirical findings — 0 🔴 = Sweep, any 🔴 = Vanguard, 2+ 🔴 or security = Bulwark, infra/auth = Fortress.
- **Self-healing**: If Bastion returns BLOCK, orchestrator auto-revises via Probe-Retry (max 1 cycle) without parent intervention.
- **Installed as skill**: `skills/adaptive-reviewer/SKILL.md`.

### Escalation Sentinel (E14)
- **`aegis_core/sentinels.py` & `aegis_core/sync.py`**: Zero-token sentinel classifying files by sensitivity (HIGH: hooks/infra/auth, MEDIUM: rules/code, LOW: docs/README) and recommending minimum protocol level.
- **Phase Gate Enforcement**: `providence.md §9` strengthened with 3 concrete rules extracted from `f8b82d61` post-mortem — "No Coding While Scouting", "Conflicting Commands" serialization, and escalation sentinel integration.
- **Empirical validation**: docs→SWEEP, scripts→BULWARK, single-file→PATROL (100% correct on 3 test cases).

### Bulwark Security & Portability Hardening (13 fixes)
- **Security**: Scoped `git add` staging (S1), safe config parser replacing `source` (S2), chained command gate bypass (S3), Python injection fix (S4), pre-truncation secret redaction (S5), JSON serialization via `python3 json.dumps` (S6).
- **Portability**: `fuser`/`lsof` fallback (P1), 15 POSIX regex conversions (P2), `flock`/`mkdir` fallback across 3 scripts (P3), `date -Iseconds` → POSIX across 5 locations (P4), metadata regeneration gating (P5), `grep -P` removal (P6), dead code cleanup (P7).
- **Gauntlet value proof**: Without adversarial testing, `git add .` would have permanently dropped governance data, config parser would have rejected quoted values, and gate logger would have leaked partial tokens at byte boundaries.

### Cross-Conversation Analysis
- **Experiment signals**: Analyzed E14/E15/E16/E17 across both sessions. Added E16 (consumer) and E17 (max 2 Fortresses/session).
- **Diminishing returns proven**: Fortress #1 found 7 critical breaks; Fortresses #2–#4 found 0. After the first Fortress, every subsequent review found only formatting and count synchronization.
- **f8b82d61 post-mortem**: Phase inversion traced to Step 464 — 3 coding lanes launched while 5 research scouts were active. 16 files of dead code written against obsolete 8-protocol architecture. Led directly to E14 phase gate rules.
- **15 skills, 17 experiments** (E1–E17, 15 allocated).

**Impact on rules:** Phase Gate Enforcement strengthened in `providence.md §9` with 3 concrete anti-patterns. `adaptive-reviewer` skill added. Escalation sentinel wired into `aegis_core/sentinels.py`. E11/E14 advanced to TESTING. E16/E17 proposed.

## The Compound Effect

```
Prescriptive Rules → caught obvious gaps but missed real failure modes
    ↓
Evidence-Based → extracted rules from 1,339 steps of real waste
    ↓
Cross-Conversation → proved patterns are systemic, not one-off
    ↓
Continuous Monitor → catches new patterns as they emerge
    ↓
Divide & Conquer → parallel lanes, preflight probe, review sentinels
    ↓
Vanguard, Bulwark & Mechanized Guardrails → Sweep/Vanguard/Bulwark, 10 lenses, 14 skills, auto-hooks
    ↓
Empirical Falsification & Research Grounding → Refutation Gate, Boundary Verification, Orthogonal Personas, FPSR, Structured Diagnosis
    ↓
Spectrum Completion & Lifecycle Extraction → Patrol/Fortress, Trace/Debrief, 6 modes, 6 prongs, 7 escalation paths
    ↓
Fortress Hardening → Platform adapters, shared core, dynamic hooks, safety gate hardening, docs consolidation
    ↓
Autonomous Orchestration → Subagent nesting, adaptive auto-escalation, escalation sentinel, 15 skills, 17 experiments
```

## Phase 11: Expanded Dataset Analysis & Genesis

Analysis of a new dataset of 66 masked and sanitized production sessions (618 user turns, 4,913 assistant turns, 4,945 tool calls) validated governance effectiveness and exposed critical installer gaps:

### Installer Completeness Fix
- **Root cause**: Legacy installer had a conditional branch that deployed 11 rules but 0 skills. The `doctor` target checked rules but never verified that the skills those rules referenced were installed.
- **Impact**: Security-sensitive code changes executed without any review protocol, when the risk table called for Bulwark.
- **Fix**: All `aegis_cli/platforms/` adapters now deploy rules, skills, and hooks with the same fidelity. `aegis doctor` and `aegis status` verify full coverage.

### 66-Session Masked Dataset
- Date range: 2026-08-10 to 2026-09-27 (~7 weeks)
- Tool distribution: 30.6% execute_bash, 12.4% read_file, 9.2% str_replace
- Delegation evolution: 0 subagents (sessions 1–24) → selective context-gatherers (25–53) → full orchestrated review with 14 subagents (session 53)
- Key finding: delegation was used only for context saving, never for adversarial second opinions, until governance skills were installed

### Genesis Skill (E18)
- 4-stage codebase onboarding reconnaissance: `Perimeter` → `Chronology` → `Blueprint` → `Policy` *(formerly Canopy → Rings → Taproot → Lichen)*
- Read-only reconnaissance: produces structured intelligence artifact, never modifies application code
- Fills gap between `session-preflight` (env health) and `Sentry` (problem survey) — Genesis surveys for *understanding*
- Output feeds Context Pre-Seeding blocks, Sentry priority, Trace blast-radius, and `.aegis/rules/` policy generation

### New Anti-Patterns Discovered
- **Unbounded file ingestion**: Reading large files without line limits crashes context in seconds (Session 001)
- **Terminal echo churn**: Multi-line bash commands failing in interactive shells (Sessions 009, 024, 029)
- **Exit code masking**: Piping to `tail`/`head` masking build failures (Session 053)
- **Silent dead starts**: Sessions with zero execution and no error feedback (Sessions 041, 052)
- **Cross-session amnesia**: Same environmental traps re-discovered independently across sessions

### Historical Naming Milestones
- `ai-steering-rules` → `soma` (v0.11–v1.5) → `aegis-guardrails` / **Aegis Guardrails** (v2.0–v3.2.0)
- 5 new experiments registered (E18–E22), bringing total to 22

**Impact on rules:** Installer completeness fix. `aegis doctor` verifies skills. Genesis skill added (`skills/genesis/SKILL.md`). 5 experiments proposed (E18–E22).

---

## Phase 12: Measurement Integrity & Deep Optimization

**Trigger**: Full Fortress review during Phase 12 planning revealed that all token baselines in METRICS.md were calculated using a word-count heuristic — a method that understated actual costs. A character-class recalibration (×1.97) overcorrected in the opposite direction. Neither was measured against the model's actual tokenizer.

**Key Discovery**: The governance system is structurally sound. The contamination was limited to the token economics presentation layer — 83 values across 8 files. All 11 phases' core claims survived because they were built on step counts and behavioral patterns, not token math.

### Changes
- **Ground-truth token census**: `aegis_core/metrics.py` (`WORDS_TO_TOKENS_FACTOR = 1.35`). Phase 11 baseline: **~3,800 tokens/turn idle overhead**
- **Rule compression**: Providence, subagent-delegation, and cost-optimization compressed by 320 words (~431 tokens/turn) through prose dedup and example tightening. §10 (Fail-Fast Validation) preserved — was misidentified as desktop automation during planning
- **Skill consolidation**: Legacy code review skill merged into `staff-review` (16 → 15 skills) with Sweep aliases and trigger absorption; all 15 skill frontmatter descriptions compressed to ≤15 words. One skill, one escalation ladder
- **Genesis env scanning**: Privacy-first dev environment probes (sanitized outputs only — versions and booleans, not raw paths or usernames)
- **Cross-OS platform adapters**: Native Python platform adapters (`aegis_cli/platforms/`) supporting Linux, macOS, and Windows
- **Metrics infrastructure**: `aegis_core/metrics.py` with privacy invariant, automated baselines, delta comparison
- **ROI reframed**: Step-based instead of token-based. Steps are model-independent; token ROI varies by model and caching
- **Cross-model data separation**: Governed sessions (Gemini) and 66 masked sessions (alternative model family) use different tokenizers — only step-based metrics are valid for cross-dataset comparison
- **Documentation**: 8 cross-reference inconsistencies fixed, 83 contaminated token values replaced, Insight 4 corrected, E11 graduated

**Impact on rules:** Rule compression without semantic loss. Privacy invariant strengthened. Measurement methodology established. 15 skills, 18 core rules (as of v3.2.0).

---

## Phase 13: Adaptive Governance — Policy Generation with Integrated Selection

**Trigger**: Genesis observation was insufficient; it needed synthesis to generate governance extensions tailored to the repo, **with fitness tracking built in from day one**. Lesson from Phase 12: measure first, then optimize. Don't generate rules and evaluate later — build the feedback loop immediately.

### Naming Hierarchy
```
🛡️ POSTURE (Global)      → Modes: Patrol, Sweep, Vanguard, Bulwark, Fortress, Citadel
🔍 OPERATIONS            → Prongs: Sentry, Trace, Probe, Gauntlet, Bastion, Debrief
📐 RULE (Repo-Local)     → Persona, Trap, Invariant, Boundary, Contract, Gate (.aegis/rules/)
```

### Rule Types (`.aegis/rules/`)
| Rule Type *(Legacy Alias)* | Repo-Specific Function | Example |
|:---------------------------|:----------------------|:--------|
| **Persona** *(Chloroplast)* | Repo-specific review personas tuned to the domain | `persona: schema-migration-guardian` |
| **Trap** *(Vacuole)* | Accumulated traps & anti-patterns for this codebase | `"This repo uses build.sh not make"` |
| **Invariant** *(Cell Wall)* | Hard boundaries — things you must never do HERE | `"Never modify auth_config.yaml without security review"` |
| **Boundary** *(Membrane)* | Escalation overrides — what gets auto-Patrolled vs forced-Vanguard | `"Any change to /migrations/ → minimum vanguard"` |
| **Contract** *(Plasmodesmata)* | Cross-repo connections in multi-service architectures | `"Service A feeds Service B via the events table"` |

### Hypothesis Invariant (Design Principle §6)
Every generated rule must be **self-testing**. When `aegis_core/lifecycle/creation.py` or Genesis produces a rule in `.aegis/rules/`, it must also produce:
- **Hypothesis**: What the rule believes about this codebase
- **Prediction**: What it should catch or prevent
- **Falsification**: How to know it's NOT working (e.g., "0 findings in 15 sessions → prune")
- **Expiry**: When to re-evaluate (`expiry_sessions` or `expiry_days`)

### Execution Order (Fitness-First)

| Order | Component | Rationale |
|:-----:|:----------|:----------|
| 1 | **Fitness Infrastructure** (`aegis_core/scoring.py`) | Build the scoring mechanism BEFORE generating anything — Phase 12's lesson |
| 2 | **Traps** (`.aegis/rules/traps/`) | Lowest risk, highest immediate value. Genesis already identifies traps — just persist them |
| 3 | **Invariants + Boundaries** (`.aegis/rules/invariants/`, `.aegis/rules/boundaries/`) | Configuration and hard gates. Simple and immediately useful |
| 4 | **Personas** (`.aegis/rules/personas/`) | Domain accelerators launched with fitness tracking already running |
| 5 | **Selection Cycle** (`aegis_core/lifecycle/selection.py`) | Pruning pass — do Traps and Personas actually help? |

Genesis Stage 4 (`Policy`) generates differentiated rules in `.aegis/rules/` — additive only, never overriding global `rules/` governance.

### Fitness Function

```
fitness(rule) = wilson_lower_bound(true_positives, triggers) × impact_weight
```

Where:
- **true_positives**: Findings that led to actual code changes or prevented verified defects
- **triggers**: All times the rule fired (including false positives)
- **impact_weight**: Severity multiplier — catching a security defect > catching a style issue

### Selection Cycles (`aegis_core/lifecycle/`)

```
Every N sessions (or via aegis rule):
    ↓
For each rule in .aegis/rules/:
    ├── fitness > 0.7           → SURVIVE (keep as-is)
    ├── fitness 0.3–0.7         → ADAPT (refine hypothesis, narrow scope)
    ├── fitness < 0.3           → EXTINCTION (archive / clean)
    └── 0 triggers in N cycles  → DORMANT → EXTINCTION after 1 more cycle
```

**Validation**: E23 (Persona Effectiveness), E24 (Trap Persistence), E25 (Fitness Function Accuracy). See [EXPERIMENTS.md](../research/experiments.md).

**Impact on rules:** Genesis 4-stage pipeline (`Perimeter`, `Chronology`, `Blueprint`, `Policy`). Additive repo-local governance layer in `.aegis/rules/` with integrated self-pruning (`aegis_core/sync.py` and `aegis_core/sentinels.py`).

---

## Phase 14: Evolutionary Dynamics — Cross-Repo Natural Selection

Phase 14 extends Phase 13's local rule generation across repos and over time, enabling the system to discover its own universal rules.

### Evolutionary Mechanisms

| Mechanism | Concept | Governance Function |
|:----------|:--------|:-------------------|
| **Contracts** | Interface treaties | Cross-repo connections — how services relate in multi-repo architectures (`.aegis/rules/contracts/`) |
| **Adaptation** | Trait refinement | Rules refine their scope, phrasing, or thresholds based on accumulated near-miss data |
| **Promotion** | Tiered graduation | Local traps that prove high precision graduate to invariants and gates (`aegis rule promote`) |
| **Phylogenetics** | Lineage tracking | Rule provenance (`lineage.parent_id`, `lineage.created_by`, `lineage.generation`) in `aegis_core/lifecycle/creation.py` |

### The Promotion & Transfer Path
When a rule proves effective, it advances along the local enforcement ladder (`trap` → `invariant` → `gate` via `aegis rule promote`) or transfers across repositories (`aegis_core/lifecycle/creation.py::transfer_cell`, logged in `.aegis/metrics/transfers.jsonl`):

```
.aegis/rules/traps/trap-schema-guardian.md (advisory)
    ↓ catches schema issues with high Wilson lower-bound precision
    ↓ aegis rule promote
.aegis/rules/invariants/invariant-schema-guardian.md (gate enforcement)
```

### Named Anti-Pattern: Write-Only Knowledge Base

A system accumulates lessons, rules, or post-mortems but never closes the loop — knowledge is written to disk but never queried during decisions, never validated against outcomes, and never pruned when proven wrong. Aegis Guardrails' fitness and expiry engine detects this automatically: a rule with zero `triggers` in its `expiry_sessions` window scores null and is archived (`aegis rule clean`).

### Configurable Metrics Infrastructure
Phase 14 includes configurable data paths via `aegis.conf`:

| Config Key | Purpose | Default |
|:-----------|:--------|:--------|
| `METRICS_REPO` | Private repo/directory for metrics snapshots, fitness data, rule telemetry | `docs/snapshots/` (gitignored) |
| `CONVERSATION_LOG_DIR` | Where session transcripts live for sweep analysis | `~/.gemini/antigravity/brain` |
| `GENESIS_REPORT_DIR` | Where Genesis reports are stored and loaded for pre-seeding | `docs/` |

This separation ensures: governance rules are **public** (Apache 2.0 licensed), telemetry data is **private** (user-configurable repo, gitignored by default).

**Validation**: E26 (Promotion Path Validation). See [EXPERIMENTS.md](../research/experiments.md).

## Design Principles (Emerged, Not Prescribed)

1. **Evidence over intuition** — Every rule traces back to observed steps wasted. No rule exists "just in case."
2. **Accuracy over speed** — The agent must never sacrifice correctness to save tokens.
3. **Rules as a system** — Cross-references between rules are intentional. Providence §3 mandates read-before-write; refactoring-pilot operationalizes it as a phased workflow.
4. **Continuous validation** — Rules aren't "done" after review. Governance is a living system that evolves with each session.
5. **Installation completeness** — Governance installed at partial fidelity provides false assurance. Every installer path must deploy rules, skills, and hooks with the same completeness.
6. **Hypothesis-driven governance** — Every governance extension must carry its own falsifiability criteria. Generated rules in `.aegis/rules/` must specify what they predict, how to measure it, and when to prune if unvalidated.

---

## Phase 15: Team Topology & Clean Uninstaller

- Team governance convergence: `TEAM_REPO` and `ORG_REPO` in `aegis.conf`
- Three-tier hierarchy: Individual → Team → Organization
- `aegis_core/sync.py` team sync and post-session hooks
- Clean uninstaller (`aegis uninstall`) with backup/restore and platform adapter cleanup (`aegis_cli/platforms/`)
- Privacy: only rule hypotheses/scores flow — never file content, paths, or PII

### Phase 15.1: Cross-Domain Insights (RL Training & Production Gaps)
- **Liveness Sentinel**: Added subagent deadlock monitoring (`aegis_core/sentinels.py`) after discovering silent deadlocks during multi-agent orchestration.
- **Enhanced Policy Magic Number Detection**: Added explicit detection for high-density hardcoded numeric literals (coordinates, ports, timeouts) to identify structural brittleness for Trap generation.
- **Enhanced Contract Detection**: Added explicit patterns for multi-service connections, including `pip install -e` sibling references, shared DBs, and protobuf/gRPC imports.

## Phase 16: Checkpoint System (`aegis check` / `aegis checkpoint`)

Heavy multi-prong reviews and full test executions created inner-loop friction, tempting agents to bypass checks on routine edits while missing basic syntax errors or bare `pass` placeholders.

- **Deterministic AST Gate**: `aegis check` (`aegis_cli/check.py`, `aegis_core/verification/checkpoint_checks.py`) analyzes AST structure in milliseconds with zero LLM overhead, verifying assertion density, import integrity, and placeholder absence.
- **Pre-Commit Integration**: Placed directly at the git boundary (`install/hooks/pre-commit`) to block malformed commits before code enters version control.
- **Why it matters**: Shifted baseline hygiene from slow, probabilistic model review to observable deterministic linting, ensuring code satisfies structural invariants before higher-tier reviews trigger.

## Phase 17: Evolutionary Computation & Rule Lineage

Formalized Aegis Guardrails' evolutionary operators in `aegis_core/lifecycle/`:

- **GA Operators (`aegis_core/lifecycle/selection.py`)**: Crossover merges complementary rule hypotheses; tournament selection preserves population diversity during pruning.
- **Confidence Decay (`aegis_core/lifecycle/decay.py`)**: Rule fitness decays exponentially unless reinforced by new evidence.
- **Tiered Rule Promotion (`aegis_core/lifecycle/promotion.py`)**: Rules mature between tiers through proof (`trap` → `invariant` → `gate` via `aegis rule promote`).
- **Cross-Project Rule Transfer (`aegis_core/lifecycle/creation.py`)**: Rules can be transferred across projects with fitness reset, `lineage.generation` increment, `lineage.created_by: "transfer"`, and audit logging to `.aegis/metrics/transfers.jsonl`. Transferred rules receive a probation period to prove themselves in the new context.
- **Effector & Memory Rules (`aegis_core/lifecycle/creation.py`)**: Effector rules provide acute protection during incidents (3 sessions, 3.0x weight, `fortress` minimum mode) before decaying into dormant memory boundaries.
- **Fitness Landscape Visualization (`aegis_sdk/analysis.py`)**: Dashboard showing decayed fitness across all active rules in `.aegis/rules/`.

## Phase 18: Oracle Maturation (`aegis_core/proposals.py`)

Static governance rules in `rules/.oracles/` drifted silently over time: without runtime telemetry, the system could not differentiate between high-value invariants, dormant rules, and noisy false-alarm generators.

- **Empirical Classification**: Classifies rules into four behavioral states: `HEALTHY` (high precision), `NOISY` (excess false positives), `EXPIRED` (past expiry limit), and `UNOBSERVED` (zero triggers).
- **Behavioral Grounding**: Ties rule validity directly to execution telemetry rather than author intuition.

## Phase 19: Rule Promotion & Demotion Workflows (`aegis rule`)

Manual rule maintenance created governance stagnation: high-value repo-local Traps remained advisory, while noisy rules lingered without consequence.

- **Automated Lifecycle Transitions**: `aegis rule` (`list`, `promote`, `demote`, `archive`, `clean` in `aegis_cli/rule.py` and `aegis_core/lifecycle/promotion.py`) operationalizes the `trap` → `invariant` → `gate` ladder.
- **Objective Criteria**: Mandates strict empirical gates (≥20 triggers, >0.85 true-positive rate, >30 days maturity) for promotion, with automatic demotion for high false-positive rates (>0.5) or dormancy.

## Phase 20: Evidence Pipeline (`.aegis/evidence/signals.jsonl`)

Persisting fitness scores directly in rule YAML frontmatter created merge conflicts, noisy git diffs, and enabled agents to game their own evaluations by editing frontmatter scores directly.

- **Decoupled Append-Only Ledgers**: Telemetry moved to `.aegis/evidence/signals.jsonl` and `outcomes.jsonl`, managed by `aegis_core/evidence.py`, `aegis_core/evidence_collector.py`, and `aegis_core/telemetry.py`.
- **External Signal Grounding**: Scores derive from verifiable external signals (test exit codes, build results, git reverts) rather than agent self-declarations.

## Phase 21: Transcript Verification (`aegis_core/verification/transcript_verifier.py`)

Agents frequently hallucinate compliance in completion summaries—claiming tests passed or refactors succeeded when transcripts reveal skipped executions, test deletions, or unhandled errors.

- **Post-Hoc Transcript Audit**: `aegis_core/verification/transcript_verifier.py` parses raw session JSONL logs to cross-reference every self-reported claim against actual tool inputs and outputs.
- **Two-Layer Architecture**: Combines deterministic AST log checks (Layer 1) with an adversarial prompt evaluator (Layer 2) to detect rationalization and reward-hacking.

## Phase 22: MCP Gateway (`aegis_mcp/`)

- **MCP Server**: Aegis Guardrails exposed natively via Model Context Protocol (`aegis_mcp`), allowing zero-API-key integration with Gemini/Antigravity, Claude Code, Cursor, GitHub Copilot, Kiro, and any MCP-compatible agent.
- **Aggressive Subagent Delegation**: Enabled concurrent subagent lanes resulting in 97.3% FPSR.

## Phase 23-25: Test-Time Compute (TTC) Oracles & JIT Context (`aegis_mcp/jit_engine.py`)

- **TTC Oracles (`aegis_core/proposals.py`)**: Pre-execution verification of tool calls to eradicate hallucinated commands and rework loops.
- **JIT Context Clamping (`aegis_mcp/jit_engine.py`)**: Token-budgeted rule expression (`JIT_DEFAULT_MAX_TOKENS = 2000`) prioritizing `invariant` and `gate` rules.

## Phase 26-30: Resilience & Signal Coherence (`aegis_core/resilience.py`)

- **Internal Health & Resilience Engine (`aegis_core/resilience.py`)**: Monitors cognitive load across token density, file entanglement, dependency depth, and coherence decay, triggering a Graceful Reset when consecutive failures cross thresholds.
- **Signal Coherence & Ground Truth (`aegis_core/outcomes/`)**: Catches reward hacking through pairwise signal contradiction and captures verifiable execution feedback (pytest exit codes, git reverts).

## Phase 31-35: Two-Layer Verification Foundation & Adversarial Partitioning (`aegis_core/verification/`)

- **Layer 1 (`DeterministicVerifier`)**: Objective analyzers (`persistence_checker.py`, `branch_coverage.py`, `import_guard.py`, `call_graph.py`, `mutation_tester.py`) gather observable boolean `ToolEvidence`.
- **Layer 2 (`AdversarialVerifier`)**: Isolates a Spec Agent (sees requirements) from a Code Agent (sees implementation) in `aegis_core/verification/adversarial_verify.py`.
- **Deterministic `Arbiter` (`aegis_core/verification/arbiter.py`)**: Evaluates evidence across a 14-category risk taxonomy via `VerificationPipeline`, issuing `SHIP`, `BLOCK`, or `REVISE` verdicts.

## Phase 36-45: Rule Expiry, Behavioral Test Suites & Quality Gates

- **Rule Expiry Engine (`aegis_core/defects.py`, `aegis_core/lifecycle/decay.py`)**: Enforces `RULE_EXPIRY_DAYS = 90` and session windows, automatically archiving dormant or ineffective rules.
- **AST Test Quality Gate (`aegis_core/verification/quality_gate.py`)**: Statically enforces test quality invariants: bare `pass` elimination, assertion density thresholds, and anti-skip guards.

## Phase 46-60: Mechanism Design, Unified CLI, Gitflow Gate & Citadel Reviews

- **Mechanism Design Framework**: Codified `docs/architecture/mechanism_design.md`, mapping governance primitives (`trap`, `invariant`, `boundary`, `ReceiptManager`, `VerificationPipeline`, `Arbiter`) to formal mechanism design.
- **Unified CLI Suite (`aegis_cli/`)**: Core commands (`aegis init`, `aegis status`, `aegis check`, `aegis rule`, `aegis system`, `aegis migrate`, `aegis report`, `aegis doctor`).
- **Gitflow Review Gate (`rules/gitflow-review-gate.md`)**: Enforces structural separation between authoring and reviewing contexts across `feat/*` → `develop` → `release/vX.Y.Z` → `main`.
- **Citadel Review Protocol** *(formerly Supercell)*: Apex review intensity tier above Fortress employing adversarial Prosecutor/Defender pairs per prong with zero allowed deferrals.

## Phase 61-75: Multi-Runtime CI, Evidence Sync (`aegis sync`), SDK & Credit Assignment

- **Evidence Ledger Sync (`aegis sync`, `aegis_cli/sync.py`)**: Reconciles `.aegis/evidence/signals.jsonl` into rule YAML frontmatter in `.aegis/rules/`.
- **SDK Foundation (`aegis_sdk/`)**: Canonical Python library — `errors.py`, `scoring.py` (Wilson interval confidence bounds), `rules.py` (`Rule`, `RuleFitness`), `governance.py` (`Governance`), `invariants.py`, `telemetry.py`.
- **Claim Registry Verification (`aegis_core/enforcement.py`)**: `verify_readme_claims()` cross-references `docs/project/CLAIM_REGISTRY.json` against passing behavioral tests.
- **Credit Assignment (`aegis_core/telemetry.py`, `aegis_core/attribution.py`)**: `prob_round()` probabilistic rounding and `compute_credit_weights()` per-file scope narrowing with credit conservation.

## v1.0.0–v1.5.1: Production GA, Polyglot Normalized AST Drivers & Delegation Governance

- **Zero-Dependency `AegisYAML` (`aegis_core/yaml.py`, ADR-012)**: Pure-stdlib YAML frontmatter parser and serializer (`dependencies = []` in `pyproject.toml`).
- **In-Process Governance (`aegis_sdk/`, `aegis_core/`, ADR-013)**: 100% pure-Python in-process execution across CLI, SDK, and MCP without shell enzyme subprocesses.
- **Lexical Command Safety (`aegis_core/command_safety.py`, ADR-014)**: `CommandAnalyzer` using `shlex` tokenization and wrapper unrolling (`sudo`, `env`, `nohup`, subshells) over brittle regexes.
- **Normalized AST Driver (NAD) Protocol & Zero-Touch Polyglot Provisioning (`aegis_core/ast/`, ADR-015 & ADR-016)**: Language-agnostic AST verification for Python, TypeScript/JavaScript, Go, and Rust with automatic `.aegis/slots.yaml` provisioning via `aegis init`, `aegis detect`, and `aegis doctor --fix`.

## v2.0.0–v3.2.0: Pure Aegis Architecture, Burn-Before-Compare Receipts & Canonical Taxonomy

- **Soma-to-Aegis Cutover & `aegis migrate` (`aegis_cli/migrate.py`)**: Clean-slate `aegis_core`, `aegis_cli`, `aegis_mcp`, and `aegis_sdk` packages with atomic `.soma/` → `.aegis/` workspace migration.
- **Burn-Before-Compare Cryptographic Receipts (`aegis_core/receipts.py`, `aegis_mcp/server.py`)**: Single-use HMAC-SHA256 receipts under `.aegis/locks/receipts.lock` sidecar locking that burn nonces to `.aegis/receipts.jsonl` *before* comparing file and rule digests, eliminating replay vectors.
- **Canonical 17-Tool MCP Control Plane (`aegis_mcp/registry.py`, `aegis_mcp/tools.py`)**: Streamlined `aegis_*` tool surface across Read, Write (receipt-required), and Execute (opt-in, receipt-required) tiers.
- **Canonical Defensive Taxonomy (`aegis_core/taxonomy.py`)**: Unified review modes (`Patrol`–`Citadel`), prongs (`Sentry`–`Debrief`), Genesis stages (`Perimeter`–`Policy`), and rule types (`invariant`, `trap`, `gate`, `boundary`, `persona`, `contract`) across all 18 core rules and 15 agent skills.


# Formal Framework: Mechanism Design Mapping

> **Purpose**: This document maps **Aegis Guardrails** (v3.2.0) governance, verification, and rule lifecycle concepts—along with their historical Soma aliases—to formal mechanism design concepts. Agents working in the codebase should reference this to understand the theoretical intent behind each component, not just its implementation.

---

## Term Mapping

### Directory & Package Structure

| Codebase (`aegis-guardrails` v3.2.0) | Formal Concept (Mechanism Design) | What It Actually Does |
|:---|:---|:---|
| `rules/` *(legacy `genome/`)* | **Constitutional rules** | Immutable foundational governance — rarely amended, high legitimacy cost to change |
| `aegis_core/` & `aegis_cli/` *(legacy `enzymes/`)* | **Institutional procedures** | Pure-Python enforcement, scoring, and measurement modules — the operational machinery of governance |
| `skills/` *(legacy `organs/`)* | **Institutional capabilities** | Complex multi-step competencies (audit, staff review, onboarding reconnaissance) — what the governance system *can do* |
| `aegis_core/verification/` *(legacy `immune_system/`)* | **Oversight institution** | Independent verification body (`VerificationPipeline`, `Arbiter`, `DeterministicVerifier`, `AdversarialVerifier`) — structurally separated from the governed entity |
| `aegis_core/receipts.py` (`ReceiptManager`) | **Cryptographic commitment / authorization** | State-bound, burn-before-compare HMAC-SHA256 receipts binding `aegis_scan` governance inspection to file and rule digests before write/execute tool execution |
| `.aegis/rules/` *(legacy `.soma/cells/`)* | **Adaptive policy layer** | Per-repository regulatory instruments (`invariants/`, `traps/`, `gates/`, `boundaries/`, `personas/`, `contracts/`) — generated, tested, evolved, or sunset |
| `.aegis/` *(legacy `.soma/`)* | **Regulatory state** | Persistent governance artifacts, evidence ledgers (`.aegis/evidence/signals.jsonl`), and cryptographic locks for a specific jurisdiction (repository) |

### Adaptive Rule Types (`aegis_core/taxonomy.py`)

| Codebase Rule Type | Formal Concept | Mechanism Design Role |
|:---|:---|:---|
| **Trap** (`trap`, *legacy Vacuole*) | **Precedent / trap rule** | Encodes a known failure mode as a falsifiable hypothesis. Analogous to case law — "this specific thing went wrong, don't repeat it." |
| **Persona / Method** (`persona`, *legacy Chloroplast*) | **Best-practice norm** | Encodes an observed success pattern or domain specialist lens. Analogous to professional standards — "this method worked, propagate it." |
| **Invariant** (`invariant`, *legacy Cell Wall*) | **Hard constraint / invariant** | Non-negotiable safety boundary. Analogous to constitutional amendment — highest policy tier, prioritized first in JIT context budgets. |
| **Boundary** (`boundary`, *legacy Membrane*) | **Escalation trigger** | Sensitivity classifier that activates elevated review modes when specific paths change. Analogous to mandatory regulatory review for sensitive sectors. |
| **Contract** (`contract`, *legacy Plasmodesmata*) | **Interface contract** | Cross-service data shape and API agreement. Analogous to treaty — governs interactions between independent jurisdictions. |
| **Gate** (`gate`) | **Mechanical compliance gate** | Deterministic AST or invariant DSL check enforced at pre-commit and CI (`aegis check`). |

### Evolutionary & Lifecycle Operators (`aegis_core/lifecycle/`)

| Codebase Operator | Formal Concept | What It Addresses |
|:---|:---|:---|
| **Fitness scoring (`aegis_core/scoring.py`)** | **Performance evaluation** | Measures rule effectiveness via Wilson score lower-bound confidence intervals and signal-to-noise ratio (SNR). |
| **Confidence decay (`aegis_core/lifecycle/decay.py`)** | **Sunset clause** | Rules expire (`RULE_EXPIRY_DAYS = 90`) or decay unless actively reinforced by empirical triggers. Prevents bureaucratic ossification. |
| **Selection / tournament (`aegis_core/lifecycle/selection.py`)** | **Competitive evaluation** | Diversity-preserving selection among candidate rules. Prevents monoculture in the policy landscape. |
| **Crossover (`aegis_core/lifecycle/selection.py`)** | **Policy synthesis** | Merges high-performing rules from complementary contexts. Analogous to synthesizing regulations across jurisdictions. |
| **Tiered promotion (`aegis rule promote`)** | **Regulatory promotion** | A rule earns a higher enforcement tier (`advisory` → `invariant` → `gate`) through demonstrated empirical effectiveness (`aegis_core/lifecycle/promotion.py`). |
| **Rule transfer (`aegis_core/lifecycle/creation.py`)** | **Policy import** | Importing rules from external repositories with a probation period (`.aegis/metrics/transfers.jsonl`). Analogous to adopting foreign regulatory frameworks with local adaptation. |
| **Pruning / archive (`aegis rule archive` / `clean`)** | **Regulatory repeal** | Archiving or removing rules that fail to demonstrate effectiveness. The enforcement of sunset clauses. |
| **Genesis Policy generation (`skills/genesis/`)** | **Rule generation** | Scanning a codebase across 4 stages (`Perimeter`, `Chronology`, `Blueprint`, `Policy`) to generate repository-specific governance rules in `.aegis/rules/`. |
| **Gate enforcement (`aegis_core/enforcement.py`)** | **Mechanical compliance** | Pre-commit hooks (`install/hooks/pre-commit`) and `aegis check` invariant DSL checks for rules reaching gate enforcement tiers. |

### Verification Architecture (`aegis_core/verification/`)

| Codebase Component | Formal Concept | Mechanism Design Property |
|:---|:---|:---|
| **Layer 1: `DeterministicVerifier`** | **Objective audit** | Produces observable `ToolEvidence` (AST call graph, branch coverage, mutation testing, persistence, import guards). The auditor cannot exercise subjective discretion on what counts. |
| **Layer 2: `AdversarialVerifier`** | **Adversarial proceeding** | Information-partitioned Spec Agent (prosecutor) vs. Code Agent (defender) who cannot collude. Directly implements **information asymmetry exploitation** — agreement between partitioned agents is meaningful evidence. |
| **`Arbiter` (`aegis_core/verification/arbiter.py`)** | **Mechanical adjudication** | Deterministic verdict (`SHIP`, `REVISE`, `BLOCK`) from Layer 1 and Layer 2 outputs via `VerificationPipeline`. Removes judicial discretion — the adjudicator applies fixed set-algebra rules to structured inputs. |
| **`ReceiptManager` (`aegis_core/receipts.py`)** | **State-bound commitment** | Burn-before-compare single-use cryptographic receipts ensure agents cannot mutate governed files without first scanning active rules for the exact target file digest. |
| **`transcript_verifier.py`** | **Post-hoc audit** | Independently verifies self-reported claims against execution JSONL logs. Implements a **revelation mechanism** — agents cannot benefit from misreporting because claims are checked against the tape. |
| **Escaped defect tracking (`aegis_core/defects.py`)** | **External ground truth** | CI/CD exit codes and bug registry records provide signals outside the governance system's control. Breaks the **self-evaluation loop**. |

### Review Intensity (`aegis_core/taxonomy.py::ReviewMode`)

| Canonical Mode *(Legacy Alias)* | Formal Concept | When Applied |
|:---|:---|:---|
| **Patrol** *(Breeze)* | Expedited review | Low-risk, known-pattern changes |
| **Sweep** *(Gale)* | Standard review | Routine changes |
| **Vanguard** *(Trident)* | Enhanced review | Features, multi-file refactors |
| **Bulwark** *(Maelstrom)* | Intensive review | Architecture, security-sensitive paths |
| **Fortress** *(Tempest)* | Maximum assurance | High-risk infrastructure/auth changes, human gate required |
| **Citadel** *(Supercell)* | Apex assurance | Adversarial Prosecutor/Defender pairs per prong, zero deferrals, mandatory re-validation |

### Review Prongs (`aegis_core/taxonomy.py::ReviewProng`)

| Canonical Prong *(Legacy Alias)* | Formal Concept |
|:---|:---|
| **Sentry** *(Spores)* | Preliminary survey — width-first problem identification |
| **Trace** *(Mycelium)* | Impact analysis — 2-hop blast radius mapping |
| **Probe** *(Roots)* | Root-cause investigation — depth-first analysis and concrete fix specs |
| **Gauntlet** *(Thorns)* | Adversarial falsification — red-team refutation |
| **Bastion** *(Bedrock)* | Final gate — binary `SHIP` / `BLOCK` decision |
| **Debrief** *(Mulch)* | Learning extraction — post-decision knowledge capture to `governance/debrief_queue.jsonl` |

---

## Mechanism Design Analysis: What Aegis Guardrails Implements

### Properties Aegis Guardrails HAS:

1. **Information asymmetry exploitation** (Layer 2 `AdversarialVerifier`)
   - Two reviewers see different inputs (Spec Agent sees plan/requirements; Code Agent sees diff/tests) → agreement is evidence, not collusion.
   - Orchestrated by `VerificationPipeline` with deterministic `Arbiter` adjudication.

2. **State-bound pre-execution commitment** (`ReceiptManager`)
   - MCP write/execute tools require a single-use HMAC-SHA256 receipt issued by `aegis_scan` and bound to the workspace, target file digest, and active rule inventory fingerprint.
   - Burn-before-compare verification prevents replay attacks even when digest comparisons fail.

3. **Post-hoc revelation mechanism** (`transcript_verifier.py`)
   - Agents cannot benefit from false self-reports because claims are verified against execution transcripts.
   - Partial strategy-proofness: lying about test execution or file edits is mechanically detectable.

4. **Sunset provisions** (Confidence decay & `RULE_EXPIRY_DAYS`)
   - Rules in `.aegis/rules/` that aren't reinforced by empirical evidence decay and expire automatically.
   - Prevents institutional accumulation of dead regulations.

5. **Graduated enforcement** (Tiered promotion: `trap` → `invariant` → `gate`)
   - Rules earn enforcement power through demonstrated Wilson-bounded precision.
   - Low-confidence rules advise; high-confidence rules mechanically block commits (`aegis check`).

6. **External ground truth** (Escaped defect tracking & `aegis report`)
   - CI/CD exit codes and git revert detection provide signals the governance system cannot manufacture.
   - Breaks the self-grading loop via closed-loop attribution (`aegis_core/attribution.py`).

7. **Budget balance** (Token economics / JIT Context Budget)
   - JIT context clamping (`JIT_DEFAULT_MAX_TOKENS = 2000`) and conditional rule loading keep governance overhead measurably smaller than prevented rework waste.

---

## Mechanism Design Analysis: What Aegis Guardrails is MISSING

> [!IMPORTANT]
> These are structural gaps visible only through the mechanism design lens.
> They represent the difference between "governance that works because the
> LLM happens to comply" and "governance that works because compliance is
> provably optimal."

### 1. Incomplete Incentive Compatibility

**The gap**: While `ReceiptManager` makes calling `aegis_scan` mandatory for MCP mutations, in-context rule compliance still relies on attention in the context window rather than intrinsic utility maximization for the model. When prompt pressure exceeds governance pressure outside MCP-confined tools, compliance can degrade.

**What mechanism design would prescribe**: Make compliance the dominant strategy by coupling every rule to fast deterministic feedback (`aegis check`) and pre-seeded target constraints so following the rule is always the shortest path to task completion.

### 2. Proxy Social Welfare Function

**The gap**: Aegis Guardrails optimizes for low waste rate, high First-Pass Success Rate (FPSR), and high rule Wilson lower bounds, which are proxy metrics for the true objective: task completion, code correctness, and user satisfaction.

**What mechanism design would prescribe**: Define the social welfare function explicitly: `W = task_completion × code_quality × (1 / cost)`, ensuring efficiency metrics are always evaluated conditionally on verified task completion (`VerificationPipeline` `SHIP` verdict).

### 3. Strategic Minimalism Risk

**The gap**: The transcript verifier catches *lies about execution*, and Layer 2 catches *spec-to-code divergences*, but an agent could still attempt to produce minimal, overly conservative changes to avoid triggering rules.

**What mechanism design would prescribe**: Couple rule fitness and verification to complete specification satisfaction (enforced by the Spec Agent in `AdversarialVerifier`), ensuring under-delivery is penalized equally with rule violation.

### 4. Limited Agent-Tier Discrimination

**The gap**: While `cost-optimization.md` and `subagent-delegation.md` partition tasks by model capability tier (`flash` vs. `inherit` vs. orchestrator), `.aegis/rules/` JIT expression does not yet dynamically scale rule verbosity or token budgets based on the calling model's prior defect rate.

**What mechanism design would prescribe**: Bayesian type-conditional governance — adjust JIT rule budget, enforcement strictness, and initial `ReviewMode` intensity based on empirical per-model-tier reliability profiles.

### 5. Bilateral Contract Formalization

**The gap**: Governance primarily constrains the agent, whereas vague or contradictory user prompts also generate rework loops.

**What mechanism design would prescribe**: Bilateral commitment devices — formalizing `providence.md §1` ("Fail Loudly" / assumption surfacing) as a pre-execution specification completeness check before multi-file implementation begins.

---

## Implications for Development

When working in this codebase, understand that:

1. **"Fitness" is a proxy metric, not a welfare function.** Don't optimize rule fitness in `aegis_core/scoring.py` without checking that code quality and task completion are served.
2. **Mechanical gates beat prose.** Whenever a `trap` or `invariant` rule can be expressed deterministically in `aegis_core/enforcement.py` or `aegis_core/verification/`, promote it to a mechanical check rather than relying solely on prompt attention.
3. **`VerificationPipeline` + `Arbiter` + `ReceiptManager` form the core mechanism design pillar.** Information partitioning, deterministic arbitration, and state-bound cryptographic receipts are Aegis Guardrails' strongest formal guarantees—protect their structural independence.
4. **The remaining frontier** (type-conditional JIT budgets, formal welfare functions, repeated-game model reputation) represents research opportunities bridging empirical agent governance and provable mechanism design.


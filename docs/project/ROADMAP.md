# Aegis Guardrails — Roadmap

> Features listed under **Research** are planned or experimental. Shipped milestones document verified capabilities backed by behavioral tests and `docs/project/CLAIM_REGISTRY.json`.
> A feature moves to the README only when:
> 1. Its behavioral test suite is written
> 2. All tests pass
> 3. It has a Claim Registry entry with status `unlocked`

## Shipped Features

### Layer 2 Verification (`VerificationPipeline` & `Arbiter`)
**Status**: ✅ SHIPPED (v0.60; unified in v3.2.0)  
AST-based Layer 1 verification tools (`DeterministicVerifier`) paired with information-partitioned Layer 2 evaluation (`AdversarialVerifier`) and deterministic `Arbiter` adjudication.

### Transcript Verifier
**Status**: ✅ SHIPPED (v0.60)  
Verify agent conversation transcripts against governance rules (`aegis_core/verification/transcript_verifier.py`).

### Genesis
**Status**: ✅ SHIPPED (v0.70; 4-stage `Perimeter` → `Policy` in v3.1.0)  
Automated codebase reconnaissance and `.aegis/rules/` governance rule candidate generation.

### Review Intensity Levels (Patrol → Citadel, formerly Breeze → Supercell)
**Status**: ✅ SHIPPED (v0.60; canonical Aegis taxonomy in v3.1.0)  
Dynamic review depth escalation (`Patrol`, `Sweep`, `Vanguard`, `Bulwark`, `Fortress`, `Citadel`) based on diff risk assessment.

### Phase 1 — Stop the Bleeding
**Status**: ✅ SHIPPED (v0.73)  
README stripped to earned claims, hook fix, claim registry, roadmap/release workflow docs.

### Phase 2 — Foundation
**Status**: ✅ SHIPPED (v0.74)  
Canonical cell parser, Wilson-bounded scoring, error hierarchy, 27-file parser migration.

## Phase 3 — v0.75 ✅ Shipped

### Credit Assignment
**Status**: ✅ Shipped (v0.75)  
**Tracking**: `claim_credit_assignment` in `docs/project/CLAIM_REGISTRY.json`  
Attribute session outcomes to the specific cells that fired, enabling causal fitness updates.

### Crossover (Structured Rule Merging)
**Status**: ✅ Shipped (v0.75)  
**Tracking**: `claim_structured_crossover` in `docs/project/CLAIM_REGISTRY.json`  
Field-level merge of parent cell attributes to create hybrid rules.

### Tournament Selection
**Status**: ✅ Shipped (v0.75)  
**Tracking**: `claim_tournament_selection` in `docs/project/CLAIM_REGISTRY.json`  
Competitive evaluation between rules to select higher-fitness survivors.

## Phase 4 — v0.80 ✅ Shipped

### Quorum Sensing (Multi-Rule Consensus)
**Status**: ✅ Shipped (v0.80)  
**Tracking**: `claim_quorum_sensing` in `docs/project/CLAIM_REGISTRY.json`  
Require agreement from multiple rules before taking high-stakes actions.

### Gate Enforcement (Invariant DSL)
**Status**: ✅ Shipped (v0.80)  
**Tracking**: `claim_gate_enforcement` in `docs/project/CLAIM_REGISTRY.json`  
CI-required invariant checks defined in cell YAML frontmatter.

## Phase 4.5 — v0.81 ✅ Shipped

### CI Outcome Reporter
**Status**: ✅ Shipped (v0.81)  
**Tracking**: CI step summary integration  
Report-only advisory showing which cells match changed files in PRs.

### Telemetry Consolidation
**Status**: ✅ Shipped (v0.81)  
Unified signal evidence writer and 3 telemetry bug fixes.

## Phase 4.6 — v0.82 ✅ Shipped

### Writer Migration
**Status**: ✅ Shipped (v0.82)  
Migrate all fitness signal writers to unified telemetry path.

### Documentation Reconciliation  
**Status**: ✅ Shipped (v0.82)  
Update ROADMAP and README to match shipped state.

## Phase 4.7 — v0.83 ✅ Shipped

### JIT Cell Cache
**Status**: ✅ Shipped (v0.83; hardened in v0.89)  
Content-fingerprinted in-memory cache for the MCP hot path. The canonical inventory captures exact bytes, rejects symlinked cell trees, detects concurrent changes, and invalidates even when an edit restores a file's mtime.

## Phase 4.8 — v0.84 ✅ Shipped

### Bug Registry
**Status**: ✅ Shipped (v0.84)  
Machine-parseable bug registry with verification enzyme and governance cell. Backfilled Bugs 1–5.

## Phase 4.9 — v0.85 ✅ Shipped

### Antifragile Hot Zones
**Status**: ✅ Shipped (v0.85)  
Hot zone engine feeds bug patterns into cell fitness scoring. Bugs make the system smarter.

## Phase 5.0 — v0.89.0 ✅ Shipped

### MCP Execution Security
**Status**: ✅ Shipped (v0.89.0)  
Opaque, stateful, session-bound cryptographic receipts. MCP write/execute tools safely verify client authority and enforce strict workspace confinement.

### Bug Registry
**Status**: ✅ Shipped (v0.89.0)
Open bug tracking, Windows/MCP platform compatibility categorizations.

## Phase 5.1 — v0.93.0 ✅ Shipped

### Autonomous Cell Lifecycle
**Status**: ✅ Shipped (v0.93.0)  
Unified cell lifecycle state machine (`NEW`, `SURVIVE`, `ADAPT`, `EXTINCT`, `APOPTOSIS`, `WALL`, `GENOME`) with Laplace-smoothed scoring, Wilson confidence bounds, protected rules guards, and atomic rollback semantics.

### Multi-Platform Hook Parity
**Status**: ✅ Shipped (v0.93.0)  
Native cross-platform lifecycle hook runner (`soma hook <phase>`) providing 100% parity across Linux, macOS, and native Windows (PowerShell 5.1 / 7). Resolved BUG-014 (UTF-8 encoding / BOM) and BUG-032 (lifecycle hooks). All 69 registered bugs verified fixed.

### Asynchronous Verification Engine
**Status**: ✅ Shipped (v0.93.0)  
Non-blocking Layer 2 verification over MCP (`soma_verify_changes` with `async_mode`) and read-only polling (`soma_poll_verification`) with m8ven annotations.

## Phase 5.2 — v0.94.0 ✅ Shipped

### Operational Resilience & Self-Healing
**Status**: ✅ Shipped (v0.94.0)  
Cross-process and thread-safe file locking (`soma_core/locking.py`) with stale lockfile recovery (>60s), self-healing file quarantine (`soma_core/quarantine.py`) isolating corrupt JSON/YAML state without read failures, and graceful daemon worker lifecycle management (`soma_core/verification_jobs.py`).

### Mathematical Invariants & Property-Based Verification
**Status**: ✅ Shipped (v0.94.0)  
Hardened Wilson score intervals and Laplace smoothing validated through exhaustive Hypothesis property-based testing (`tests/test_math_properties.py`), typed domain error hierarchy (`soma_core/errors.py`), and idempotent state transitions (`tests/test_idempotency.py`).

### Zero-Overhead Optimization & Pure-Python Enzymes
**Status**: ✅ Shipped (v0.94.0)  
Sub-0.1ms safety-gate fast-path allow-list for read-only commands (0.087ms mean latency), zero-copy directory scanning via `os.scandir`, parallelized test execution via `pytest-xdist` (3.9x speedup: 71s down to 18s), and complete pure-Python migration of 12 utility enzymes with backwards-compatible shell delegations.

## Phase 5.3 — v0.94.1 ✅ Shipped

### Concurrency Integrity & Reentrant Locking
**Status**: ✅ Shipped (v0.94.1)  
Thread-local recursion tracking (`_THREAD_STATE`) in `soma_core/locking.py` `workspace_lock` eliminating reentrant self-deadlock, and graceful worker shutdown invariant preservation in `soma_core/verification_jobs.py`.

### Cross-Platform Normalization & CI Portability
**Status**: ✅ Shipped (v0.94.1)  
Windows path backslash-to-slash normalization in `enzymes/fitness_updater.py` unblocking glob pattern matching (`src/**`), dynamic Python interpreter discovery in `install/install.ps1`, `sys.stdout.reconfigure(errors="replace")` guards across all CLI tools preventing `cp1252` encoding crashes, and CI runner xdist flag fix.

### Sandbox & Safety Gate Hardening
**Status**: ✅ Shipped (v0.94.1)  
Subshell metacharacter protection and destructive command flag detection (`-D`, `--output=`, `--ext-cmd=`) in `soma_cli/hooks.py` safety gate, path traversal confinement across `soma_mcp/tools.py` (`soma_scan`, `soma_propose_change`), atomic single-use cryptographic receipt invalidation on failed verification in `soma_core/receipts.py`, and pure-noise SNR `-inf` boundary invariant.

## Phase 5.4 — v0.95.0 ✅ Shipped

### Architecture Consolidation & Shell Enzyme Retirement
**Status**: ✅ Shipped (v0.95.0)  
Replaced bulky legacy shell implementations in `safety_gate.sh`, `immune_init.sh`, `session_close.sh`, and `cell_transfer.sh` with ultra-thin backward-compatible forwarding shims delegating to `soma_cli.hooks` and `soma_cli.transfer`, reducing over 800 lines of shell code with zero regression.

### Deep Defense & Sandbox Hardening
**Status**: ✅ Shipped (v0.95.0)  
Pre-tokenization quote/escape dequoting in safety gate blocking evasion bypasses (`\rm`, `r"m"`, `git diff --o\utput=`), word-bounded git branch deletion flags, git configuration/exec-path injection protection, and path confinement rejecting null bytes, Windows device names (`CON`, `PRN`, `AUX`, `NUL`, `COM1-9`, `LPT1-9`), alternate data streams, and extended namespaces.

### Storage Resiliency & Process Lifecycle Hardening
**Status**: ✅ Shipped (v0.95.0)  
Crash-resilient atomic storage (`soma_core/storage.py`) with exponential backoff on Windows file locking sharing violations (`WinError 32`), new `soma quarantine` CLI subcommand (`list`, `inspect`, `prune`), universal `utf-8-sig` BOM handling, and worker thread registry tracking with bounded shutdown joins in `soma_core/verification_jobs.py`.

## Phase 5.5 — v0.96.0 ✅ Shipped

### Pure-Stdlib Core Layer & Codebase Consolidation
**Status**: ✅ Shipped (v0.96.0)  
Consolidated all functional domains (Scoring/Workspace, Arbitration, Enforcement, Defects, Insights, Homeostasis, Sync, Telemetry, and Cell Genetics/Lifecycle) into pure-stdlib `soma_core/`. Converted 58 enzyme modules into backward-compatible dual-mode forwarding shims with explicit re-exports, dynamic module dispatch, and console encoding compliance, reducing architectural bloat in preparation for 1.0.0.

## Phase 5.6 — v0.96.1 ✅ Shipped

### 100% Zero-Dependency Framework & Stdlib Frontmatter Engine
**Status**: ✅ Shipped (v0.96.1)  
Achieved complete zero-dependency architecture across all runtime surfaces (`soma_cli/`, `soma_core/`, `soma_mcp/`, `soma_sdk/`, `enzymes/`). Eliminated PyYAML from required dependencies (`dependencies = []` in `pyproject.toml`). Upgraded `soma_core.frontmatter` to support 100% of cell YAML patterns in pure Python standard library (wrapped plain scalars, same-indent sequences, literal/folded block scalars with chomping, and multiline quoted strings with unicode escapes), verified across 102 cells and 2,522 tests. Upgraded invariant SOMA-C01 to repository-wide SOMA-C02.

## Phase 5.7 — v0.97.0 ✅ Shipped

### The Sunset Phase: Legacy Enzymes Purge, Native Platform Adapters & Dynamic Colocality
**Status**: ✅ Shipped (v0.97.0)  
Purged all 75 legacy enzyme scripts and 4,277 lines of shell/PowerShell installers in favor of pure-Python native platform adapters (`soma_cli.platforms`). Transitioned the SDK facade and MCP endpoints to 100% in-process execution without subprocess overhead (ADR-013). Established canonical 1:1 mirrored test package directories (`tests/soma_core/`, `tests/soma_cli/`, etc.) with hermetic import isolation and fully dynamic candidate resolution in checkpoint verification.

## Phase 5.8 — v0.97.1 ✅ Shipped

### Structured Command Safety & Safety Gate Pattern De-bloating
**Status**: ✅ Shipped (v0.97.1)  
Adversarially audited and rejected proposed `RegexBuilder` class in favor of pure-stdlib `CommandAnalyzer` (`soma_core.command_safety`, ADR-014). Eliminated 123 lines of fragile, unmaintainable shell regexes in `soma_cli/hooks.py` while providing lexical tokenization, wrapper unwrapping (`sudo`, `env`, `nice`, `time`, `nohup`), quote-aware subshell and pipeline extraction, and bounded recursion depth clamps.

## Phase 5.9 — v0.98.0 ✅ Shipped

### Test Suite Rationalization & Deadwood Pruning
**Status**: ✅ Shipped (v0.98.0)  
Consolidated 83 individual 1:1 mirrored stub files into a single high-speed parameterized test suite (`tests/test_module_contracts.py`). Purged 11 obsolete test suites (2,647 LOC) guarding deleted v0.97.0 assets (`enzymes/`, `install.sh`, etc.), eliminated 140 dead skipped tests in pytest runs, preserved historical bug registry traceability via tombstone regressions, and added dedicated unit tests for `soma_sdk.analysis`.

## Phase 5.10 — v0.99.0 ✅ Shipped

### Core/CLI Decoupling & Legacy CLI Purge
**Status**: ✅ Shipped (v0.99.0)  
Decoupled command-line execution and argument parsing from `soma_core/`. Extracted pure `evaluate_cell_tiers()` into `soma_core.lifecycle` and wired `soma promote --tier-check`. Purged 29 dead `cli_*` functions across `soma_core/` (`lifecycle.py`, `homeostasis.py`, `defects.py`, `insights.py`, `sync.py`, `telemetry.py`, `arbitration.py`, `enforcement.py`). Deleted legacy pass-through `soma_cli/handlers/` and its test suite. Net code reduction of ~1,660 lines.

## Phase 5.11 — v0.100.0 ✅ Shipped

### Core God Module Decomposition & Verification Deduplication
**Status**: ✅ Shipped (v0.100.0)  
Decomposed `soma_core/telemetry.py` (1,911 LOC) into `soma_core/outcomes.py` and `soma_core/metrics.py`, leaving `soma_core/telemetry.py` as a ~450 LOC cohesive evidence ledger with proxy mutation mirroring. Decomposed `soma_core/sync.py` (1,206 LOC) into `soma_core/sentinels.py`. Deduplicated triplicate glob matchers across telemetry and enforcement into canonical `find_matching_cells` in `soma_core/cell_inventory.py`. Centralized OS locking inside `soma_core/locking.py`. Added colocated test suites `test_outcomes.py`, `test_metrics.py`, and `test_sentinels.py`.

## Phase 5.12 — v0.101.0 ✅ Shipped

### Immune System Unification & Lifecycle Consolidation
**Status**: ✅ Shipped (v0.101.0)  
Unified the verification framework by establishing `soma_core/verification/` as the canonical package housing 12 deterministic and adversarial verification modules. Replaced the 3,672 LOC in `immune_system/verification/*.py` with lightweight backward-compatibility facade modules mirroring attributes and re-exporting all symbols. Consolidated `evaluate_promotions` and `evaluate_demotions` directly into `soma_core/lifecycle.py`, eliminating the duplicate lifecycle engine. Streamlined `cli_cell_create` description generation in `soma_core/lifecycle.py`. Rerouted internal CLI, MCP, and Core callers to canonical verification paths. Purged deprecated enzyme stubs (`_safe_import_enzyme` and `_ENZYME_ALLOWLIST`). Updated scripts reference to 74 total scripts.

## Phase 5.13 — v0.102.0 ✅ Shipped

### Facade Hardening & Final Prune (Bloat Initiative Completion)
**Status**: ✅ Shipped (v0.102.0)  
Decomposed monolithic `execute_tool()` in `soma_mcp/tools.py` into modular per-tool handlers with a declarative dispatch map, fixing syntax anomalies. Streamlined `_list_cells_stdlib` while preserving `TOOL_DEFINITIONS` literal AST compliance. Pruned dead legacy enzyme stubs in `soma_sdk/governance.py` (`_run_script`, `replay`, `trends`, `dependencies`, `adversarial`) and write-hook dead code in `soma_sdk/cells.py`. Eliminated leftover empty shims (`DESTRUCTIVE_PATTERNS = ()` and `STARTER_RULES_LEGACY`). Optimized `soma_core/__init__.py` with PEP 562 dynamic attribute resolution, accelerating cold package import by ~16x (down to 3.3ms) and process startup to 41ms. Completed comprehensive 5-phase bloat and latency audit.

## Phase 6 — v0.103.0 ✅ Shipped

### Legacy Sunset & Lifecycle Modularization
**Status**: ✅ Shipped (v0.103.0)  
Sunsetted legacy `immune_system/` compatibility shims, pruning 18 forwarding files. Pruned unmaintained `soma_sdk_js/` zero-dependency Node.js client package. Sunsetted dead epoch migration CLI engine `soma_cli/migration.py` and `tests/test_migration.py` while ensuring continuous BUG-019 and BUG-025 test suite coverage via tombstone regressions in `tests/test_legacy_purged_regressions.py`. Purged dead `install/starter_pack.txt` stub. Modularized 1,884-line monolithic `soma_core/lifecycle.py` into a structured, highly maintainable `soma_core/lifecycle/` package (`constants`, `parsers`, `quorum`, `decay`, `creation`, `promotion`, `selection`) with backward-compatible symbol re-exporting.

## Phase 7 — v0.104.0 ✅ Shipped

### Layer 2 Adversarial Verification CLI Wiring
**Status**: ✅ Shipped (v0.104.0)  
Wired Layer 2 Adversarial Verification into `soma verify` CLI using existing inference provider infrastructure (`Gemini`, `Anthropic`, `OpenAI`, `Keyring`, `PromptOnlyProvider`). Added `--plan`, `--plan-file`, and `--provider` flags with automatic plan discovery. Implemented graceful fallback to Layer 1 deterministic verification when no provider or API keys are present. Added `format_layer2_summary` for readable Arbiter output and mapped Arbiter verdicts (`SHIP` -> 0, `BLOCK`/`REVISE` -> 1). Developed following strict TDD with 100% test coverage across 9 new behavioral tests.

## Phase 8 — v0.105.0 ✅ Shipped

### True AST Call Graph Traversal & Static Analysis
**Status**: ✅ Shipped (v0.105.0)  
Upgraded call graph completeness checker from naive regex string matching to a full Python Abstract Syntax Tree (AST) engine. Resolves true function definitions, ignores docstrings/comments/string literals, isolates external module calls (preventing collisions with `subprocess.run`, `sys.exit`, etc.), tracks cross-module call sites, and respects module `__all__` export declarations. Developed following strict TDD with 10 behavioral tests in `tests/test_verification/test_call_graph_ast.py`.

## Phase 9 — v0.106.0 ✅ Shipped

### JIT Context Budget Clamping & Two-Layer Verification Gate
**Status**: ✅ Shipped (v0.106.0)  
Resolved GitHub Issue #75 by introducing configurable JIT context budget clamping (`max_jit_tokens`, defaulting to 2,000 tokens) across `soma_mcp/jit_engine.py` and `soma.conf`. Implemented deterministic character-based token estimation and multi-tiered precedence resolution (explicit parameter > environment variable > `soma.conf` > default 2,000). Prioritized active cell injection by frontmatter wall rules (`enforcement: wall` / `tier: wall`) while clamping lower-tier rules when the budget is saturated. Systematically integrated Gate 4.5 (Two-Layer Adversarial Verification) into `docs/project/RELEASE_WORKFLOW.md` and verified live with Gemini 3.8 Flash. Developed following strict TDD with 7 new behavioral tests in `tests/test_jit_context_budget.py`.

## Phase 10 — v0.107.0 ✅ Shipped

### Porcelain Aliases, Output Ergonomics & Pre-Seed Target Constraints
**Status**: ✅ Shipped (v0.107.0)  
Resolved GitHub Issue #77 and enhanced developer ergonomics across CLI commands and JIT engine. Added intuitive porcelain aliases (`soma check` -> `verify`, `soma rules` -> `status`, `soma audit` -> `doctor`). Added `--plain` and `--no-emoji` global output controls and plain text formatters for non-UTF-8 terminals (Windows cp1252) and CI log pipelines. Decoupled default status outputs from internal biological metaphors unless `--plumbing` is explicitly passed. Pre-seeded target file invariants and traps during `soma_scan` and JIT engine expression, rendering early-warning constraint summaries at the top of context to eliminate post-generation rejection token waste. Developed following strict TDD with 13 new behavioral tests across `tests/test_cli_porcelain.py` and `tests/test_jit_preseed_constraints.py`.

## Phase 11 — v0.108.0 ✅ Shipped

### Two-Layer Adversarial Rebuttal & Verification Test Harness
**Status**: ✅ Shipped (v0.108.0)  
Resolved the uncoordinated "Battleship" guessing flaw in Layer 2 verification by implementing the Two-Phase Adversarial Exchange (Prosecution $\rightarrow$ Defense Rebuttal). Serialized Layer 2 execution to pass Spec Agent predicted risk charges directly into the Code Agent defense prompt, prompting targeted defenses with code and test evidence while preserving strict information partitioning. Implemented `discover_test_evidence()` in `soma_cli/verify.py` to auto-discover matching test files, extract test names via AST, execute tests, and feed real test evidence to Layer 2. Enhanced `call_graph.py` AST traversal to inspect dictionary dispatch tables, container elements, and callback arguments, eliminating false-positive orphan function warnings on CLI command handlers. Developed following strict TDD with 11 new behavioral tests across `tests/test_verification/test_adversarial_rebuttal.py`, `tests/test_cli_verify_test_harness.py`, and `tests/test_verification/test_call_graph_dispatch.py`.

## Phase 12 — v0.109.0 ✅ Shipped

### Security Hardening & Core Architecture Decoupling
**Status**: ✅ Shipped (v0.109.0)  
Resolved 9 security, architectural, and reliability defects identified during the multi-perspective Tempest review (BUG-073 through BUG-081). Prevented host API key exfiltration and SSRF by strictly rejecting network endpoint configuration from untrusted workspace configuration files (`.soma/soma.conf`). Closed command safety evasion vectors by parsing POSIX bundled short flags (`-*c`) and normalizing trailing slashes in destructive `rm` commands. Enforced fail-closed session token authentication in the MCP server. Decoupled Layer 0 Core from Layer 2 MCP by canonicalizing frontmatter parsing inside `cell_inventory.py`. Fixed Layer 1 multi-target evidence collisions in the Arbiter, non-literal default argument AST crashes, and C1 terminal control escape code sanitization. Silenced upstream `google-genai` Automatic Function Calling (AFC) advisory warnings on single-turn inference. Developed following strict TDD with 29 new behavioral tests and full regression test suite passing.

## Phase 13 — v0.110.0 ✅ Shipped

### Ambient Telemetry & Zero-Touch Evolution
**Status**: ✅ Shipped (v0.110.0)  
Resolved the external critique regarding static rule decay and unobserved cell fitness. Closed the evolutionary telemetry feedback loop without background daemons or recurring cron jobs, maintaining strict scale-to-zero governance. Integrated ambient verification telemetry into `soma verify` and MCP verification tools to mint trigger and outcome signals (`signals.jsonl`). Implemented MCP stdio shutdown hooks to trigger outcome reflection on process termination. Added `soma harvest` (`--git`, `--limit`, `--dry-run`, `--json`) with cross-platform `evidence_lock()` and deterministic commit-hash idempotency to bootstrap initial cell fitness from historical git commits. Implemented read-time dynamic decay in `soma oracle` and `generate_checkpoint()` to lazily evaluate dormant and decaying cells without polling threads. Enhanced `branch_coverage.py` with bytecode disassembly (`dis.findlinestarts`) and multiline docstring state tracking to eliminate false-positive uncovered docstring lines. Developed following strict TDD with 29 new behavioral tests and full regression test suite passing (2,706 passing).

## Phase 14 — v0.111.0 ✅ Shipped

### Git Worktrees & Cell Schema Integrity
**Status**: ✅ Shipped (v0.111.0)  
Resolved pre-commit hook installation and health detection failures in Git worktrees (BUG-082) by introducing `resolve_git_hooks_dir()` in `soma_core.workspace` with zero-dependency fallback resolution. Updated `soma init`, `soma doctor`, and `soma sync` to handle `.git` pointer files in worktrees seamlessly. Resolved missing `enforcement` frontmatter in cell generation (BUG-083) across `create_cell()`, `cli_cell_create()`, and MCP prompt templates, defaulting wall cells to `gate` and vacuole cells to `advisory` to guarantee full compliance with pre-commit checkpoint conventions. Developed following strict TDD with 11 new behavioral tests across `tests/test_worktree_hooks.py` and `tests/test_cell_creation_enforcement.py` and full regression test suite passing (2,717 passing).

## Phase 15 — v0.112.0 ✅ Shipped

### Workspace Value Object & Hardened Error Handling
**Status**: ✅ Shipped (v0.112.0)  
Introduced the immutable, strongly-typed `Workspace` value object in `soma_core.workspace` implementing `os.PathLike[str]` for zero-overhead path manipulation, worktree-aware hook resolution, and path containment. Added standardized domain exception hierarchy (`WorkspaceError`, `WorkspaceNotFoundError`, `PathTraversalError`) subclassing `SomaValidationError` / `ValueError` for complete backward compatibility. Retained standalone functions as backward-compatible wrappers following the Strangler Fig migration pattern. Hardened error handling in git hook resolution by replacing bare exception blocks with explicit types (`(subprocess.SubprocessError, FileNotFoundError, PermissionError, UnicodeDecodeError, OSError)`). Integrated proactive `$PATH` guidance into `soma init` via `soma_cli.pathcheck.build_hint()`. Developed following strict TDD with 13 new behavioral tests and full regression verification (2,730 passing).

## Phase 16 — v0.113.0 ✅ Shipped

### Perimeter & Edge Workspace Migration
**Status**: ✅ Shipped (v0.113.0)  
Wired the strongly-typed `Workspace` value object into perimeter and edge boundaries. Initialized `_canonical_workspace` as a `Workspace` instance at MCP server startup (`soma_mcp/server.py`) and re-exported `Workspace` via `soma_mcp/security.py`. Standardized all MCP tool handlers (`soma_mcp/tools.py`) to resolve and confine workspaces into `Workspace` instances, replacing manual path concatenations with direct `ws.confine_path()` and `ws.cells_dir` calls. Integrated `Workspace` instances across state-bound receipts (`soma_core/receipts.py`), including receipt issuance, verification, file content hashing, and cell inventory fingerprints. Wired `self.workspace: Workspace` into `soma_sdk.Governance` while preserving 100% backward compatibility for `.root`, `.cells_dir`, and `.metrics_dir` properties. Developed following strict TDD with 10 new behavioral tests in `tests/test_perimeter_workspace.py` and full regression verification (2,742 passing).

## Phase 17 — v0.114.0 ✅ Shipped

### Core Engines Workspace Migration
**Status**: ✅ Shipped (v0.114.0)  
Wired the strongly-typed `Workspace` value object into core engines: lifecycle (`creation.py`, `parsers.py`, `promotion.py`, `decay.py`, `selection.py`), arbitration (`arbitration.py`), outcome reflection (`outcomes.py`), defect tracking (`defects.py`), invariant enforcement (`enforcement.py`), and synchronization (`sync.py`). Added `as_workspace(workspace)` coercion helper to `soma_core.workspace` and added `DeprecationWarning` with `stacklevel=2` to legacy standalone directory getters (`get_cells_dir`, `get_metrics_dir`, `get_signals_file`, `get_outcomes_file`). Developed following strict TDD with 19 new behavioral tests in `tests/test_core_engines_workspace.py` and full regression verification (2,761 passing).

## Phase 18 — v0.115.0 ✅ Shipped

### CLI Porcelain & Final Deprecation Gate
**Status**: ✅ Shipped (v0.115.0)  
Completes the Workspace migration across all user-facing CLI commands (`soma_cli/cli.py` root resolution attaching `args.ws: Workspace` to all subcommand handlers: `init`, `doctor`, `status`, `verify`, `promote`, `demote`, `transfer`, `checkpoint`, `genesis`). Performs AST audit to guarantee zero internal references to deprecated standalone getters while retaining permanent backward-compatible facades (`resolve_workspace`, `confine_workspace`, `confine_path`, `resolve_git_hooks_dir`).

## Phase 19 — v0.116.0 ✅ Shipped

### Multi-Repo Hook Ergonomics & Dedicated Hook Management
**Status**: ✅ Shipped (v0.116.0)  
Resolves multi-repo onboarding friction by introducing porcelain `soma hook` subcommands (`install`, `status`, `uninstall`), cross-platform dynamic interpreter resolution (Windows `Scripts/python.exe` and POSIX `bin/python`), uninitialized workspace bootstrapping (`Workspace.for_init()` and `ws.scaffold()`), and interactive hook installation in `soma genesis --install-hooks`.

## Phase 20 — v0.117.0 ✅ Shipped

### Dual-Mode Verifier OOP & Frictionless In-Session Verification
**Status**: ✅ Shipped (v0.117.0)  
Refactors the verification subsystem into a composable class hierarchy (`DeterministicVerifier`, `AdversarialVerifier`, `Arbiter`, `VerificationPipeline`). Introduces Dual-Mode Layer 2 Verification: zero-API-key in-session adversarial verification for interactive agent/MCP sessions (via in-band charge sheets and MCP Sampling `sampling/createMessage`), alongside headless SDK fallback for CI runners. Integrates `GitWorkspace(Workspace)` with zero-subprocess fast paths, resolves interpreter discovery for mutation testing across virtualenvs, and enforces the Isolated CI Environment Invariant (`HOME=$(mktemp -d) pytest`) guaranteeing zero test runner divergence.

## Phase 21 — v0.118.0 ✅ Shipped

### Modular Workspace Package, Non-Bypassable Layer 1 & Localized Cell Evolution
**Status**: ✅ Shipped (v0.118.0)  
Decomposes `soma_core/workspace.py` into a modular package directory (`soma_core/workspace/` with `base`, `git`, `discovery`, `confinement`, `scaffold`, and `hooks`). Restricts cell evolution strictly to the local workspace (`vacuole` $\rightarrow$ `wall` $\rightarrow$ `gate`), disconnecting automatic promotion to global `genome/`. Adds compound fingerprinting to `Workspace.is_soma_repo` to prevent false positives on external genomics repositories. Implements whitelist-only global rules cleanse with mandatory quarantine backups (`~/.soma/quarantine/`). Implements explicit tagged Horizontal Gene Transfer (`soma transfer export`).

## Phase 22 — v0.119.0 ✅ Shipped

### Intelligent JIT Targeting, Salience Engine & Closed-Loop Attribution
**Status**: ✅ Shipped (v0.119.0)  
Extends JIT matching from path globs to syntactic AST triggers (imports, decorators, call sites). Implements closed-form Salience scoring with an exploration prior ($S_{\text{base}} = 0.20$), 95% Wilson lower bound, and temporal decay within an invariant-preserving 2-tier token budget. Automatically attributes commit and verification outcomes from the Phase 20 Verifier to active cells in real time via `.soma/evidence/signals.jsonl`.

## Phase 23 — v0.120.0 ✅ Shipped

### The Great Project-Wide Legacy Cleanse & Sunset ("The Great Purge")
**Status**: ✅ Shipped (v0.120.0)  
The designated clean-slate release. Purged all accumulated rapid-iteration backwards-compatibility shims across the entire project (CLI, Core, MCP, SDK, and Tests) to establish the pristine baseline for permanent backwards compatibility. Removed deprecated standalone getters (`get_cells_dir`, `get_metrics_dir`, `get_signals_file`, `get_outcomes_file`), obsolete wrapper facades, legacy CLI flags (`--repo-root`, `--project-root`). Established the zero-warning test suite baseline (0 pytest warnings across 2,900+ tests). Official project-wide backwards compatibility contract begins here.

## Phase 24 — v0.121.0 ✅ Shipped

### Canonical Verification Pipeline, Fail-Closed Arbitration & Closed-Loop I->W->C
**Status**: ✅ Shipped (v0.121.0)  
Unifies all verification surfaces onto `VerificationPipeline` as the single canonical execution engine across CLI and MCP. Eliminates the split-brain architecture between `runner.py` and `pipeline.py` by converting `runner.run_layer2()` into a thin forwarding facade. Enforces fail-closed Layer 2 arbitration guarantees, real-time closed-loop repair loops (`--repair`), dynamic branch baseline discovery via `GITHUB_BASE_REF`, and cross-version Python 3.9 branch coverage resilience.

## Phase 25 — v0.122.0 ✅ Shipped

### Zero-Dependency AegisYAML, Horizontal Skill Graph, Response Projection & Lean Gateway
**Status**: ✅ Shipped (v0.122.0)  
Pure standard library recursive-descent YAML frontmatter parser (`aegis_core/yaml.py`, `AegisYAML`). Skill graph, fail-closed slot resolution, typed envelopes (<150 tokens), and file-buffered handoff tickets (`aegis_core/skills/`). Dual-Plane MCP Gateway decomposition (`aegis_mcp/`) into Control Plane (`registry.py`), Execution Plane (`handlers/`), and lean router (`tools.py`). Response projection and secret scrubbing (`aegis_mcp/projection.py`).

## Phase 25.5 — v0.123.0 ✅ Shipped

### Test Suite Consolidation & Hard Cleanse
**Status**: ✅ Shipped (v0.123.0)  
Relocated 191 test files into domain hierarchy: `tests/unit/core/`, `tests/unit/verification/`, `tests/unit/cli/`, `tests/unit/mcp/`, `tests/unit/sdk/`, and `tests/integration/`. Atomic synchronization of all entries in `BUG_REGISTRY.json` and `CLAIM_REGISTRY.json`. Hermetic isolation fixtures in single canonical `tests/conftest.py`.

## Phase 26 — v1.0.0 ✅ Shipped

### Production GA, Documentation Portal & SemVer 2.0 Compatibility Guarantee
**Status**: ✅ Shipped (v1.0.0)  
Restructures root `README.md` into a lean documentation portal (< 200 lines) with interactive closed-loop diagram, 30-second quickstart, and comprehensive production guides (`docs/guides/mcp_gateway.md`, `docs/guides/verification_pipeline.md`, `docs/guides/rule_lifecycle.md`, `docs/guides/skill_graph.md`). Formal SemVer 2.0 Backwards Compatibility Guarantee published in `docs/project/COMPATIBILITY.md`.

## Phase 27 — v1.1.0 ✅ Shipped

### Language-Agnostic AST Verification via Normalized AST Drivers
**Status**: ✅ Shipped (v1.1.0)  
Language-agnostic Normalized AST Driver (NAD) protocol (`aegis_core/ast/`). NormalizedAST intermediate representation, in-process Python driver, subprocess driver runner with timeout and sandbox constraints. Polyglot Layer 1 call graph reachability, orphan deadwood detection, and mutation testing (`aegis_core/verification/`). Reference driver recipes for TypeScript/JavaScript (`install/drivers/ts_ast.js`) and Go (`install/drivers/go_ast.go`).

## Phase 28 — v1.2.0 ✅ Shipped

### Zero-Touch Polyglot Provisioning & Rust AST Driver
**Status**: ✅ Shipped (v1.2.0)  
Zero-touch polyglot language detection and driver slot provisioning in `aegis init`, `aegis detect`, and `aegis doctor --fix` (`aegis_core/ast/detect.py`). Pure Python stdlib reference Rust AST driver (`rust_ast.py`) producing NormalizedAST JSON without external dependencies. Bundled driver templates (`aegis_core/ast/drivers/templates/`). CI/CD release verification alignment (`diff_base` propagation and `HEAD~1` fallback in `aegis_core/verification/runner.py`).

## Phase 29 — v1.3.0 ✅ Shipped

### Pre-Commit Verification & Release Gate 4.5 Hardening
**Status**: ✅ Shipped (v1.3.0)  
Fast pre-commit git hook verification (`aegis verify --fast`) and pre-tag release verification (`aegis check --release`, Gate 4.5) ensuring zero unverified tags reach `main`.

## Phase 30 — v2.0.0 – v3.0.0 ✅ Shipped

### Aegis Guardrails Nomenclature & Multi-Platform IDE Integration
**Status**: ✅ Shipped (v3.0.0)  
Transition from biological metaphors (`soma`, `cell`, `Spores`–`Mulch`, `Breeze`–`Supercell`) to clear engineering vocabulary (**Aegis Guardrails**, `aegis_core`, `aegis_cli`, `aegis_mcp`, `aegis_sdk`, `rule`, `Sentry`–`Debrief`, `Patrol`–`Citadel`). Multi-platform configuration compilation (`aegis_core/compiler.py`) for Gemini/Antigravity, Claude Code, Cursor, GitHub Copilot, and Kiro, plus workspace migration via `aegis migrate`.

## Phase 31 — v3.1.0 – v3.2.0 ✅ Shipped

### GitFlow Review Gate, Structural Separation & Documentation Alignment
**Status**: ✅ Shipped (v3.2.0)  
Enforces structural separation between authoring and reviewing contexts via `rules/gitflow-review-gate.md` and `rules/ci-green-before-release.md`. Consolidates the 17-tool MCP gateway (`aegis_*`), pure-Python in-process governance hooks (`aegis_cli/hooks/`), and comprehensive architecture, ADR, and project documentation.

## Research

### Antifragile Scaling
**Status**: Research  
Rules that perform better under stress receive fitness bonuses.

### External Validation Benchmarks
**Status**: Research  
Standardized benchmarks for comparing governance effectiveness across projects.

### Natural Language Rule Creation
**Status**: Experimental  
Create rules from natural language descriptions via `aegis_core/lifecycle/creation.py` (`aegis rule`).

### Team Topology (Multi-Repo Sync)
**Status**: Experimental  
Synchronize governance rules across multiple repositories.

### Counterfactual ROI
**Status**: Research  
Causal inference for measuring governance impact.



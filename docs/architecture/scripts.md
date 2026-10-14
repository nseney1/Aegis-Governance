# Scripts Reference

This document catalogs 77 executable scripts, command modules, SDK modules, and MCP/core modules in the Aegis governance framework.

## Counting Method

Counts are generated from the source tree with mutually exclusive categories: package initializers (`__init__.py`, `__main__.py`) and subpackages (`aegis_core/workspace/`, `aegis_core/lifecycle/`, `aegis_core/schemas/`, `aegis_core/outcomes/`, `aegis_cli/hooks/`) are excluded; `install/hooks/pre-commit` is counted as the lifecycle script; and all non-initializer `aegis_core/*.py` modules are grouped with the MCP modules. This produces 77 unique paths with no double counting.

## Summary by Category

| Category | Primary Language / Location | Count | Description |
|:---------|:----------------------------|:------|:------------|
| [Lifecycle Scripts (Hooks)](#lifecycle-scripts-hooks--bash) | bash (`install/hooks/`) | 1 | Git pre-commit lifecycle hook |
| [Verification Scripts](#verification-scripts--python) | Python (`aegis_core/verification/`) | 15 | Deterministic AST checkers, coverage tools, and adversarial verification |
| [CLI Commands](#cli-commands--python-aegis_cli) | Python and bash (`aegis_cli/`, root) | 21 | CLI launcher and command implementation modules |
| [SDK Modules](#sdk-modules--python-aegis_sdk) | Python (`aegis_sdk/`) | 8 | Canonical scoring, parsing, telemetry, hot-zone, and governance APIs |
| [MCP and Core Modules](#mcp-and-core-modules) | Python (`aegis_mcp/`, `aegis_core/`) | 32 | MCP transport, dispatch, confinement, content inventory, canonical evidence, cache, errors, receipts, and atomic storage |
| **Total** | | **77** | Unique paths under the method above |

---

## Lifecycle Scripts (Hooks) — bash

This bash script is invoked automatically by git triggers. Following the v0.97.0 sunset phase, all runtime lifecycle hooks are driven directly by pure Python in `aegis_cli/hooks/` and `aegis_core/sync.py`.

| Script | Location | Purpose |
|:-------|:---------|:--------|
| **`pre-commit`** | `install/hooks/pre-commit` | Git pre-commit hook that evaluates governance cells on staged diffs and mechanically blocks commits on violations. |

---

## Verification Scripts — Python

These 15 Python scripts form the deterministic and adversarial verification engine in `aegis_core/verification/`.

| Script | Location | Purpose |
|:-------|:---------|:--------|
| **`arbiter.py`** | `aegis_core/verification/arbiter.py` | Deterministic divergence detector comparing Spec Agent predictions against Code Agent claims, backed by Layer 1 tool evidence. |
| **`branch_coverage.py`** | `aegis_core/verification/branch_coverage.py` | Deterministic branch coverage verification tool wrapping pytest-cov or Python's stdlib `trace` module. |
| **`call_graph.py`** | `aegis_core/verification/call_graph.py` | Layer 1 AST checker verifying function reachability from call sites across the codebase. |
| **`checkpoint_checks.py`** | `aegis_core/verification/checkpoint_checks.py` | Canonical stdlib-only verification implementations (test coverage, git cleanliness, docstring presence) shared by CLI and MCP. |
| **`immune_verify.py`** | `aegis_core/verification/immune_verify.py` | Adversarial pair enzyme orchestrating the information-partitioned Spec Agent vs Code Agent verification protocol. |
| **`import_guard.py`** | `aegis_core/verification/import_guard.py` | Layer 1 AST tool detecting unguarded third-party imports to prevent runtime `ImportError` failures. |
| **`jobs.py`** | `aegis_core/verification/jobs.py` | In-memory asynchronous verification job store and background thread worker for Layer 2 verification. |
| **`mutation_tester.py`** | `aegis_core/verification/mutation_tester.py` | Lightweight AST mutation tester that synthesizes mutant functions to evaluate test suite fault-detection capabilities. |
| **`persistence_checker.py`** | `aegis_core/verification/persistence_checker.py` | Layer 1 AST checker verifying that in-memory state mutations have corresponding persistent serialization paths. |
| **`pipeline.py`** | `aegis_core/verification/pipeline.py` | Composable verification pipeline and OOP verifier hierarchy with zero-key in-band charge sheets and MCP sampling. |
| **`quality_gate.py`** | `aegis_core/verification/quality_gate.py` | Deterministic AST test quality gate validating assertion presence, detecting hollow tests, and enforcing behavioral test standards. |
| **`review_adapter.py`** | `aegis_core/verification/review_adapter.py` | Converts multi-agent review findings into structured Prediction and Claim objects for Arbiter evaluation. |
| **`runner.py`** | `aegis_core/verification/runner.py` | Layer 1 orchestration runner executing all deterministic AST and coverage checks to produce a combined evidence package. |
| **`test_runner.py`** | `aegis_core/verification/test_runner.py` | Centralized pytest discovery across virtual environments and workspace interpreters. |
| **`transcript_verifier.py`** | `aegis_core/verification/transcript_verifier.py` | Orchestrator-level subagent transcript verifier extracting objective metrics (test passes, file modifications, fix cycles) from JSONL logs. |

---

## CLI Commands — Python (`aegis_cli/`)

These 21 paths provide the root `aegis` launcher and 20 non-initializer Python modules in `aegis_cli/`. Subcommands are organized around the 5 core verbs (`init`, `status`, `check`, `rule`, `system`) plus `agent` plumbing and `migrate`.

| Command / Script | Location | Purpose |
|:-----------------|:---------|:--------|
| **`aegis`** | `aegis` | Root executable bash launcher with symlink resolution and environment configuration for the CLI. |
| **`agent.py`** | `aegis_cli/agent.py` | `aegis agent`: Headless machine-to-machine subcommands for automated agents and MCP dispatch. |
| **`base.py`** | `aegis_cli/base.py` | Abstract base class `SomaCommand` and `CommandCategory` taxonomy for modular CLI commands. |
| **`check.py`** | `aegis_cli/check.py` | `aegis check`: Unified verification gate absorbing verify, checkpoint, and pathcheck into a single command. |
| **`checkpoint.py`** | `aegis_cli/checkpoint.py` | Deterministic quality checks (test coverage, git status, docstring presence) without LLM calls. |
| **`cli.py`** | `aegis_cli/cli.py` | Main CLI entrypoint and argument dispatcher routing user commands to subcommand modules. |
| **`completion.py`** | `aegis_cli/completion.py` | `aegis completion {bash,zsh,fish}`: Prints shell completion scripts generated dynamically from argparse. |
| **`detect.py`** | `aegis_cli/detect.py` | `aegis detect`: Discovers project languages, toolchains, and source extensions, and provisions AST drivers. |
| **`doctor.py`** | `aegis_cli/doctor.py` | System health check verifying workspace structure, rules, configuration, and dependencies. |
| **`init.py`** | `aegis_cli/init.py` | `aegis init`: Scaffolds governance and platform rules for Gemini, Claude Code, Cursor, Copilot, or Kiro. |
| **`install.py`** | `aegis_cli/install.py` | `aegis install`, `aegis uninstall`: Installs and uninstalls rules and integrations into user environments. |
| **`migrate.py`** | `aegis_cli/migrate.py` | `aegis migrate`: One-way atomic upgrade from legacy `.soma` workspace layout to modern `.aegis`. |
| **`pathcheck.py`** | `aegis_cli/pathcheck.py` | Shell-aware PATH guidance: finds where pip installed `aegis` and prints PATH instructions. |
| **`registry.py`** | `aegis_cli/registry.py` | Command registry coordinating categorized discovery, subparser population, and grouped help formatting. |
| **`report.py`** | `aegis_cli/report.py` | `aegis report`: Session report card showing triggered rules, event counts, and activity distributions. |
| **`rule.py`** | `aegis_cli/rule.py` | `aegis rule`: Unified rule lifecycle management (list, promote, demote, archive, clean). |
| **`skills.py`** | `aegis_cli/skills.py` | Inspects skill graphs, slot resolution, and swarm handoffs. |
| **`status.py`** | `aegis_cli/status.py` | `aegis status`: Displays active rules, operational metrics, and governance health. |
| **`sync.py`** | `aegis_cli/sync.py` | `aegis sync`: Rebuilds rule fitness frontmatter from canonical evidence logs. |
| **`system.py`** | `aegis_cli/system.py` | `aegis system`: System diagnostics, git hooks management, driver management, and platform tools. |
| **`verify.py`** | `aegis_cli/verify.py` | Runs verification on changed files (Layer 1 deterministic tools and Layer 2 adversarial LLM pair). |

---



---

## SDK Modules — Python (`aegis_sdk/`)

These 8 non-initializer modules provide the canonical Python APIs used by the CLI, MCP server, and governance engines.

| Module | Location | Purpose |
|:-------|:---------|:--------|
| **`errors.py`** | `aegis_sdk/errors.py` | Structured error hierarchy for governance operations (parse errors, validation failures, scoring exceptions). |
| **`scoring.py`** | `aegis_sdk/scoring.py` | Wilson interval confidence-bound scoring and related fitness calculations. |
| **`rules.py`** | `aegis_sdk/rules.py` | Canonical Rule and RuleFitness models and frontmatter utilities. |
| **`governance.py`** | `aegis_sdk/governance.py` | Governance state API for querying active rules, cells, and configuration. |
| **`analysis.py`** | `aegis_sdk/analysis.py` | Analytical utilities for fitness landscapes, trends, and evidence aggregation. |
| **`hot_zones.py`** | `aegis_sdk/hot_zones.py` | Computes file and root-cause heat from the bug registry for antifragile fitness boosts. |
| **`invariants.py`** | `aegis_sdk/invariants.py` | Evaluates the cell invariant DSL and enforcement tiers. |
| **`telemetry.py`** | `aegis_sdk/telemetry.py` | Canonical locked, idempotent, generation-fenced writer for `.aegis/evidence/signals.jsonl`. |

---

## MCP and Core Modules

These 32 modules implement the MCP server, state-bound authorization, safe cell inventory, YAML frontmatter parsing, canonical evidence reading, transactional resource locking, self-healing quarantine, atomic storage, and standardized domain errors. Package initializers and `aegis_mcp/__main__.py` are excluded from the count.

| Module | Location | Purpose |
|:-------|:---------|:--------|
| **`server.py`** | `aegis_mcp/server.py` | JSON-RPC transport, capability filtering, canonical `AEGIS_WORKSPACE` injection, and receipt issuance/redemption. |
| **`tools.py`** | `aegis_mcp/tools.py` | Canonical 20-tool router with input normalization, response projection, and dispatch (<150 LOC). |
| **`registry.py`** | `aegis_mcp/registry.py` | MCP Control Plane: Tool definitions, canonical schemas, parameter translation, and workspace boundary confinement. |
| **`projection.py`** | `aegis_mcp/projection.py` | Opt-in response projection engine for token reduction and SOMA-V01 credential scrubbing. |
| **`security.py`** | `aegis_mcp/security.py` | Workspace/path confinement and cell-name validation. |
| **`integrity.py`** | `aegis_mcp/integrity.py` | Cell manifest generation, signing, and verification. |
| **`rule_cache.py`** | `aegis_mcp/rule_cache.py` | Content-fingerprinted parsed-rule cache using the canonical race-detecting inventory; stale or unsafe trees fail closed. |
| **`jit_engine.py`** | `aegis_mcp/jit_engine.py` | JIT cell matching, frontmatter parsing, and governance expression. |
| **`scoring.py`** | `aegis_core/scoring.py` | Zero-dependency Wilson interval lower bound and SNR confidence calculations. |
| **`proposals.py`** | `aegis_core/proposals.py` | Test-to-code (TTC) verification, deterministic oracle scoring, and checkpoint validation. |
| **`enforcement.py`** | `aegis_core/enforcement.py` | Cell enforcement, CI outcome reporting, bug registry integrity, and documentation claim verification. |
| **`defects.py`** | `aegis_core/defects.py` | Escaped defect tracking, cell expiry pruning, and hot zone diagnosis. |
| **`insights.py`** | `aegis_core/insights.py` | Structured insight capture and correlation engine. |
| **`homeostasis.py`** | `aegis_core/homeostasis.py` | Session sleep consolidation, system coherence, interoception health check, and resilience engine. |
| **`sync.py`** | `aegis_core/sync.py` | Escalation sentinel, liveness sentinel, team sync, HGT ribosome, immune sweep, and post-session hooks. |
| **`telemetry.py`** | `aegis_core/telemetry.py` | Telemetry signal collection, outcome processing, fitness updating, metrics snapshots, cell quorum, coverage, and immune grading. |
| **`receipts.py`** | `aegis_core/receipts.py` | In-memory single-use receipts bound to session, workspace, operation, exact arguments, target-file digest, canonical cell fingerprint, and expiry. |
| **`rule_inventory.py`** | `aegis_core/rule_inventory.py` | Captures stable rule bytes and content fingerprints without following symlinks; detects concurrent changes and unsafe trees. |
| **`evidence.py`** | `aegis_core/evidence.py` | Standard-library canonical reader for weighted `signals.jsonl` evidence, independent trigger/outcome dimensions, and structured parse errors. |
| **`errors.py`** | `aegis_core/errors.py` | Standardized typed domain error hierarchy (`AegisError`, `AegisValidationError`, `RuleCorruptError`, `ReceiptExpiredError`, `LockTimeoutError`). |
| **`yaml.py`** | `aegis_core/yaml.py` | Zero-dependency AegisYAML and frontmatter parser with DoS recursion guards, anchor attack prevention, and UTF-8 validation. |
| **`locking.py`** | `aegis_core/locking.py` | Cross-platform transactional resource locking with timeout fences and native Windows fallback. |
| **`quarantine.py`** | `aegis_core/quarantine.py` | Self-healing quarantine isolating damaged YAML cells and unparseable JSONL files to preserve system availability. |
| **`storage.py`** | `aegis_core/storage.py` | Crash-resilient atomic file writes via temporary files, directory fsync, and exponential backoff retry on Windows sharing violations (WinError 32). |
| **`inference_provider.py`** | `aegis_core/inference_provider.py` | Inference provider abstraction layer with secure credential lookup and key management for AI-assisted operations. |
| **`sweep_session.py`** | `aegis_core/sweep_session.py` | Session transcript scanning, signal aggregation, and metric collection for sweep operations. |
| **`evidence_collector.py`** | `aegis_core/evidence_collector.py` | Ground-truth evidence collection and observation processing for rule evaluation. |
| **`command_safety.py`** | `aegis_core/command_safety.py` | Pure-stdlib lexical command tokenizer, wrapper unrolling automaton, and structured safety-gate analyzer. |
| **`metrics.py`** | `aegis_core/metrics.py` | Metrics snapshots, token census aggregation, cell quorum sensing, coverage mapping, and immune report cards. |
| **`sentinels.py`** | `aegis_core/sentinels.py` | Subagent liveness & deadlock detection, protocol escalation recommender, and last-gasp apoptosis sentinels. |
| **`ast_match.py`** | `aegis_core/ast_match.py` | Syntactic AST trigger matching engine (imports, call sites, decorators) with fast diff token pre-filtering. |
| **`attribution.py`** | `aegis_core/attribution.py` | Closed-loop attribution correlation mapping linking verification outcomes to cell fitness and signals telemetry. |

---

## Privacy Invariant

All scripts in this catalog are strictly constrained by the **Soma Privacy Invariant**: No script may output, log, or transmit raw file paths, usernames, hostnames, directory structures, code diffs, or patches outside the local environment. Only aggregate counts, booleans, and sanitized strings are permitted across telemetry and external synchronization.

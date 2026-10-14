# Changelog

All notable changes to Aegis Guardrails are documented here.
This project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [3.1.0] — 2026-10-14 — "Architecture Hardening, Cryptographic Receipt Burn-Before-Compare & Canonical Aegis Taxonomy"

### Packaging & Standalone Wheel Parity
- **`rules` & `skills` Package Bundling (`pyproject.toml`, `aegis_cli/platforms/base.py`, `.github/scripts/wheel_smoke.py`)**:
  - Added `rules` and `skills` (`rules/__init__.py`, `skills/__init__.py`) to `[tool.setuptools.packages.find]` and `[tool.setuptools.package-data]` (`rules = ["*.md", ".oracles/*.md"]`, `skills = ["*/SKILL.md"]`) so standalone `pip install aegis-guardrails` wheels bundle all 18 core rules and 15 agent skills.
  - Updated `PlatformAdapter.get_source_skills()` (`aegis_cli/platforms/base.py`) to fall back to `importlib.resources.files("skills")` when running outside a git checkout, matching `get_source_rules()`.
  - Extended `.github/scripts/wheel_smoke.py` to assert non-empty `get_source_rules()` and `get_source_skills()` under `python -I` outside the repository.

### Cryptographic Security Hardening
- **Burn-Before-Compare Single-Use Receipts & Sidecar Locking (`aegis_core/receipts.py`, `aegis_mcp/server.py`)**:
  - Hardened `ReceiptManager.verify(..., consume=True)` under exclusive sidecar file lock `.aegis/locks/receipts.lock` to verify HMAC-SHA256 signature and expiration first, immediately append the consumed nonce to `.aegis/receipts.jsonl` (`fsync`), and only then compare `file_digest` and `rule_digest`, preventing pre-burn replay attacks on digest mismatch or path validation failures.
  - Fixed ledger compaction (`_compact_consumed_locked`) to prune only expired nonces (`exp < now`), eliminating the 1,000-nonce FIFO eviction replay vulnerability.
  - Wrapped `server.py:_verify_receipt_for_call` `_compute_state_digest` in `try/except ValueError` so invalid path arguments occur after receipt burn and return structured JSON-RPC errors without leaking unburned tokens.

### Verification Engine & MCP Tool Surface Cleanup
- **Deduplicated `scan_test_issues()` & Narrowed Exception Handling (`aegis_core/ast_checks.py`, `aegis_core/verification/`, `aegis_core/rule_inventory.py`, `aegis_core/telemetry.py`)**:
  - Extracted shared `scan_test_issues()` in `aegis_core/ast_checks.py` and wired both `aegis_cli/check.py` and `aegis_core/verification/pipeline.py` to eliminate duplicated test AST scanning logic.
  - Narrowed broad `except Exception:` blocks in `aegis_core/verification/runner.py`, `aegis_core/rule_inventory.py`, and `aegis_core/telemetry.py` to specific exception tuples (`(OSError, ValueError, KeyError, TypeError)` / `(OSError, subprocess.SubprocessError, ValueError, KeyError)`).
- **17 Canonical `aegis_*` MCP Tools (`aegis_mcp/registry.py`, `aegis_mcp/tools.py`, `aegis_mcp/server.py`)**:
  - Removed legacy duplicate MCP tool definitions `aegis_list_cells`, `aegis_fitness`, and `aegis_create_cell`, standardizing on the 17 canonical `aegis_*` tools (`aegis_list_rules`, `aegis_rule_fitness`, `aegis_create_rule`, etc.).
- **Clean-Tree Manifest Generation (`aegis_cli/check.py`, `aegis_core/rule_inventory.py`)**:
  - Made `aegis check` read-only by default (no longer mutating `.aegis/rules/manifest.json` during read-only checks) and added `RuleInventory.check_manifest_sync()`.

### Canonical Aegis Taxonomy Cutover
- **Review Modes, Prongs, Genesis Stages & `.aegis/rules/` Metadata (`aegis_core/`, `aegis_cli/`, `rules/`, `skills/`, `.aegis/rules/`)**:
  - Cut over review modes from weather metaphors (`breeze`, `gale`, `trident`, `maelstrom`, `tempest`, `supercell`) to defensive posture tiers (`patrol`, `sweep`, `vanguard`, `bulwark`, `fortress`, `citadel`).
  - Cut over review prongs from botanical metaphors (`spores`, `roots`, `thorns`, `bedrock`, `canopy`, `mulch`) to security operations roles (`sentry`, `trace`, `probe`, `bastion`, `gauntlet`, `debrief`).
  - Cut over Genesis onboarding stages from biological metaphors (`membrane`, `fossil`, `anatomy`, `physio`) to structural reconnaissance stages (`perimeter`, `chronology`, `blueprint`, `policy`).
  - Updated all 18 core rules (`rules/`), 15 agent skills (`skills/*/SKILL.md`), and 42 `.aegis/rules/` rule files to canonical Aegis v3.1.0 terminology and persisted Citadel v3.0.0 debrief learnings in `governance/debrief_queue.jsonl`.

## [3.0.0] — 2026-10-14 — "Pure Aegis Clean-Slate Architecture & Zero-Dependency CLI UX"

### Breaking Changes (Pure Aegis Clean-Slate Cutover)
- **Legacy `soma_*` Shims & `Soma*` / `Cell*` Aliases Removed**:
  - Deleted `aegis_core/compat.py`, `aegis_core/somayaml.py`, `aegis_sdk/cells.py`, `aegis_core/cell_inventory.py`, and `aegis_mcp/cell_cache.py`. Importing `soma_core`, `soma_cli`, `soma_sdk`, or `soma_mcp` now raises `ModuleNotFoundError`.
  - Removed all `Soma*` and `Cell*` class/error aliases (`SomaError`, `SomaValidationError`, `SomaYAMLError`, `SomaDocument`, `SomaYAML`, `SomaCommand`, `SomaParser`, `Cell`, `CellFitness`, `CellNotFoundError`, `CellParseError`, `CellPathTraversalError`).
- **Pure `.aegis/rules/` Workspace & Upgrade Sentinel**:
  - Removed `.soma/` and `.soma/cells/` fallback resolution across `aegis_core/workspace/`, `aegis_core/locking.py`, `aegis_core/rule_inventory.py`, `aegis_mcp/rule_cache.py`, and `aegis_sdk/rules.py`.
  - Unmigrated `.soma/` workspaces now trigger an immediate Upgrade Sentinel diagnostic instructing users to run `aegis migrate` on v2.1.x before upgrading to v3.0.0.
  - Renamed all repository rules in `.aegis/rules/invariants/` and `.aegis/rules/boundaries/` from `wall-*.md` / `membrane-*.md` to `invariant-*.md` / `boundary-*.md` and removed legacy biological rule types (`vacuole`, `chloroplast`, `plasmodesmata`).
- **Pure `aegis_*` MCP Tool Namespace**:
  - Cut over all 20 MCP tools in `aegis_mcp/registry.py`, `aegis_mcp/tools.py`, and `aegis_mcp/server.py` to the `aegis_*` namespace (`aegis_scan`, `aegis_report_outcome`, `aegis_create_rule`, `aegis_list_rules`, `aegis_verify_changes`, `aegis_checkpoint`, `aegis_handoff`, etc.) and removed `_CANONICAL_TOOL_MAP`.

### Zero-Dependency Terminal UI & CLI Unification
- **Terminal Theme & Adaptive Table Engine (`aegis_cli/ui/`)**:
  - Added `OutputContext` (`aegis_cli/ui/theme.py`) honoring `NO_COLOR`, `FORCE_COLOR`, `TERM=dumb`, `isatty()`, `--plain`, `--no-emoji`, and `--json` with zero ANSI leakage in non-TTY/JSON modes.
  - Added ANSI-aware `Table`, `Grid`, `Column`, `render_table`, `render_box`, and `render_error_panel` (`aegis_cli/ui/table.py`) while preserving `dependencies = []` in `pyproject.toml`.
- **Unified Command Registry & Core Deduplication**:
  - Registered `doctor`, `report`, `install`, and `uninstall` directly in `CommandRegistry` (`aegis_cli/registry.py`) and unified `aegis init` onto `aegis_cli/platforms/` adapters.
  - Consolidated frontmatter parsing onto `aegis_core/yaml.py`, atomic writes onto `aegis_core/storage.py`, relocated `aegis_core/verification/jobs.py`, and renamed `aegis_core/proposals.py`.

## [2.1.0] — 2026-10-14 — "Pure Aegis Unification, Migration Bridge & aegis-guardrails Cutover"

### Package & Repository Cutover
- **PyPI Package (`aegis-guardrails`) & Repository (`Aegis-Guardrails`)**:
  - Updated `pyproject.toml` distribution package name to `aegis-guardrails` (`pip install aegis-guardrails`) and repository links to `https://github.com/nseney1/Aegis-Guardrails`.
  - Updated `.github/workflows/publish.yml` OIDC Trusted Publisher target to `https://pypi.org/p/aegis-guardrails`.
  - Updated `aegis_core/workspace/discovery.py`, `aegis_cli/cli.py`, and `aegis_mcp/server.py` to resolve `aegis-guardrails` metadata.

### Workspace Migration Bridge (`aegis migrate`) & Modern Rule Taxonomy
- **Interactive & Automated `.soma` $\rightarrow$ `.aegis` Migration (`aegis_cli/migrate.py`)**:
  - Added `aegis migrate` (`--dry-run`, `--json`) to atomically migrate legacy `.soma/cells/` workspaces to `.aegis/rules/` (`invariants/`, `traps/`, `boundaries/`, `personas/`, `contracts/`).
  - Rewrites legacy biological `type:` frontmatter (`vacuole` $\rightarrow$ `trap`, `wall` $\rightarrow$ `invariant`, `membrane` $\rightarrow$ `boundary`, `chloroplast` $\rightarrow$ `persona`, `plasmodesmata` $\rightarrow$ `contract`) during migration (`BUG-099`).
- **Native Aegis Primitives (`AegisYAML`, `Rule`, `AegisError`, `AegisCommand`)**:
  - Promoted `aegis_core/yaml.py` (`AegisYAML`, `AegisDocument`, `parse_rule_frontmatter`), `aegis_sdk/rules.py` (`Rule`, `RuleFitness`), `aegis_core/errors.py` (`AegisError`, `AegisValidationError`, `RuleCorruptError`), and `aegis_cli/base.py` (`AegisCommand`) to primary implementations while retaining v2.x compatibility aliases.

### Runtime Engine & Governance Rule Wiring (`BUG-096`–`BUG-100`)
- **Governance Rule Frontmatter & Platform Adapter Parity (`BUG-096`, `BUG-097`)**:
  - Added required `trigger:` and `description:` frontmatter to `rules/META.md`, `rules/gitflow-review-gate.md`, `rules/core-change-protocol.md`, `rules/ci-green-before-release.md`, and `rules/no-pre-existing-excuse.md`.
  - Removed the `META.md` exclusion filter in `aegis_cli/platforms/base.py:discover_rules()`.
- **`.aegis/rules/` Engine Discovery (`BUG-098`, `BUG-100`)**:
  - Updated `aegis_mcp/jit_engine.py`, `aegis_core/sentinels.py`, `aegis_core/metrics.py`, `aegis_core/lifecycle/`, `aegis_cli/hooks/runtime.py`, `aegis_cli/init.py`, and `aegis_core/enforcement.py` to discover `.aegis/rules/` and emit modern Aegis response keys (`relevant_rules`, `invariant_warnings`, `triggered_rules`, `matched_rules`, `rules_triggered`, `total_rules`, `invariant_strength`).

## [2.0.0] — 2026-10-14 — "Soma-to-Aegis Unification & Architecture Rebrand"

### Architectural Rebrand
- Renamed core packages to `aegis_core`, `aegis_cli`, `aegis_mcp`, and `aegis_sdk` with `aegis_core/compat.py` import hooks preserving `soma_*` backwards compatibility across the v2.x line.
- Consolidated `genome/` into `rules/` and `.soma/cells/` into `.aegis/rules/`.

## [1.5.1] — 2026-10-14 — "Subagent Delegation Governance & CI Supply Chain Hardening"

### CI Supply Chain & Dependabot Pipeline Hardening
- **Artifact Action Security Bumps**:
  - Bumped `actions/upload-artifact` from v7.0.1 (`043fb46d1a93c77aae656e7c1c64a875d1fc6a0a`) to v7.0.2 (`cf430e030ddbb5b0abf93d22962f4752f3646cd9`).
  - Bumped `actions/download-artifact` from v8.0.1 (`3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c`) to v8.0.2 (`9000827ccba6bdab643e8b6fd33ac0654aef8333`).
- **Dependabot Workflow Routing**:
  - Configured `target-branch: "develop"` in `.github/dependabot.yml` across `github-actions` and `pip` package ecosystems.
  - Ensured automated dependency PRs build and validate against `develop` without triggering PR-to-main Release Gate 4.5 arbitration checks.
  - Extended `tests/integration/test_ci_workflows.py` to assert `target-branch: "develop"` is preserved.

### Governance & Architecture
- **Prefer Subagent Delegation Governance Cell (`wall-prefer-subagent-delegation`)**:
  - Established `.soma/cells/walls/wall-prefer-subagent-delegation.md` enforcing the Delegation-First Mandate for implementation tasks spanning $\ge 2$ disjoint files or independent modules.
  - Preserves primary orchestrator context for system architecture, cross-module integration, test verification, and staff synthesis.
  - Codifies Disjoint Lane Execution (explicit non-overlapping file scopes, model tiering, single-call fan-out, and verification against cheap-talk self-reports).
- **Genome Alignment**:
  - Updated Section 1 of `genome/subagent-delegation.md` to incorporate the Delegation-First Mandate and Single-Call Fan-Out protocol.

## [1.5.0] — 2026-10-09 — "Lifecycle Parity & Diagnostic Transparency"

### Developer Experience, Full Lifecycle Parity & Mutation Diagnostics
- **Production Status Rule Counting Parity (BUG-090)**:
  - Decoupled `_project_root` workspace resolution from `test_mode` in `soma status`. Production CLI executions now accurately count active platform rules rather than erroneously reporting `Core rules: 0 active`.
- **Symmetric Claude Platform Uninstallation (BUG-091)**:
  - Extended `soma uninstall --platform claude` to clean up the 5 starter rule `.md` files in `~/.claude/` (or `<project>/.claude/`), sanitize both target and workspace `.mcp.json` configs, and excise the git pre-commit hook block installed during `soma init`.
  - Added opt-in `--purge` flag to `soma uninstall` for explicitly removing `.soma/` governance state, while preserving `.soma/` by default.
- **Claude Rules Parity & Local Scoping in `soma init` (BUG-092)**:
  - Unified `ClaudeAdapter.render_config()` to render full rule content across both `init` and `install` workflows, eliminating truncated rule stub files.
  - Added `--local` flag support to `soma init`, allowing developers to target project-local rule directories (`<project>/.claude` and `<project>/CLAUDE.md`) in addition to default global configuration.
- **Dry-Run Output Standardization (BUG-093)**:
  - Standardized uninstallation logging across all platform adapters (`claude`, `copilot`, `mcp`) to use standard `[dry-run] Would uninstall <path>` notation instead of past-tense `"Uninstalled"` statements during `--dry-run`.
- **Telemetry Runner Safety & Missing Make Graceful Degradation (BUG-094)**:
  - Guarded Makefile discovery in outcome telemetry with `shutil.which("make")` validation, preventing failed subprocess invocations on systems lacking `make` (such as bare Windows environments).
  - Treated process exit code 127 as unverified/command-not-found rather than recording a false test failure, preventing unfair -1.0 fitness penalties across all governed cells.
  - Added `SOMA_REFLECT_ON_CLOSE` environment variable check to allow graceful opt-out of MCP server shutdown test runs.
- **Mutation Tester Diagnostic Transparency (BUG-095)**:
  - Introduced structured `TestRunResult` to capture subprocess exit codes, timeouts, and stderr details during mutation testing prerequisite baseline checks.
  - Replaced generic `"Baseline tests fail against the unmutated code"` errors with actionable diagnostic reasons (e.g. timeout duration under load, unresolved test runner binaries, or exact test assertion/traceback excerpts).

## [1.4.0] — 2026-10-09 — "Cross-Platform Execution & Safe Claude Lifecycle"

### Cross-Platform Execution, Windows Toolchain Hardening & Claude Lifecycle Parity
- **Safe Claude Configuration Lifecycle & Data Loss Prevention (BUG-088, [#142](https://github.com/nseney1/Soma-Governance/issues/142))**:
  - Delimited injected Soma instructions in `CLAUDE.md` with `<!-- SOMA:START -->` and `<!-- SOMA:END -->` markers.
  - Hardened `soma uninstall --platform claude` to parse and excise only the Soma-governed block, completely preserving user-authored custom instructions and notes. `CLAUDE.md` is deleted only if no non-Soma content remains.
  - Automatically cleans up `soma` from `mcpServers` in `.mcp.json` / `.claude.json` upon uninstallation.
- **Unified Claude Rules Directory & Path Parity (BUG-089, [#143](https://github.com/nseney1/Soma-Governance/issues/143))**:
  - Fixed `soma init --platform claude` to install rules and `CLAUDE.md` to user home (`~/.claude/`), resolving parity conflicts with `soma doctor`, `soma status`, and `soma uninstall`.
  - Replaced improper use of `args._project_root` as home override with explicit `_home` / `_home_override` test seams.
- **Rust AST Driver on Windows Python.org Installs (BUG-086, [#144](https://github.com/nseney1/Soma-Governance/issues/144))**:
  - The AST driver runner and `soma doctor` now resolve a bare `python3`/`python` driver command that is not on `PATH` to the interpreter running Soma (`sys.executable`), bypassing missing `python3.exe` on python.org Windows installations and 0-byte Windows Store execution aliases.
- **Test Harness Hardening & Symlink Fallbacks (BUG-087, [#145](https://github.com/nseney1/Soma-Governance/issues/145))**:
  - Added `anyio` to `[dev]` extras and CI pinned dependencies so `test_async_atomic_write_text` reliably executes on all environments.
  - Switched direct `symlink_to()` calls to `conftest.symlink_or_skip` so test suites pass on Windows environments without Developer Mode or administrative privileges.
- **Claude Platform Adapter Refactoring (`soma_cli/platforms/claude.py`)**:
  - Replaced deeply nested `if/elif/else` ladders in `ClaudeAdapter` with modular, single-purpose helper functions: `_inject_soma_section`, `_strip_soma_section`, `_uninstall_claude_md`, and `_clean_mcp_config`.
  - Flattened `install()` and `uninstall()` methods into linear, declarative routines with isolated exception handling.
- **AST Driver Architectural Cleanup & Deterministic Token Resolution (`soma_core/ast/runner.py`, `soma_core/ast/detect.py`)**:
  - Introduced deterministic `{python}` token support in `slots.yaml`, expanding directly to `sys.executable` across all platforms at runtime.
  - Added an in-process fast path for the bundled Rust AST driver (`rust_ast.py`), parsing Rust sources directly via `parse_rust_source` with zero subprocess overhead.
  - Purged platform-specific heuristic string sniffing (such as `windowsapps` alias detection and OS branching) from `soma_core/ast/runner.py`, restoring core engine purity. *(Note: The interim `windowsapps` string heuristic was refactored and eliminated prior to release and is not in production; v1.4.0 relies exclusively on deterministic `{python}` token expansion and in-process execution.)*

## [1.3.0] — 2026-10-08 — "Unified CLI Command Architecture & Discovery"

### Unified CLI Command Architecture, Modular Subcommands & Categorized Discovery
- **`SomaCommand` Protocol & Categorized Discovery (`soma_cli/commands/`)**:
  - Modularized monolithic CLI handlers into distinct `SomaCommand` subclasses with explicit metadata: `name`, `category` (`CommandCategory`), `description`, and `aliases`.
  - Structured all 24 commands across four decoupled domain modules:
    - `bootstrap.py`: `init`, `genesis`, `clone`, `config`
    - `inspection.py`: `status`, `list` (`ls`), `explain` (`show`), `history`, `metrics`, `doctor`, `detect` (`languages`, `drivers`)
    - `governance.py`: `propose`, `audit`, `receipt`, `freeze`, `thaw`, `adapt` (`evolve`), `export`, `import`
    - `verification.py`: `verify` (`check`), `quarantine`, `sweep`, `restore`, `checkpoint`
- **`CommandRegistry` Engine (`soma_cli/commands/__init__.py`)**:
  - Centralized registration, aliasing, and lazy instantiation for CLI commands.
  - Built-in category filtering (`get_by_category()`), alias resolution (`resolve()`), and schema discovery.
- **Orchestrator Refactor (`soma_cli/cli.py`)**:
  - Slimmed CLI entrypoint from 620 to 300 lines by delegating argument definition and execution to registry commands.
  - Enhanced `--help` formatting with clean category grouping, visual hierarchy, and alias hints.
  - Guaranteed 100% backward compatibility with existing command arguments, subparser flags, and stdout/JSON contracts.

## [1.2.1] — 2026-10-08 — "Git-Aware Polyglot Call Graph & Doctor Display Hotfix"

### Git-Aware Call Graph Boundary Discovery & Doctor Auto-Repair Fix (BUG-085)
- **Git-Aware File Discovery & Dynamic Extension Discovery (`soma_core/verification/call_graph.py`)**:
  - Replaced brittle directory blacklists with `GitWorkspace`-backed file discovery (`git ls-files --cached --others --exclude-standard`), automatically and universally respecting `.gitignore` across all project types without hardcoding compiler output names (`target/`, `.cargo/`, `bin/`, `obj/`, etc.).
  - Eliminated static hardcoded source extension sets in favor of dynamic extension resolution (`_resolve_searchable_extensions`), discovering source extensions from configured workspace slots (`.soma/slots.yaml`), active AST runner drivers, and target file metadata.
  - Implemented `_is_safe_source_file()` defense-in-depth guard rejecting files exceeding 1MB or containing binary null bytes.
- **Standalone `soma detect` Command & `soma doctor --drivers` (`soma_cli/detect.py`, `soma_cli/doctor.py`)**:
  - Added dedicated `soma detect` command (aliases: `soma languages`, `soma drivers`) allowing developers to inspect detected languages, toolchains, and AST driver bindings, and auto-provision `.soma/slots.yaml` with `--fix` independently of `soma init` or `soma genesis`.
  - Added `--drivers` flag to `soma doctor` for fast, targeted AST driver health checks without running full platform/rules/MCP audits.
- **Doctor Auto-Provision Display & Dry-Run Fixes (`soma_cli/doctor.py`, `soma_core/ast/detect.py`)**:
  - Fixed display fallthrough bug in `soma doctor --fix`: reloads `SlotRegistry` immediately after auto-provisioning so the configured polyglot driver is accurately reported rather than falling through to the native Python message.
  - Fixed `provision_ast_driver_slots` to strictly honor `dry_run=True`, preventing unauthorized directory creation or driver template copies during simulated runs.

## [1.2.0] — 2026-10-08 — "Zero-Touch Genesis Polyglot Provisioning & Rust AST Driver"

### Zero-Touch Polyglot Detection, Rust AST Driver & Release Verification Alignment
- **Zero-Touch Polyglot Provisioning (`soma_core/ast/detect.py`)**:
  - `detect_project_languages()`: Automatically detects source languages (Rust, Go, TypeScript/JavaScript, Python) by inspecting root manifests (`Cargo.toml`, `package.json`, `go.mod`, etc.) and scanning project source trees.
  - `provision_ast_driver_slots()`: Proactively configures `.soma/slots.yaml` with recommended driver commands and stages reference driver files into `.soma/drivers/` with full dry-run support.
- **CLI Workflows Integration (`soma_cli/`)**:
  - `soma init`: Automatically detects project languages and provisions polyglot AST driver slots during repository initialization.
  - `soma genesis`: Seamlessly auto-provisions AST drivers during initial repository scan and reports status in console and JSON output.
  - `soma doctor --fix`: Identifies unconfigured AST drivers for non-Python sources in the workspace and repairs them with `--fix`.
- **Reference Rust AST Driver & Template Bundling**:
  - Pure Python stdlib regex/block parser (`rust_ast.py`) producing `NormalizedAST` JSON with functions, structs, impls, modules, macros, and mutation points without external pip dependencies.
  - Bundled driver templates in `soma_core/ast/drivers/templates/` and installer recipe in `install/drivers/rust_ast.py`. Added package data distribution in `pyproject.toml`.
- **CI/CD & Release Verification Alignment (BUG-084)**:
  - Fixed `soma verify --layer1-only` in release tag publishing workflows by propagating resolved `diff_base` to `soma_core.verification.runner.run_layer1()` and adding `HEAD~1` fallback in `_get_modified_lines()`.
- **Architecture Decision Record (ADR)**:
  - `docs/architecture/decisions/ADR-016-zero-touch-polyglot-genesis.md`: Documents design trade-offs, language detection heuristics, and template installation paths.

## [1.1.0] — 2026-10-08 — "Language-Agnostic AST Verification via Normalized AST Drivers"

### Polyglot Verification, Normalized AST Drivers & Zero-Dependency Schema
- **Normalized AST Driver (NAD) Protocol (`soma_core/ast/`)**:
  - `soma_core/ast/schema.py`: Language-agnostic intermediate representation defining `NormalizedAST`, `DefinitionNode`, `CallSiteNode`, `ImportNode`, and `MutationPoint` with JSON and mapping roundtrip serialization.
  - `soma_core/ast/drivers/python.py`: In-process native Python standard library parser (`ast.parse`) providing a sub-millisecond fast path with zero process overhead.
  - `soma_core/ast/runner.py`: External process execution engine (`ASTDriverRunner`, `ASTDriverRegistry`) resolving drivers via `.soma/slots.yaml` or code registry with strict 3.0-second timeout enforcement and workspace confinement.
- **Layer 1 Polyglot Call Graph & Mutation Adaptation (`soma_core/verification/`)**:
  - `soma_core/verification/call_graph.py`: Implements `check_normalized` to verify function call reachability, detect orphan deadwood, and ignore comments and string literals across polyglot files.
  - `soma_core/verification/mutation_tester.py`: Adds `apply_mutation_point` and `collect_mutations_from_ast` supporting byte-offset and coordinate operator swaps on non-Python sources.
  - `soma_core/verification/runner.py`: Automatically routes changed polyglot files through configured AST drivers.
- **Host Driver Recipes (`install/drivers/`)**:
  - `install/drivers/ts_ast.js`: Zero-dependency Node.js recipe for TypeScript and JavaScript using the official `typescript` compiler API when present and falling back to a deterministic built-in lexer in bare environments.
  - `install/drivers/go_ast.go`: Zero-dependency Go recipe leveraging standard library `go/parser`, `go/token`, and `go/ast`.
- **Doctor Diagnostics & Architecture Documentation**:
  - `soma_cli/doctor.py`: Added `_check_ast_drivers` diagnostic verifying that configured AST driver binaries are resolvable on PATH.
  - `docs/guides/polyglot_ast.md`: Comprehensive developer guide for authoring and configuring custom AST drivers.
  - `docs/architecture/decisions/ADR-015-normalized-ast-driver-protocol.md`: Architectural Decision Record codifying the NAD protocol and trade-offs.

## [1.0.0] — 2026-10-08 — "General Availability & Production Governance Framework"

### Production GA, Documentation Portal & Formal Backwards Compatibility
- **Lean Documentation Portal (< 200 Lines)**:
  - Restructures root `README.md` into an immediate, above-the-fold portal with 30-second quickstart, closed-loop architecture diagram, and deep-dive documentation guide cards.
- **Production Architecture & Operations Guides (`docs/guides/`)**:
  - `docs/guides/mcp_gateway.md`: Dual-Plane Gateway architecture, tool tiers, receipt security, and opt-in projection.
  - `docs/guides/verification_pipeline.md`: Two-Layer Verification engine, deterministic Layer 1 AST checks, Layer 2 Adversarial Rebuttal, and Gate 4.5.
  - `docs/guides/cell_lifecycle.md`: Five cell types, evolutionary lifecycle, Wilson-bounded fitness scoring, and zero-touch decay.
  - `docs/guides/skill_graph.md`: Horizontal skill graph, typed envelopes (<150 tokens), and file-buffered handoffs.
- **SemVer 2.0 Backwards Compatibility Guarantee (`docs/project/COMPATIBILITY.md`)**:
  - Codifies formal public API contracts across CLI, Python SDK (`soma_sdk`), MCP Server (`soma_mcp`), and Core Governance schemas starting at `v1.0.0`.
- **Checkpoint Candidate Resolution**:
  - Updates verification test candidate resolution in `soma_core/verification/checkpoint_checks.py` to recognize relocated domain hierarchy suites.

## [0.123.0] — 2026-10-08 — "Test Suite Consolidation & Hard Cleanse"

### Test Suite Architecture & Hard Cleanse
- **Hierarchical Domain Test Suite**:
  - Relocated 191 flat test files into domain hierarchy: `tests/unit/core/`, `tests/unit/verification/`, `tests/unit/cli/`, `tests/unit/mcp/`, `tests/unit/sdk/`, and `tests/integration/`.
  - Removed legacy `tests/test_verification/` directory.
- **Canonical Evidence and Test Discovery**:
  - Synchronized all 83 entries in `docs/project/BUG_REGISTRY.json` and 23 entries in `docs/project/CLAIM_REGISTRY.json`.
  - Unified test discovery across runner and verify CLI using recursive domain globbing.
- **Hermetic Isolation Fixtures**:
  - Configured global `autouse=True` fixture in single canonical `tests/conftest.py` ensuring complete environment and singleton isolation across test runs.

## [0.122.0] — 2026-10-08 — "Zero-Dependency SomaYAML, Horizontal Skill Graph, Response Projection & Lean Gateway"

### Core Architecture, Swarm Protocols & Gateway Optimization
- **Zero-Dependency SomaYAML (`soma_core/somayaml.py`)**:
  - Implements pure standard library recursive-descent YAML frontmatter parser replacing external dependencies.
  - Complete drop-in parity across all 26+ frontmatter callers with DoS recursion guards, YAML bomb prevention, and zero-width anti-poisoning filtering.
  - Safely deletes `soma_core/frontmatter.py` with 0 residual references in AST scan.
- **Horizontal Skill Graph & Fail-Closed Slot Resolution (`soma_core/skills/`)**:
  - `soma_core/skills/graph.py`: Skill graph discovery and topology validation supporting producer/consumer contracts.
  - `soma_core/skills/slots.py`: Fail-closed parameterized slot resolution for swarm skills.
  - `soma_core/skills/handoff.py`: File-buffered ticket routing emitting compact prompt blocks (<150 tokens) and persisting HMAC-verified envelopes to `.soma/swarm/handoffs/`.
  - `soma_cli/skills.py`: CLI porcelain `soma skill {list,inspect,slots}` and `soma handoff`.
- **Opt-In Response Projection (`soma_mcp/projection.py`)**:
  - Implements response projection views (`full`, `summary`, `ids`) and arbitrary dot-notation field traversal (`fields=[...]`) to reduce agent context token consumption.
  - Embedded SOMA-V01 credential and secret scrubbing across all tool responses.
- **Dual-Plane MCP Gateway Decomposition (`soma_mcp/`)**:
  - `soma_mcp/registry.py`: Control Plane defining canonical tool schemas, argument normalization, and strict workspace boundary confinement.
  - `soma_mcp/handlers/`: Execution Plane with decoupled handlers (`governance.py`, `verification.py`, `audit.py`, `telemetry.py`) under 280 LOC each.
  - `soma_mcp/tools.py`: Ultra-lean gateway router under 150 LOC.
- **Accumulator Module Decompositions (`soma_core/outcomes/`, `soma_cli/hooks/`)**:
  - Decomposes legacy `soma_core/outcomes.py` into focused subpackage `soma_core/outcomes/` (`engine.py`, `fitness.py`, `harvest.py`, `insights.py`, `telemetry.py`).
  - Decomposes legacy `soma_cli/hooks.py` into modular subpackage `soma_cli/hooks/` (`redaction.py`, `safety.py`, `management.py`, `runtime.py`).

## [0.121.1] — 2026-10-08 — "Gate 4.5 Tree Hash Binding, Deduplication & Safety Hardening"

### Security, Verification & Safety Hardening
- **Gate 4.5 Cryptographic Tree Hash Binding (`soma_cli/verify.py`)**:
  - Binds arbitration receipts strictly to git tree hashes via `git rev-parse HEAD^{tree}`, preventing unverified code mutations after arbitration.
  - Enforces clean working trees (`git status --porcelain`) prior to release, ignoring runtime evidence ledgers (`.soma/evidence/`, `.soma/metrics/`, `.soma/telemetry/`) and Python test caches (`__pycache__`, `.pytest_cache`).
  - Eliminates silent exception swallowing (`except Exception: pass`) in release gate checks to fail closed on repository execution errors.
- **MCP Evidence Deduplication (`soma_mcp/tools.py`)**:
  - Removes redundant second persistence call in `_handle_verify_changes`, establishing `VerificationPipeline` as the single canonical evidence writer.
- **Atomic Cycle Counter (`soma_core/verification/review_adapter.py`)**:
  - Introduces `.soma/evidence/.cycle_counter` with atomic POSIX file locking (`.evidence.lock` via `fcntl.flock`) and automatic recovery via directory sweep.
  - Synchronizes cycle numbers across all evidence writes to prevent race conditions.
- **Fail-Closed Verification Persistence (`soma_cli/verify.py`)**:
  - Exits code 1 and records blocking telemetry if evidence persistence fails.
- **Command Safety Global Flags (`soma_core/command_safety.py`)**:
  - Adds `"--git-dir"` to `GIT_GLOBAL_FLAGS_WITH_ARG`, preventing escape from protected branch and repository mutation checks.
- **Call Graph Pre-Commit Fast Mode (`soma_core/verification/call_graph.py`, `runner.py`)**:
  - Adds `fast_mode` support to skip repository-wide `os.walk` in pre-commit hooks, preserving the $<300\text{ ms}$ latency budget.
- **CLI Porcelain for Human Insights (`soma_cli/cli.py`)**:
  - Exposes `soma capture-insight` CLI command with `--insight`, `--context-files`, `--category`, `--scaffold-wall`, and `--wall-id` flags.

## [0.121.0] — 2026-10-08 — "Canonical Verification Pipeline, Fail-Closed Arbitration & Closed-Loop I->W->C"

### Canonical Verification Pipeline, Fail-Closed Arbitration & Closed-Loop I->W->C
- **Canonical Verification Pipeline (`soma_core/verification/pipeline.py`, `soma_cli/verify.py`)**:
  - Permanently collapses the dual verification pathway by routing all Layer 1 and Layer 2 verification requests (CLI and in-band MCP) through `VerificationPipeline`.
  - Replaces fragmented verify logic in `soma_cli/verify.py` with `VerificationPipeline.run()`, guaranteeing identical evaluation semantics, fail-closed enforcement, and diagnostic output across CLI, hooks, and MCP tools.
  - Converts `soma_core/verification/runner.py::run_layer2()` into a thin backward-compatibility facade delegating directly to `VerificationPipeline.run()`.
- **Fail-Closed Layer 2 Arbitration & Evidence Generation (`soma_core/arbitration.py`, `soma_core/verification/pipeline.py`)**:
  - Hardens Layer 2 arbiter evaluation: provider timeouts, inference formatting errors, or malformed provider responses fail closed with `BLOCK` or `REVISE`, preventing ungrounded changes from passing verification.
  - Serializes verified arbitration receipts to `.soma/evidence/arbitration_cycle_{N}.json` with comprehensive round-trip fidelity.
- **Closed-Loop I->W->C Autonomous Repair Loop (`soma_cli/verify.py`, `soma_core/verification/pipeline.py`)**:
  - Implements the `--repair` flag on `soma verify`, enabling closed-loop remediation where failed assertions and Layer 2 arbiter critique trigger iterative deterministic repair before checkpoint commit.
- **Dynamic Baseline Ref Resolution & Branch Target Precision (`soma_core/verification/runner.py`, `soma_cli/verify.py`)**:
  - Adds prioritized base ref resolution inspecting `GITHUB_BASE_REF` and tracking remote branches (`origin/develop` before `origin/main`), ensuring precise modified-line diff targeting in CI pull request workflows.
- **Cross-Version Python 3.9 Coverage Precision (`soma_core/verification/branch_coverage.py`)**:
  - Remediates pre-PEP 626 jump tracing anomalies in Python 3.9 by filtering bare jump tokens (`break`, `continue`, `pass`) from missing line reporting.
  - Hardens `_parse_coverage` filtering out negative branch exits, backward loop headers, and already-executed jump targets.

## [0.120.1] — 2026-10-07 — "Human Review Gate Enforcement & CI Test Suite Repair"

### Human Review Gate Enforcement & CI Test Suite Repair
- **Governance & Command Safety Hardening (`soma_core/command_safety.py`)**:
  - Deterministically intercepts `gh pr merge` and protected branch pushes (`git push ... main` and `*:main` refspecs) via `CommandAnalyzer.evaluate()`, flagging them with `REASON_HUMAN_REVIEW_GATE` and `REASON_PROTECTED_BRANCH`.
  - Hardened option parsing for global GitHub CLI flags (`-R`, `--repo`) and full git refspecs (`refs/heads/main`).
  - Added Immune Wall cell `.soma/cells/walls/wall-human-review-gate.md` enforcing the structural boundary between autonomous agent execution and human release authority.
- **CI Test Suite Restoration & Bug Registry Grounding (`docs/project/BUG_REGISTRY.json`)**:
  - Remediated Pytest 8.3 exit code 4 in GitHub Actions CI by establishing tombstone regression assertions (`test_bug_014_powershell_installer_purged`, `test_bug_029_mcp_generators_purged`, `test_bug_031_manifestless_uninstall_purged`) in `tests/test_legacy_purged_regressions.py`.
  - Re-grounded all 83 bug entries in `BUG_REGISTRY.json` to existing, verified test functions.
  - Achieved 100% passing CI matrix across Ubuntu, macOS, and Windows on Python 3.9, 3.11, and 3.12.

## [0.120.0] — 2026-10-07 — "The Great Project-Wide Legacy Cleanse & Compatibility Contract"

### The Great Project-Wide Legacy Cleanse & Compatibility Contract ("The Great Purge")
- **Core Subsystem Cleanse (`soma_core/workspace/`)**:
  - Permanently purges deprecated standalone getters: `get_cells_dir`, `get_metrics_dir`, `get_signals_file`, and `get_outcomes_file`. All callers and internal engines standardise on direct `Workspace` instance properties (`ws.cells_dir`, `ws.metrics_dir`, `ws.signals_file`, `ws.outcomes_file`).
  - Removes unused legacy imports and obsolete wrappers across `soma_core`.
- **CLI Porcelain Consolidation (`soma_cli/`)**:
  - Purges legacy redundant CLI flag aliases: `--repo-root` from `soma verify` and `--project-root` from `soma genesis`, fully standardising on `--workspace` / `-w`.
  - Streamlines `main()` CLI dispatch to standard `args.ws = Workspace.resolve(...)`.
- **Public SDK Standardisation (`soma_sdk/`)**:
  - Updates `soma_sdk/scoring.py` docstrings and exports to reflect the official public SDK scoring API rather than deprecated facades.
- **Zero-Warning Test Suite Milestone (`tests/`)**:
  - Modernised test suites (`test_workspace.py`, `test_workspace_model.py`, `test_workspace_package.py`, `test_core_engines_workspace.py`) to assert on `Workspace` properties directly.
  - Replaced deprecation warning assertions with `TestPurgedLegacyGetters` verifying that purged getters are permanently removed from `soma_core.workspace` and `__all__`.
  - Unskipped `test_legacy_purged_regressions.py` with all 15 regression checks actively passing.
  - Achieved a 100% warning-free pytest run (0 warnings emitted across 2,900+ tests).

## [0.119.0] — 2026-10-07 — "Intelligent JIT Targeting, Salience Engine & Closed-Loop Attribution"

### Intelligent JIT Targeting, Salience Engine & Closed-Loop Attribution
- **Syntactic AST Triggers (`soma_core/ast_match.py`, `soma_mcp/jit_engine.py`)**:
  - Introduces `match_ast_triggers()` and `ASTTriggerVisitor` for precision targeting of imports, function/method call sites, and decorator applications.
  - Fast diff hunk token pre-filtering (`prefilter_ast_tokens()`) skips AST traversal on irrelevant diffs.
  - Seamlessly falls back to target path globs for non-Python files and unparseable snippets.
- **Cold-Start Safe Salience Scoring Engine (`soma_core/scoring.py`)**:
  - Implements `compute_salience()` with $S_{\text{base}} = 0.20$ exploration prior, guaranteeing newly created cells are never starved.
  - Clamped temporal decay floor $R_{\text{min}} = 0.20$ protects foundational invariants against obsolescence decay.
  - Tier weighting prioritizes security gates ($W_{\text{gate}} = 5.0$, $S_{\text{gate\_untested}} = 1.0$), walls ($W_{\text{wall}} = 2.0$), and vacuoles ($W_{\text{vacuole}} = 1.0$).
  - Specificity multipliers reward precise triggers (`ast_match`: 1.5x, `exact_path`: 1.2x, `glob_match`: 1.0x).
- **Partitioned 2-Tier Token Budget & Atomic Directive Compression (`soma_mcp/jit_engine.py`)**:
  - Implements `pack_two_tier_context()` dividing context budget: 1,200 tokens (60%) for Tier 1 Security Gates, 800 tokens (40%) for Tier 2 Advisory Rules. Unused Tier 1 headroom dynamically overflows to Tier 2.
  - Incompressible Gate Guarantee: Gates are NEVER dropped under extreme context pressure; overflow gates compress into Atomic Invariant Directives (`compress_to_atomic_directive()`).
- **Closed-Loop Attribution Correlation Mapping (`soma_core/attribution.py`, `soma_core/verification/pipeline.py`)**:
  - Implements `attribute_verification_outcome()` and `infer_cell_risk_categories()`.
  - Layer 1 deterministic verifier failures and Layer 2 confirmed divergences attribute True Positives (TP) to relevant active governance cells.
  - Spurious or dismissed predictions attribute False Positives (FP).
  - Updates cell frontmatter (`triggers`, `true_positives`, `false_positives`, `last_trigger_date`) and appends audit signals to `.soma/evidence/signals.jsonl`.
  - Wired directly into `VerificationPipeline.run(..., attribute=True)`.

## [0.118.0] — 2026-10-07 — "Modular Workspace Package, Non-Bypassable Layer 1 & Localized Cell Evolution"

### Modular Workspace Architecture, Staged Pre-Commit & Localized Evolution
- **Modular Workspace Package (`soma_core/workspace/`)**:
  - Decomposes monolithic `workspace.py` into a cohesive, modular package: `base.py`, `git.py`, `discovery.py`, `confinement.py`, `scaffold.py`, and `hooks.py`.
  - Maintains strict backward compatibility via `soma_core.workspace` barrel exports.
- **Non-Bypassable Staged Layer 1 Pre-Commit Verification**:
  - Enhanced pre-commit lifecycle hook to deterministically execute Layer 1 verification (`DeterministicVerifier`) on git staged files during commit.
  - Blocks commits violating active invariants and prevents test regressions before changes leave the workspace.
- **Localized Cell Evolution & Compound Soma Fingerprinting**:
  - Restricts cell evolution in foreign repositories strictly to the local workspace boundary (`vacuole` $\rightarrow$ `wall` $\rightarrow$ `gate`).
  - Added compound fingerprinting in `Workspace.is_soma_repo` (requiring `soma-governance` package name in `pyproject.toml` plus `soma_core` and `soma_cli` packages) to prevent accidental mutation of external genomics repositories named `genome`.
- **Global Rules Cleanse & Quarantine Protocol**:
  - Whitelist-only quarantine system (`~/.soma/quarantine/`) protecting user platform rules.
  - Horizontal Gene Transfer porcelain command (`soma transfer export`) for explicit, audited rule sharing.

## [0.117.0] — 2026-10-07 — "Dual-Mode Verifier OOP & Frictionless In-Session Verification"

### Dual-Mode Verifier & Composable Architecture
- **Composable Verification Pipeline Hierarchy (`soma_core/verification/`)**:
  - Refactored verifier into `DeterministicVerifier`, `AdversarialVerifier`, `Arbiter`, and `VerificationPipeline`.
- **Dual-Mode Verification Support**:
  - In-session zero-API-key verification using in-band charge sheets and MCP Sampling (`sampling/createMessage`).
  - Headless SDK provider fallback for CI pipelines and automated testing.
- **Fast Git Integration & Isolated CI Gate**:
  - Subprocess-free fast paths in `GitWorkspace(Workspace)`.
  - Codified Isolated CI Environment Invariant (`HOME=$(mktemp -d) pytest`) guaranteeing zero test runner divergence.

## [0.116.0] — 2026-10-07 — "Multi-Repo Hook Ergonomics & Dedicated Hook Management"

### Porcelain Hook Management & Multi-Repo Worktree Ergonomics
- **Dedicated Porcelain Hook Subcommands (`soma_cli/hooks.py`)**:
  - `soma hook install`: Installs or updates Format 3 pre-commit hook into `.git/hooks/pre-commit`, with support for `--force` and `--dry-run`. Atomically written via PID temporary files with strictly normalized POSIX LF newlines (`\n`) to guard against Windows CRLF syntax errors in Git Bash.
  - `soma hook status`: Comprehensive hook diagnostics reporting installation status (`installed`, `outdated`, `not_installed`, `no_git_repository`), format version, worktree layout detection, and active interpreter resolution (`soma` on PATH, `$VIRTUAL_ENV`, `$PWD/.venv`, system `python3`), with full `--json` support.
  - `soma hook uninstall`: Safely strips the Soma managed block from `.git/hooks/pre-commit` while preserving any existing user-defined hooks or external tool runners. If only Soma content was present, deletes the file completely.
- **Hybrid Dispatcher (`soma_cli/hooks.py`, `soma_cli/cli.py`)**:
  - Maintains 100% backward compatibility with internal lifecycle hooks (`soma hook pre-commit`, `safety-gate`, `pre-invocation`, `session-close`, `post-session`).
  - Seamlessly disambiguates porcelain actions (`install`, `status`, `uninstall`) from lifecycle phases, defaulting to `status` when no subcommand or phase is provided.
- **Portable Cross-Platform Dynamic Hook Script (Format 3)**:
  - Dynamically probes active virtualenvs at hook runtime (`$VIRTUAL_ENV/bin/python`, `$VIRTUAL_ENV/Scripts/python.exe`, `$PWD/.venv/bin/python`, `$PWD/.venv/Scripts/python.exe`) without baking transient virtualenvs into shared `.git/hooks`.
  - Guards against the Microsoft Store exit-49 Python stub on Windows via `python3 -c "import sys; sys.exit(0)"` verification.
  - Enforces strict symlink security: refuses to modify symlinks pointing outside the repository boundary unless `--force` is specified.
- **Genesis & Init Integration (`soma_cli/genesis.py`, `soma_cli/init.py`)**:
  - `soma genesis`: Added `--install-hooks` and `--no-hooks` flags, with interactive user prompts in interactive sessions and confirmation output.
  - `soma init`: Added smart platform rules detection; when global platform rules already exist, skips the global rules prompt and immediately attaches Soma to the local repository.
- **Comprehensive Behavioral Test Suite (`tests/test_hook_ergonomics.py`)**:
  - 20 unit and behavioral tests validating porcelain commands, idempotency, non-Soma preservation, symlink guards, dynamic interpreter resolution, and Genesis hook automation.

## [0.115.0] — 2026-10-07 — "CLI Porcelain & Final Deprecation Gate"

### CLI Porcelain Architecture & Object Model Adoption
- **Uninitialized Workspace Model (`soma_core/workspace.py`)**:
  - `Workspace.for_init(path)`: Pure immutable constructor that validates target paths, rejects symlink traversal escapes (`not path.is_symlink()`), and returns a typed `Workspace` instance without requiring a pre-existing `.soma/cells/` directory.
  - `ws.scaffold(minimal=False, dry_run=False)`: Explicit filesystem method creating `.soma/cells/{vacuoles,walls,gates}` and `.soma/evidence/` directories, respecting dry-run and guarding against bare git repositories (`WorkspaceBareRepoError`).
  - Isolated git hooks attachment: `resolve_git_hooks_dir()` attaches hooks only if `(ws.root / ".git").exists()`, preventing nested monorepo subprojects from ambiently hijacking parent repository hooks.
  - Safe system directory resolution: Workspace walk-up avoids stopping at system temporary directories (`/tmp`, `/var/tmp`) or user home directory without explicit `.soma/cells/`.
- **Root Workspace Resolution (`soma_cli/cli.py`)**:
  - Centralized root resolution in `main()`:
    - `completion`: Exempt from workspace resolution.
    - `init`: Resolves via `Workspace.for_init(target_path)`.
    - All other subcommands: Resolve via `Workspace.resolve(target_path)` with strict argument precedence: `--workspace` > `--repo-root` / `--project-root` > `--_project_root` > CWD.
  - Attaches canonical `args.ws: Workspace` along with backward-compatible bridge attributes (`args._project_root`, `args.workspace`, `args.repo_root`, `args.project_root`).
- **Subcommand Migration & Decoupling (`soma_cli/`)**:
  - Migrated `init.py`, `doctor.py`, `status.py`, `verify.py`, `promote.py`, `demote.py`, `transfer.py`, `checkpoint.py`, `genesis.py`, `report.py`, `quarantine.py`, `prune.py`.
  - All command handlers consume `args.ws` with robust fallback (`getattr(args, 'ws', None) or Workspace.resolve(...)`) for direct test invocations bypassing `main()`.
  - Eliminated duplicate local `resolve_workspace()` helper definitions in `quarantine.py` and `transfer.py`, consolidating on `soma_core.workspace.Workspace`.
- **Architectural Deprecation Gate & AST Enforcement (`tests/test_architecture_decoupling.py`)**:
  - Added AST test verifying zero internal imports or invocations of deprecated standalone getters (`get_cells_dir`, `get_metrics_dir`, `get_signals_file`, `get_outcomes_file`) across `soma_core/`, `soma_cli/`, `soma_mcp/`, and `soma_sdk/`.
- **Comprehensive Behavioral Test Coverage (`tests/test_cli_workspace.py`, `tests/test_workspace_uninitialized.py`)**:
  - Added 15 new unit and behavioral tests verifying root resolution, argument precedence, handler fallback, subfolder isolation, uninitialized scaffolding, and symlink rejection.

## [0.114.0] — 2026-10-07 — "Core Engines Workspace Migration"

### Core Engines Architecture & Object Model Adoption
- **Lifecycle Subsystem (`soma_core/lifecycle/`)**:
  - `creation.py`: `create_cell`, `create_cell_from_description`, `transfer_cell` accept `Workspace` instances and use `ws.cells_dir`, `ws.metrics_dir`, `ws.root`.
  - `parsers.py`: `find_cell_file`, `find_cell`, `_load_evidence`, `_load_cells` accept `Workspace` instances and consume `ws.cells_dir`, `ws.evidence_dir`.
  - `promotion.py`: `evaluate_promotions`, `evaluate_demotions`, `promote_cell`, `demote_cell`, `evaluate_cell_tiers`, `metamorphose_cell`, `adapt_cell` accept `Workspace` instances and consume `ws.cells_dir`, `ws.soma_dir`, `ws.metrics_dir`.
  - `decay.py`: `compute_cells_fitness` accepts `Workspace` instances and consumes `ws.cells_dir`.
  - `selection.py`: `run_cell_selection`, `prune_cells`, `crossover_cells` accept `Workspace` instances and consume `ws.cells_dir`, `ws.evidence_dir`, `ws.metrics_dir`.
- **Arbitration Subsystem (`soma_core/arbitration.py`)**:
  - `_classify_protocol_python`, `get_escalation_protocol`, `load_oracles`, `evaluate_change`, `_consult_oracle`, `soma_propose_change`, `_load_fitness_evidence`, `_load_cells`, `generate_checkpoint` accept `Workspace` instances and consume `ws.cells_dir`, `ws.evidence_dir`, `ws.root`.
  - Checkpoint generation outputs stringified workspace root to ensure clean JSON serializability across tools.
- **Outcomes Subsystem (`soma_core/outcomes.py`)**:
  - `capture_mcp_outcomes`, `_insight_cursor_path`, `_read_insight_cursor`, `commit_insight_cursor`, `capture_human_insight_signals`, `read_human_insight_signals`, `match_cells_to_changes`, `record_verification_telemetry`, `harvest_git_history`, `run_outcome_engine` accept `Workspace` instances and consume `ws.soma_dir`, `ws.cells_dir`, `ws.signals_file`, `ws.root`.
  - Preserved module introspection hook (`getattr(m, 'resolve_workspace', resolve_workspace)`) for test monkeypatching compatibility.
- **Defects & Enforcement Subsystem (`soma_core/defects.py`, `soma_core/enforcement.py`)**:
  - `soma_core/defects.py`: `load_registry`, `load_report_from_workspace`, `record_escaped_defect`, `update_cell_escaped_rate`, `audit_expiry`, `prune_expired` accept `Workspace` instances.
  - `soma_core/enforcement.py`: `load_registry`, `verify_regression_tests`, `verify_readme_claims`, `load_cells_for_enforcement`, `generate_precommit_check`, `generate_gate_assertion`, `update_cell_enforcement_artifact`, `_match_cells`, `generate_ci_report` accept `Workspace` instances.
- **Synchronization Subsystem (`soma_core/sync.py`)**:
  - `load_soma_config`, `run_push`, `run_pull`, `run_post_session_hook` accept `Workspace` instances and consume `ws.cells_dir`, `ws.evidence_dir`, `ws.root`.
- **Workspace Coercion Primitive (`soma_core/workspace.py`)**:
  - Introduced `as_workspace(workspace)` helper function to cleanly coerce any representation (str, Path, os.PathLike, Workspace, or None) into a validated `Workspace` value object.
- **Deprecation Warnings on Standalone Getters (`soma_core/workspace.py`)**:
  - Standalone getters `get_cells_dir()`, `get_metrics_dir()`, `get_signals_file()`, and `get_outcomes_file()` now emit `DeprecationWarning` with `stacklevel=2` targeting removal in `v1.0.0`.
- **Comprehensive Behavioral Test Coverage (`tests/test_core_engines_workspace.py`)**:
  - Added 19 behavioral tests covering lifecycle, arbitration, outcomes, defects, enforcement, and sync interoperability with `Workspace` instances, plus deprecation warnings validation.

## [0.113.0] — 2026-10-07 — "Perimeter & Edge Workspace Migration"

### Perimeter Architecture & Object Model Adoption
- **MCP Server Confinement (`soma_mcp/server.py`)**:
  - Initialized `_canonical_workspace` as a strongly-typed `Workspace` value object at server startup.
  - Standardized shutdown session harvesting `_on_session_close()` to accept `Workspace` objects.
  - Re-exported `Workspace` directly from `soma_mcp/security.py` alongside security primitives.
- **MCP Tool Handlers (`soma_mcp/tools.py`)**:
  - Standardized all tool handlers (`soma_list_cells`, `soma_propose_change`, `soma_audit_security`, `soma_audit_performance`, `soma_verify_changes`, `soma_checkpoint`, `soma_scan`, `soma_report_outcome`, `soma_capture_insight`, `soma_generate_manifest`, `soma_grade`, `soma_coverage`, `soma_fitness`) on `_get_workspace()` returning a `Workspace` value object.
  - Replaced manual path concatenations and redundant `confine_workspace()` calls with direct `ws.confine_path()` and `ws.cells_dir` invocations.
- **State-Bound Receipts Integration (`soma_core/receipts.py`)**:
  - Supported `Workspace` instances across `ReceiptStore.issue()`, `ReceiptStore.verify()`, `compute_file_digest()`, and `compute_cell_digest()`.
  - Normalized workspace storage to canonical string paths so receipts issued with a `Workspace` instance verify equivalently against string paths.
- **Python SDK Porcelain (`soma_sdk/governance.py`)**:
  - Wired `self.workspace: Workspace` into `Governance`, deriving `self.root`, `self.cells_dir`, and `self.metrics_dir` directly from the value object while maintaining 100% backward compatibility with `Path` accessors.
- **Comprehensive Test Coverage (`tests/test_perimeter_workspace.py`)**:
  - Added 10 comprehensive behavioral tests covering `Governance` workspace instantiation, receipts workspace interoperability, and MCP server/tool handler execution with `Workspace` value objects.

## [0.112.0] — 2026-10-07 — "Workspace Value Object & Error Hardening"

### Strongly-Typed Architecture & Object Model
- **Immutable `Workspace` Value Object (`soma_core/workspace.py`)**:
  - Implemented `@dataclass(frozen=True)` `Workspace` implementing `os.PathLike[str]` for zero-overhead path manipulation, worktree-aware hook resolution, and path containment.
  - Added property accessors: `root`, `soma_dir`, `cells_dir`, `metrics_dir`, `evidence_dir`, `signals_file`, `git_hooks_dir`, `is_worktree`.
  - Added factory methods: `Workspace.resolve()` (7-step walk-up order) and `Workspace.confine()` (validation of `.soma/cells/` existence).
  - Implemented path division operator (`ws / "sub"`) and `__fspath__()` for seamless interoperability with standard library functions (`open()`, `pathlib.Path`, `os.path`).
- **Domain Exception Hierarchy (`soma_core/errors.py`)**:
  - Added `WorkspaceError` (subclassing `SomaValidationError` and `ValueError`).
  - Added `WorkspaceNotFoundError` (`code="ERR_WORKSPACE_NOT_FOUND"`).
  - Added `PathTraversalError` (`code="ERR_PATH_TRAVERSAL"`).
  - Preserves 100% backward compatibility with existing `except ValueError:` blocks.
- **Strangler Fig Dual-Mode Compatibility**:
  - Retained standalone helper functions (`resolve_workspace`, `resolve_workspace_path`, `confine_workspace`, `confine_path`, `get_cells_dir`, `get_metrics_dir`, `get_signals_file`, `validate_cell_names`) as backward-compatible wrappers delegating to `Workspace`.

### Hardened Error Handling & CLI Diagnostics
- **Explicit Git Hooks Exception Narrowing**:
  - Replaced bare `except Exception:` in `resolve_git_hooks_dir()` with explicit types: `(subprocess.SubprocessError, FileNotFoundError, PermissionError, UnicodeDecodeError, OSError)`.
- **Proactive PATH Guidance in `soma init`**:
  - Wired `soma_cli.pathcheck.build_hint()` into `soma init` completion output so developers receive immediate, shell-specific remedy guidance if `soma` is not in their active `$PATH`.
- **Comprehensive Test Coverage**:
  - Added `tests/test_workspace_model.py` and `tests/test_init_pathcheck.py` with 13 new behavioral tests verifying path confinement, domain exception inheritance, immutable value object contracts, and PATH diagnostics.

## [0.111.0] — 2026-10-07 — "Git Worktree Hooks & Cell Schema Integrity"

### Git Worktrees & Tooling Hardening
- **Git Worktree Hook Installation & Health Detection (`BUG-082`)**:
  - Implemented `resolve_git_hooks_dir()` in `soma_core/workspace.py` using `git rev-parse --git-path hooks` with a zero-dependency fallback reading `gitdir:` and `commondir` from worktree git files.
  - Updated `soma init` (`soma_cli/init.py`) to install pre-commit hooks into the common git directory when run from worktrees, preventing silent bypass of hook installation.
  - Updated `soma doctor` (`soma_cli/doctor.py`) to resolve and check the worktree's active hooks directory, eliminating false negative health reports.
  - Added regression test suite `tests/test_worktree_hooks.py`.

### Cell Lifecycle & Schema Integrity
- **Cell Creation Frontmatter Enforcement Schema (`BUG-083`)**:
  - Updated `create_cell()` in `soma_core/lifecycle/creation.py` to accept and validate the `enforcement` frontmatter attribute (`advisory`, `mechanical`, `gate`), defaulting walls to `gate` and other cell types to `advisory`.
  - Added `-e` / `--enforcement` parameter to `soma_core/lifecycle/creation.py:cli_cell_create()`.
  - Added `enforcement` to required frontmatter schema instructions in `create_cell_from_description()` and MCP `build_cell_create_prompt()`.
  - Exported canonical `VALID_ENFORCEMENT` tuple in `soma_core.lifecycle`.
  - Added regression test suite `tests/test_cell_creation_enforcement.py`.

## [0.110.0] — 2026-10-06 — "Ambient Telemetry & Zero-Touch Evolution"

### Ambient Telemetry & Evolutionary Automation
- **Ambient Verification Telemetry (`soma verify` & MCP Tools)**:
  - Instrumented `soma verify`, MCP `verify_changes`, and async verification jobs to record ambient execution evidence automatically.
  - Generates `trigger` and outcome (`tp`/`fp`) signals in `.soma/evidence/signals.jsonl` on verification exit without requiring manual model self-reports (`soma_report_outcome`).
- **MCP Session Shutdown Outcome Reflection**:
  - Wired in-process outcome reflection (`run_outcome_engine()`) into the `finally:` block of `run_stdio_server()` in `soma_mcp/server.py`.
  - Captures human insight cursors and evaluates evolutionary promotions/decay automatically when the host agent terminates or disconnects, redirecting telemetry logs safely to stderr.
- **Historical Git Retro-Harvesting (`soma harvest`)**:
  - Implemented `soma harvest` (`--git`, `--limit`, `--dry-run`, `--json`) backed by `harvest_git_history()` in `soma_core/outcomes.py`.
  - Inspects historical git commit diffs, matches touched paths against cell target patterns, and mints baseline fitness evidence.
  - Enforced strict deterministic commit-hash idempotency keys (`{commit}:trig:{cell}` / `{commit}:tp:{cell}`) and guarded execution with `evidence_lock()` to prevent race conditions and payload conflicts.
- **Lazy Read-Time Aging & Checkpoint Decay**:
  - Implemented dynamic decay evaluation in `soma_core/arbitration.py` (`_classify_cell`), evaluating rule age lazily against `expiry_days` or 90/180-day decay/dormant thresholds upon reading.
  - Updated `soma oracle` and `generate_checkpoint()` to reflect `decaying` (🍂) and `dormant` (💤) rule states in real-time with zero background daemons or cron jobs.
- **Accurate Branch Coverage Disassembly & Docstring State Tracking**:
  - Upgraded `_TRACE_SCRIPT_TEMPLATE` in `soma_core/verification/branch_coverage.py` with bytecode disassembly (`dis.findlinestarts`) and multiline docstring state tracking (`"""` / `'''`).
  - Eliminates false-positive uncovered code warnings on multiline docstrings, single-line docstrings, comments, and closing structural brackets.

## [0.109.0] — 2026-10-06 — "Security & Core Hardening"

### Security & Inference Hardening
- **SSRF & Credential Exfiltration Prevention (`BUG-073`)**:
  - Hardened `resolve_key()` in `soma_core/inference_provider.py` to reject network endpoint configuration (`*_BASE_URL`, `*_URL`, `ENDPOINT`, `HOST`) from untrusted workspace configuration files (`.soma/soma.conf`), preventing malicious repositories from exfiltrating host credentials.
- **Command Safety Bundled Flag Unwrapping (`BUG-074`)**:
  - Enhanced `unwrap_command_stage()` in `soma_core/command_safety.py` to parse POSIX short flag bundles (`-*c`, e.g. `bash -lc`, `sh -ec`), closing a command inspection evasion vector.
- **Destructive Command Trailing Slash Normalization (`BUG-075`)**:
  - Normalized path arguments in `evaluate_rm()` to strip trailing slashes (`rstrip("/\\")`) and added `/root` to `RM_DANGEROUS_TARGETS`, closing destructive command detection bypasses.
- **MCP Session Authentication Enforcement (`BUG-076`)**:
  - Enforced fail-closed session token authentication in `soma_mcp/server.py` when session tokens are active or when `SOMA_REQUIRE_SESSION_TOKEN=1` is set, eliminating unauthenticated execution bypasses.
- **Google GenAI SDK Automatic Function Calling (AFC) Advisory Warning Silencing (`BUG-081`)**:
  - Explicitly configured `config={"automatic_function_calling": {"disable": True}}` in `GeminiProvider.generate()`, suppressing upstream SDK advisory warnings on stderr during single-turn LLM inference.

### Core Decoupling & Verification Integrity
- **Layer 0 Core Decoupling (`BUG-079`)**:
  - Relocated and canonicalized `parse_frontmatter` into `soma_core.cell_inventory` with zero external dependencies, eliminating layer inversion imports in `checkpoint_checks.py`.
- **Layer 1 Multi-Target Evidence Grouping (`BUG-078`)**:
  - Indexed Layer 1 evidence as multi-target lists in `soma_core/verification/arbiter.py`, preventing dictionary key overwrites and ensuring all tool failures are surfaced to the Arbiter.
- **AST Default Argument Fallback (`BUG-077`)**:
  - Wrapped `ast.literal_eval` with `ast.unparse` fallback in `soma_core/verification/immune_verify.py` to robustly handle complex non-literal default arguments.
- **C1 Control Sequence & Stderr Display Sanitization (`BUG-080`)**:
  - Extended `sanitize_display()` to strip 8-bit C1 control characters (`[\x80-\x9f]`) and wrapped out-of-tree filenames in `soma_cli/verify.py` to prevent terminal injection.
- **Call Graph Trailing `__all__` Export Resolution**:
  - Re-evaluated `is_exported` post-traversal in `soma_core/verification/call_graph.py` to accurately recognize exports declared after function and class definitions.

## [0.108.0] — 2026-10-06 — "Two-Layer Adversarial Rebuttal & Verification Test Harness"

### Verification Engine & Adversarial Rebuttal Protocol
- **Two-Phase Adversarial Exchange (Prosecution $\rightarrow$ Defense Rebuttal)**:
  - Eliminated the uncoordinated "Battleship" guessing flaw in Layer 2 verification where independent Spec and Code Agents had to blindly guess the same risk categories.
  - Serialized Layer 2 execution: Spec Agent predictions are now passed directly into the Code Agent defense prompt as specific charges (`category`, `severity`, `risk`, `affected_function`) to defend or concede.
  - Maintained strict information partitioning: Code Agent prompt never contains task plan text, only structured predicted failure modes.
- **CLI Test Discovery & Execution Harness**:
  - Implemented `discover_test_evidence()` in `soma_cli/verify.py` to auto-discover matching test files for target source files via AST traversal.
  - Automatically runs targeted pytest suites and feeds real `test_names` and `test_results` into `runner.run_layer2()`, providing concrete test evidence for Code Agent defense claims.
- **Dispatch Table Call Graph Inspection**:
  - Enhanced `InternalCallCollector` in `soma_core/verification/call_graph.py` to inspect AST `Dict`, `List`, `Tuple`, `Set`, `Assign`, and `Call` keyword arguments.
  - Eliminates false-positive `ORPHAN FUNCTIONS` warnings on command dispatch handlers (`COMMANDS = {"check": cmd_verify}`).

## [0.107.0] — 2026-10-06 — "Porcelain Aliases, Output Ergonomics & Pre-Seed Target Constraints"

### CLI Porcelain Aliases & Output Ergonomics
- **Intuitive Porcelain Subcommand Aliases**:
  - Added `soma check` as a direct porcelain alias for `soma verify`, supporting identical parameters (`--files`, `--layer1-only`, `--plan`, `--plan-file`, `--provider`, `--dry-run`).
  - Added `soma rules` as a porcelain alias for `soma status`, allowing developers to inspect active governance rules naturally.
  - Added `soma audit` as a porcelain alias for `soma doctor`, unifying health and governance policy audits.
- **Ergonomic Output Controls (`--plain` / `--no-emoji`)**:
  - Added `--plain` and `--no-emoji` global CLI flags to `common_parser` to strip Unicode emojis and ANSI formatting.
  - Implemented `format_plain()` in `soma_cli` to convert emojis (e.g. `[WALL]`, `[TRAP]`, `[PASS]`, `[FAIL]`) for clean, parseable output across non-UTF-8 terminals (e.g. Windows cp1252) and CI/CD log pipelines.
  - Added `format_status_summary()` in `soma_cli/status.py` decoupling default status outputs from internal biological metaphors unless `--plumbing` is explicitly passed.

### JIT Engine Pre-Seed Target Constraints (GitHub Issue #77)
- **Pre-Edit File Constraint Injection**:
  - Implemented `extract_target_constraints()` in `soma_mcp/jit_engine.py` to inspect target files during `soma_scan` and extract non-negotiable invariants and traps before code generation occurs.
  - Returns structured `target_constraints` summary key in `express()` payload containing target file, invariants, traps, and rule tiers.
  - Prepends a prominent `## Pre-Edit Invariants & Constraints` early-warning section to JIT prompt context, eliminating post-generation rejection token waste.
  - Seeded early-warning section length into JIT token accounting to strictly adhere to `max_jit_tokens`.

### Bug Registry Updates
- Logged and tracked:
  - `BUG-070`: CI ModuleNotFoundError on `google.genai` during optional test execution.
  - `BUG-071`: GitHub Issue #75 JIT token bloat and lack of budget clamping.
  - `BUG-072`: GitHub Issue #77 lack of pre-seeded active target file constraints in `soma_scan`.

## [0.106.0] — 2026-10-06 — "JIT Context Budget Clamping & Two-Layer Verification Gate"

### JIT Engine & Context Budget (GitHub Issue #75)
- **Configurable JIT Context Budget Clamping**:
  - Implemented token estimation and cumulative token budget clamping in `soma_mcp/jit_engine.py` (`express()` and helper functions).
  - Added `estimate_tokens()` using industry-standard ~4 chars/token heuristic with non-string type safety.
  - Added `resolve_token_budget()` supporting multi-tiered precedence: explicit `max_tokens` argument > `SOMA_MAX_JIT_TOKENS` environment variable > `MAX_JIT_TOKENS` from `soma.conf` > default 2,000 tokens. Handles `workspace=None` gracefully.
  - Added priority cell injection: frontmatter wall rules (`enforcement: wall` or `tier: wall`) are prioritized before non-wall rules, ensuring non-negotiable security boundaries are never clamped out in favor of soft guidelines.
  - Saturated budgets cap rule injection and append an explicit `<!-- JIT Budget Exceeded: remaining rules clamped -->` disclosure tag.
  - Added default `MAX_JIT_TOKENS=2000` to `install/soma.conf.example`.

### Release Workflow & Verification Governance
- **Mandatory Gate 4.5 Integration**:
  - Formally codified Gate 4.5 (Two-Layer Adversarial Verification) into `docs/project/RELEASE_WORKFLOW.md`.
  - Added pre-release verification protocol executing `soma verify --plan ...` with real-time Arbiter convergence/divergence analysis.
  - Verified live against Gemini 3.8 Flash (`gemini-3.8-flash`) achieving clean `SHIP` verdict (6 convergences, 0 divergences).

### Strict TDD Compliance
- Authored behavioral unit test suite in `tests/test_jit_context_budget.py` adhering to `tdd-protocol.md` and `feature-specs.md §6` with 7 test cases covering default limits, environment variable overrides, config file parsing, priority cell inclusion, and Gate 4.5 workflow documentation invariants.

### CI/CD & Test Isolation
- **Hermetic Optional Dependency Mocking**:
  - Replaced direct `patch("google.genai.Client")` in `tests/test_inference_provider.py` with `patch.dict(sys.modules, ...)` module mocking.
  - Resolves CI test suite failures across Ubuntu, Windows, and macOS environments where optional dependency `google-genai` is not pre-installed in the clean runner environment.

## [0.105.0] — 2026-10-06 — "True AST Call Graph Traversal & Static Analysis"

### Verification & Core Engine (Phase 8 Scorecard Remediation)
- **True AST Call Graph Traversal Engine**:
  - Replaced shallow regex matching (`re.compile(rf'\b{func_name}\s*\(')`) in `soma_core.verification.call_graph` with a robust Python AST visitor (`FunctionDefinitionVisitor`, `InternalCallCollector`, `ExternalModuleInspector`).
  - Added scope-aware call site resolution ignoring mentions in docstrings, block comments, and string literals.
  - Eliminated external module identifier collisions: external module invocations like `subprocess.run()`, `sys.exit()`, and `math.sqrt()` no longer collide with or masquerade as internal definitions.
  - Added export recognition: functions and classes exposed via module-level `__all__` (such as public SDK and package exports) are recognized as public interfaces and exempted from orphan flags.
  - Added cross-module direct invocation tracking resolving imports across files in the target root.
  - Maintained sub-millisecond execution performance through AST candidate pre-filtering.
- **Inference Provider Modernization & Default Models**:
  - Added explicit `DEFAULT_MODEL` class attribute and `default_model` property across all inference providers: Gemini (`gemini-3.8-flash`), Anthropic (`claude-3-5-sonnet-latest`), OpenAI (`gpt-4o`), and Prompt-Only (`human`).
  - Migrated `GeminiProvider`, `compute_token_census`, and Layer 2 arbitration from retired `gemini-2.0-flash` / `gemini-2.5-flash` to active `gemini-3.8-flash`.
  - Authored unit test suite in `tests/test_inference_provider.py` verifying default model resolution and token counting contracts.
- **Strict TDD Compliance**:
  - Authored comprehensive behavioral test suite in `tests/test_verification/test_call_graph_ast.py` adhering to `tdd-protocol.md` and `feature-specs.md §6` with 10 test cases proving Red/Green correctness across comments, string literals, collisions, class methods, exports, and syntax handling.

## [0.104.0] — 2026-10-06 — "Layer 2 Adversarial Verification CLI Wiring"

### CLI & Verification (Phase 7 Scorecard Remediation)
- **Layer 2 Adversarial Verification CLI Integration**:
  - Connected `soma verify` to the Layer 2 adversarial verification engine (`soma_core.verification.runner.run_layer2`).
  - Added `--plan` argument for passing natural language task plans or prompt context.
  - Added `--plan-file` argument for loading task specifications directly from disk.
  - Added `--provider` argument for explicitly selecting inference backends (`gemini`, `anthropic`, `openai`, `keyring`, `prompt`).
  - Implemented automatic plan discovery checking standard locations (`docs/plan.md`, `.soma/plan.md`, `PLAN.md`).
- **Graceful Deterministic Fallback**:
  - Automatically falls back to Layer 1 deterministic checks when no inference provider or API keys are available, logging a clean notice without crashing.
  - Returns exit code 0 when Layer 1 passes under graceful fallback.
- **Arbiter Output & Exit Code Mapping**:
  - Added `format_layer2_summary` to present human-readable Arbiter verdicts, divergences, and convergences.
  - Enforced strict exit code contract: `SHIP` maps to 0; `BLOCK` and `REVISE` map to 1.
- **Clean Repository Zero-Exit**:
  - Fixed false-alarm exit code 1 when running `soma verify` on clean repositories with 0 changed files. Reports `Layer 1: 0 files changed (clean repository)` and exits 0 immediately.
- **Documentation & Import Integrity**:
  - Purged phantom JavaScript SDK snippet (`const { Governance } = require('soma-governance')`) from `README.md`.
  - Fixed 5 latent `NameError` missing imports in error branches across `soma_core.lifecycle.creation` (`os`), `soma_core.lifecycle.promotion` (`sys`), `soma_core.evidence` (`Path`), `soma_core.sweep_session` (`Path`), and `soma_core.verification.runner` (`ArbitrationResult`).
  - Added automated `ruff check --select F821` invariant test in `tests/test_static_invariants.py` and updated `tdd-protocol.md` Gate 4 to mandate static import integrity checks before green phase sign-off.
- **Strict TDD Compliance**:
  - Full Red/Green TDD lifecycle adhering to `tdd-protocol.md` and `feature-specs.md §6` with 13 new behavioral and invariant tests in `tests/test_cli_verify.py` and `tests/test_static_invariants.py`.

## [0.103.0] — 2026-10-06 — "Legacy Sunset & Lifecycle Modularization"

### Architecture & Modularization (Phase 6 Bloat Elimination)
- **Sunset Legacy Verification Shims (`immune_system/`)**:
  - Removed 18 legacy forwarding shims and mulch queue stubs in `immune_system/` (-323 LOC).
  - Repointed all test suites (19 test files) to canonical `soma_core.verification` and `soma_core.lifecycle`.
  - Cleaned package configurations across `pyproject.toml`, `Makefile`, `.gitignore`, and wheel smoke validation.
- **Pruned Unmaintained JavaScript SDK (`soma_sdk_js/`)**:
  - Removed outdated zero-dependency Node.js client (-889 LOC) to focus on the pure-stdlib Python SDK and MCP server.
  - Retired obsolete SDK parity contract `.soma/cells/plasmodesmata/contract-sdk-feature-parity.md` and pruned documentation references.
- **Sunset Dead Epoch Migration Engine (`soma_cli/migration.py`)**:
  - Purged epoch migration CLI command and test suite (-640 LOC).
  - Created tombstone regression tests `test_bug_019_epoch_migration_purged` and `test_bug_025_migration_lock_purged` in `tests/test_legacy_purged_regressions.py` guaranteeing BUG-019 and BUG-025 traceability.
- **Purged Dead Install Stubs (`install/starter_pack.txt`)**:
  - Removed unused static starter pack file in favor of runtime template generators.
- **Modularized Lifecycle Engine (`soma_core/lifecycle/`)**:
  - Decomposed 1,884-line monolithic `soma_core/lifecycle.py` into a cohesive `soma_core/lifecycle/` package:
    - `constants.py`: status enumerations, thresholds, path constants, and metadata mappings.
    - `parsers.py`: cell parsing, slug generation, frontmatter transforms, and atomic file maneuvers.
    - `quorum.py`: lifecycle state predicates (`calculate_fitness_status`, `is_promotable`, `is_extinct`).
    - `decay.py`: exponential decay, Bayesian fitness scoring, and aggregate fitness calculation.
    - `creation.py`: cell creation (`create_cell`, `create_cell_from_description`), CLI and transfer handlers.
    - `promotion.py`: promotion, demotion, tier evaluation, adaptation, and metamorphosis.
    - `selection.py`: selection pressure, crossover (`crossover_cells`), and cell pruning.
    - `__init__.py`: backward-compatible facade re-exporting all 53 public symbols in `__all__`.

## [0.102.0] — 2026-10-06 — "Facade Hardening & Final Prune"

### Architecture & Pruning (Final Bloat Remediation Phase)
- **Modularized MCP Tool Execution & Architecture (`soma_mcp/tools.py`)**:
  - Decomposed 483-line monolithic `execute_tool()` into modular per-tool handlers with a declarative `_TOOL_HANDLERS` dispatch dictionary.
  - Eliminated syntax anomalies (`if` vs `elif`) across verify and grade handlers.
  - Streamlined `_list_cells_stdlib` with centralized path matching and canonical inventory traversal.
  - Preserved `TOOL_DEFINITIONS = [...]` literal AST assignment ensuring 100% contract and documentation test compatibility.
- **Hardened SDK Facades (`soma_sdk/`)**:
  - Pruned 5 dead legacy enzyme stubs in `soma_sdk/governance.py` (`_run_script`, `replay`, `trends`, `dependencies`, `adversarial`).
  - Pruned dead write hook registry (`_post_write_hook` and `register_write_hook`) from `soma_sdk/cells.py`.
  - Cleaned obsolete legacy comments and verified typing across `soma_sdk/hot_zones.py`, `soma_sdk/scoring.py`, and `soma_sdk/telemetry.py`.
- **Cleaned Leftover Empty Shims & Dead Patterns**:
  - Pruned empty tuple `DESTRUCTIVE_PATTERNS: tuple[...] = ()` in `soma_cli/hooks.py`.
  - Pruned unreferenced `STARTER_RULES_LEGACY` from `soma_cli/init.py`.
- **Package Startup & Import Optimization (`soma_core/__init__.py`)**:
  - Implemented PEP 562 dynamic attribute resolution (`__getattr__`) for submodules and heavy symbols in `soma_core/__init__.py`.
  - Defers eager loading of `asyncio` and `storage`, dropping cold `import soma_core` latency by ~16x (from 54ms to ~3.3ms) and process startup (`soma --help`) to 41ms.
- **Completed 5-Phase Bloat Elimination Initiative**:
  - Verified 100% green verification battery: all 2,626 tests passing, 69 bug regressions verified, and all claims passing.

## [0.101.0] — 2026-10-06 — "Immune System Unification & Lifecycle Consolidation"

### Architecture & Unification (Bloat Remediation)
- **Unified Canonical Verification Framework (`soma_core/verification/`)**:
  - Migrated 12 verification and quality assurance modules (`arbiter.py`, `branch_coverage.py`, `call_graph.py`, `checkpoint_checks.py`, `immune_verify.py`, `import_guard.py`, `mutation_tester.py`, `persistence_checker.py`, `quality_gate.py`, `review_adapter.py`, `runner.py`, `transcript_verifier.py`) into canonical package `soma_core/verification/`.
  - Replaced 3,672 lines in `immune_system/verification/*.py` with lightweight backward-compatibility facade modules mirroring attributes and re-exporting all symbols for 100% backward compatibility.
- **Consolidated Duplicate Lifecycle Engine (`soma_core/lifecycle.py`)**:
  - Unified `evaluate_promotions` and `evaluate_demotions` (and signal ledger readers `_load_evidence`, `_load_cells`, `_cell_age_days`) into [`soma_core/lifecycle.py`](../../soma_core/lifecycle.py), establishing a single canonical lifecycle engine.
  - Eliminated duplicate lifecycle transition engine file `immune_system/verification/lifecycle.py`, replacing with a backward-compatible shim.
  - Streamlined `cli_cell_create` description generation in `soma_core/lifecycle.py`, eliminating ~50 lines of duplicate cell writing code.
- **Rerouted Internal Callers to Canonical Verification**:
  - Rerouted `soma_cli/checkpoint.py`, `soma_cli/hooks.py`, and `soma_mcp/tools.py` to import `checkpoint_checks` from `soma_core.verification.checkpoint_checks`.
  - Rerouted `soma_cli/promote.py` and `soma_cli/demote.py` to import from `soma_core.lifecycle`.
  - Rerouted `soma_cli/verify.py` and `soma_mcp/tools.py` to import from `soma_core.verification`.
  - Rerouted `soma_core/verification_jobs.py` to target `soma_core.verification.runner`.
- **Purged Deprecated Enzyme Stubs**:
  - Stripped `_safe_import_enzyme` and `_ENZYME_ALLOWLIST` from `soma_mcp/tools.py` per ADR-013.
  - Removed obsolete `TestEnzymeImportAllowlist` from `tests/test_security.py`.
- **Documentation & Scripts Reference Accuracy**:
  - Updated `docs/architecture/scripts.md` and `tests/test_documentation_accuracy.py` to catalog 12 verification scripts under `soma_core/verification/` (74 total scripts).

## [0.100.0] — 2026-10-06 — "Core God Module Decomposition & Verification Deduplication"

### Architecture & Decomposition (Bloat Remediation)
- **Decomposed `soma_core/telemetry.py` God-Module (1,911 LOC -> ~450 LOC)**:
  - Extracted verifiable outcome reflection, credit assignment, fitness signals, transcript updater, and ACE reflector loop into [`soma_core/outcomes.py`](../../soma_core/outcomes.py).
  - Extracted token census aggregation, metrics snapshot persistence, cell quorum sensing, coverage mapping, and immune report cards into [`soma_core/metrics.py`](../../soma_core/metrics.py).
  - Retained canonical atomic evidence ledger, process-level locks, and epoch generation fences in [`soma_core/telemetry.py`](../../soma_core/telemetry.py).
  - Implemented module facade proxy on `soma_core.telemetry` mirroring attribute mutations and re-exporting all symbols for 100% backward compatibility.
- **Decomposed `soma_core/sync.py` God-Module (1,206 LOC -> ~750 LOC)**:
  - Extracted subagent liveness & deadlock detection, protocol escalation recommender, and last-gasp apoptosis sentinels into [`soma_core/sentinels.py`](../../soma_core/sentinels.py).
  - Fixed hidden file stripping bug in `classify_file` where `.github/` lost its leading period.
  - Re-exported all sentinel functions and sensitivity patterns in `soma_core.sync`.
- **Deduplicated Triplicate Cell Matching Algorithms**:
  - Unified `match_cells_to_changes`, `match_cells`, and `_match_cells` into canonical `find_matching_cells` in [`soma_core/cell_inventory.py`](../../soma_core/cell_inventory.py).
  - Eliminated divergent path separator normalization and glob edge cases.
- **Consolidated OS File Locking**:
  - Replaced raw `fcntl`/`msvcrt` imports in `soma_core/telemetry.py` with centralized, cross-platform locking primitives from [`soma_core/locking.py`](../../soma_core/locking.py).
- **Added Canonical Colocated Test Suites**:
  - Added [`tests/test_outcomes.py`](../../tests/test_outcomes.py), [`tests/test_metrics.py`](../../tests/test_metrics.py), and [`tests/test_sentinels.py`](../../tests/test_sentinels.py) with 100% test colocation parity and green `soma checkpoint`.

## [0.99.0] — 2026-10-06 — "Core/CLI Decoupling & Legacy CLI Purge"

### Removed (Bloat Elimination)
- **Purged 29 Legacy `cli_*` CLI Wrappers Trapped in `soma_core/`**:
  - Pruned dead CLI parser functions embedded in `soma_core/lifecycle.py` (`cli_cell_transfer`, `cli_cell_demote`, `cli_cell_metamorphose`, `cli_cell_adapt`, `cli_cell_selection`, `cli_cell_fitness`).
  - Pruned dead CLI wrappers in `soma_core/homeostasis.py` (`cli_soma_sleep`, `cli_soma_coherence`, `cli_soma_interoception`, `cli_resilience_engine`).
  - Pruned dead CLI wrappers in `soma_core/defects.py` (`cli_diagnose_hot_zones`, `cli_cell_escaped_defects`, `cli_cell_expiry`).
  - Pruned dead CLI wrappers in `soma_core/insights.py` (`cli_insight_capture`, `cli_insight_correlator`).
  - Pruned dead CLI wrappers in `soma_core/sync.py` (`cli_liveness_sentinel`, `cli_escalation_sentinel`, `cli_team_sync`, `cli_hgt_ribosome`, `cli_immune_sweep`, `cli_post_session_hook`).
  - Pruned dead CLI wrappers in `soma_core/telemetry.py` (`cli_outcome_engine`, `cli_fitness_updater`, `cli_metrics_snapshot`, `cli_cell_quorum`, `cli_cell_coverage`, `cli_immune_grade`).
  - Pruned dead CLI wrappers in `soma_core/arbitration.py` (`cli_oracle`) and `soma_core/enforcement.py` (`cli_cell_enforce`).
  - Net core reduction: >1,000 lines of deadwood pruned from `soma_core/`, eliminating all unused `argparse` imports.
- **Eliminated Forwarding Layer `soma_cli/handlers/` and Stale Handler Tests**:
  - Deleted legacy forwarding package `soma_cli/handlers/` (`lifecycle.py`, `sentinels.py`, `sync.py`, `telemetry.py`, `__init__.py`).
  - Deleted `tests/test_cli_handlers.py`.

### Added
- **Pure Core Tier Evaluation (`soma_core.lifecycle.evaluate_cell_tiers`)**:
  - Extracted tier decay and promotion evaluation logic out of legacy CLI wrappers into a pure library function in `soma_core/lifecycle.py`.
- **CLI Subcommand Support for `--tier-check`**:
  - Wired `--tier-check` flag into `soma promote` in `soma_cli/promote.py` and `soma_cli/cli.py` with support for both human-readable summaries and machine-readable `--json` output.

## [0.98.0] — 2026-10-06 — "Test Suite Rationalization & Deadwood Pruning"

### Removed (Bloat Elimination)
- **Purged 83 Mirrored Contract Test Stubs**:
  - Eliminated 83 individual 1:1 mirrored stub files across `tests/soma_core/`, `tests/soma_cli/`, `tests/soma_mcp/`, `tests/soma_sdk/`, and `tests/immune_system/`.
  - Replaced with a single dynamic, parameterized test suite in `tests/test_module_contracts.py` that verifies every module in the repository imports cleanly and exports valid symbols.
- **Purged 11 Obsolete Test Suites Guarding Deleted v0.97.0 Assets**:
  - Removed 2,647 lines of dead test code that executed zero passing tests and 100% skipped tests for purged `enzymes/` and shell scripts (`test_uninstall_confinement.py`, `test_python_resolution.py`, `test_install_lifecycle.py`, `test_shell_isolation_behavioral.py`, `test_enzyme_console_encoding.py`, `test_tournament_integration.py`, `test_cell_deps_behavioral.py`, `test_installer_security_hardening.py`, `test_home_isolation.py`, `test_cell_signal.py`, `test_immune_sweep.py`).
  - Net test file reduction: 94 files removed; overall codebase reduced by 3,300+ lines.
  - Eliminated 140 dead skipped tests in pytest runs.

### Added
- **Consolidated Module Contract Suite (`tests/test_module_contracts.py`)**:
  - Parameterized clean-import verification across all 84 repository modules in 0.15s.
- **Dedicated SDK Analysis Unit Tests (`tests/test_sdk_analysis.py`)**:
  - Added fast, deterministic unit test coverage for `soma_sdk.analysis` (`shannon_diversity`, `letter_grade`, `specificity_penalty`, `antifragile_bonus`).
- **Legacy Purged Regression Tombstones (`tests/test_legacy_purged_regressions.py`)**:
  - Preserved auditability and Invariant 6 (`test_mulch_invariants.py`) for historical `BUG_REGISTRY.json` items while asserting purged scripts remain absent.

### Changed
- **Relocated Command Safety Tests**:
  - Moved rich behavioral test suite from `tests/soma_core/test_command_safety.py` to canonical `tests/test_command_safety.py`, keeping all 101 tests intact.
- **Main Entrypoint Guard**:
  - Guarded `soma_cli/__main__.py` with `if __name__ == '__main__':` to prevent unintended top-level execution on programmatic import.

## [0.97.1] — 2026-10-06 — "Structured Command Safety & Pattern De-bloating"

### Added
- **Structured Lexical Command Analyzer (`soma_core.command_safety`)**:
  - Implemented pure-stdlib `CommandAnalyzer` featuring lexical tokenization (`shlex`), state automaton, wrapper unwrapping (`sudo`, `env`, `nice`, `time`, `nohup`, `xargs`), quote-aware subshell extraction, and recursion depth clamps (ADR-014).
  - Exported `CommandAnalyzer` and `SafetyEvaluation` in `soma_core/__init__.py`.
  - Added canonical 1:1 mirrored test suite in `tests/soma_core/test_command_safety.py` (101 unit tests).

### Changed
- **Safety Gate De-bloating & Refactoring (`soma_cli.hooks`)**:
  - Replaced brittle shell regular expressions (`_GIT_CMD_PREFIX`, `_GIT_GLOBAL_OPTS`, `_GIT_CMD`, and 22 redundant `DESTRUCTIVE_PATTERNS`) with structured `CommandAnalyzer` evaluation in `run_safety_gate()`.
  - Converted remaining unstructured regexes (`SECRET_REPLACEMENTS`) to documented, readable `re.VERBOSE` patterns.
  - Added `--delete` to dangerous git flags in fast-path allowlist.

### Documented
- **ADR-014 (Command Tokenization Over Regex Builder DSL)**:
  - Formally codified rejection of regex builder DSL in favor of stdlib lexical command tokenization.
- **Scripts Reference (`docs/architecture/scripts.md`)**:
  - Cataloged `soma_core/command_safety.py`, updating MCP & Core modules count to 29 and repository runtime total to 72.

## [0.97.0] — 2026-10-06 — "The Sunset Phase: Legacy Enzymes Purge, Native Platform Adapters & Dynamic Colocality"

### Removed (Breaking Changes)
- **Purged Legacy `enzymes/` Directory**:
  - Permanently deleted all 75 legacy enzyme scripts from the repository tree following the v0.96.2 deprecation bridge.
  - Removed `enzymes*` inclusions and package-data rules from `pyproject.toml` and `MANIFEST.in`.
  - Cleaned enzyme gate counts and path exceptions from `.github/workflows/validate.yml` and `.github/scripts/wheel_smoke.py`.
- **Purged Shell & PowerShell Installers**:
  - Removed legacy `install/install.sh`, `install/install.ps1`, `install/uninstall.sh`, and `install/uninstall.ps1` (4,277 LOC) in favor of pure-Python platform adapters.

### Added
- **Native Platform Adapters (`soma_cli.platforms`)**:
  - Introduced `PlatformAdapter` ABC and concrete adapters for `GeminiAdapter`, `ClaudeAdapter`, `CopilotAdapter`, `KiroAdapter`, and `McpAdapter`.
  - Wired `soma install --platform <name>` and `soma uninstall --platform <name>` commands to execute native, subprocess-free configuration and hook management across Linux, macOS, and Windows.
- **1:1 Mirrored Test Package Structure**:
  - Established canonical package test directories (`tests/soma_core/`, `tests/soma_cli/`, `tests/soma_mcp/`, `tests/soma_sdk/`, `tests/immune_system/`) providing 1:1 test coverage mirrors for all 83 core modules (AC-2C.1).
  - Configured `addopts = "--import-mode=importlib"` in `pyproject.toml` for hermetic test module isolation without name collisions.

### Changed
- **Fully Dynamic Checkpoint Test Resolution**:
  - Eliminated the legacy hardcoded `SOURCE_TO_TEST_MAP` dictionary (75 mappings) from `immune_system/verification/checkpoint_checks.py`.
  - Implemented dynamic candidate resolution for subpackages, handlers, and platform adapters, allowing `check_test_coverage()` to run 100% dynamically with zero hardcoded lookup tables.
- **Documentation & Governance Cell Re-anchoring**:
  - Synchronized `docs/architecture/scripts.md` and `README.md` to catalog 71 pure-Python runtime modules.
  - Repointed all membrane, wall, and vacuole governance cells to pure-Python `soma_core` and `soma_cli` entrypoints.


### Added
- **Core Value Object Schemas (`soma_core.schemas`)**:
  - Introduced immutable dataclasses `CellMetadata`, `TransitionResult`, and `SignalEvent` in `soma_core.schemas` for domain modeling.
  - Defined frozen `Receipt` schema in `soma_core.schemas.receipts` representing cryptographically authenticated tool execution receipts.
- **Encapsulated `ReceiptStore` (`soma_core.receipts`)**:
  - Replaced mutable module globals with thread-safe `ReceiptStore` class featuring bounded capacity eviction and TTL expiration.
- **Test Harness (`tests.harness`)**:
  - Implemented `SomaTestHarness` providing high-level cell creation, evidence generation, and workspace scaffolding with zero test base-class inheritance.
  - Registered `harness` fixture in `tests/conftest.py`.
- **Governance Wall (`.soma/cells/walls/wall-test-canonical-colocality.md`)**:
  - Codified canonical test colocality requirement preventing base-class inheritance anti-patterns.
- **Dual-Resolution Test Discovery (`immune_system/verification/checkpoint_checks.py`)**:
  - Enhanced checkpoint checks with canonical mirrored test discovery supporting both mirrored paths and legacy lookup tables.
- **CLI Handlers Package (`soma_cli.handlers`)**:
  - Extracted CLI argument parsing and formatting out of `soma_core` into dedicated handler modules: `lifecycle`, `sentinels`, `telemetry`, and `sync`.
- **Atomic Workstream Protocol**:
  - Codified 2–5 file micro-step decomposition protocol in repository genome (`genome/.oracles/atomic-workstream-protocol.md`).

### Changed
- **Enzyme Shims Deprecation**:
  - Added `DeprecationWarning` to `enzymes/__init__.py` signaling removal in upcoming v0.97.0 breaking release.
- **MCP Client Direct Execution**:
  - Repointed `soma_mcp/tools.py` directly to `soma_core.arbitration.soma_propose_change` and `soma_core.insights.capture_insight`.
- **Decoupled Telemetry Frontmatter Parsing**:
  - Repointed `soma_core.telemetry._parse_frontmatter` to `soma_core.frontmatter.parse_cell_frontmatter`, eliminating circular dependencies between `telemetry` and `lifecycle`.
- **Storage & Locking Resilience**:
  - Hardened POSIX/Windows locking CRT release guards in `soma_core.locking`.
  - Scaled atomic storage retry backoff to 8 attempts (~2.55s) in `soma_core.storage`.
- **Deadwood Pruning**:
  - Removed deprecated `enzymes/bump_version.py` and `enzymes/bump_version.sh` and removed `bump` recipe from `Makefile`.

## [0.96.1] — 2026-10-06 — "100% Zero-Dependency Runtime & Stdlib Frontmatter Engine"

### Added
- **Pure-Stdlib Frontmatter Engine (`soma_core.frontmatter`)**:
  - Implemented 100% Python standard library YAML subset parser and dumper capable of round-tripping all repository governance cells and metadata files without PyYAML.
  - Added support for wrapped multiline plain scalars with automatic indentation continuation.
  - Added support for same-indent sequences (`key:\n- item`) matching standard YAML conventions.
  - Added support for literal (`|`) and folded (`>`) block scalars with chomping indicators (`-`, `+`, clip).
  - Added support for multiline quoted strings with unicode (`\uXXXX`) and escaped space/newline (`\ `, `\\\n`) escapes.
  - Enhanced `dump_frontmatter` with optional `body` parameter for complete document generation and clean standard library formatting.
  - Added comprehensive behavioral test suite `tests/test_frontmatter_engine.py` covering all supported YAML syntax features.
- **Repository-Wide Zero Third-Party Import Invariant (SOMA-C02)**:
  - Upgraded static invariant from MCP-only `SOMA-C01` to repo-wide `SOMA-C02` in `tests/test_static_invariants.py`, statically guaranteeing zero bare third-party package imports across `soma_cli/`, `soma_core/`, `soma_mcp/`, `soma_sdk/`, and `enzymes/`.

### Changed
- **Zero Runtime Dependencies**:
  - Completely removed `pyyaml>=6.0` from `pyproject.toml [project.dependencies]`, making Soma a 100% zero-dependency framework at runtime (`dependencies = []`).
  - Moved PyYAML to `[project.optional-dependencies] dev` solely for testing GitHub Actions workflows.
  - Purged all `import yaml` statements across 14 runtime modules and 26 test suites in favor of stdlib `parse_frontmatter` and `dump_frontmatter`.
  - Updated `soma doctor` to verify the zero-dependency runtime state via `_check_zero_dependencies()`.
  - Updated `genome/.oracles/optional-import-guard.md` to reflect 0 required runtime dependencies.

### Documented
- Added ADR-012 (`docs/architecture/decisions/ADR-012-zero-dependency-frontmatter-engine.md`) detailing the motivation, syntax coverage, performance, and trade-offs of the pure standard library frontmatter engine.

## [0.96.0] — 2026-10-05 — "Core Domain Consolidation, Common Method Centralization & 1.0.0 Release Prep"

### Added
- **Developer Porcelain Facade & Ergonomics**:
  - Added `soma rules` (`soma_cli/rules.py`): Query and search genome rules with regex pattern matching, status filters, and multi-format output (`text`, `json`, `markdown`).
  - Added `soma analyze` (`soma_cli/analyze.py`): Holistic workspace telemetry, waste rate trajectory, and cell fitness health analysis.
  - Added `soma prune` (`soma_cli/prune.py`): Interactive and batch pruning of extinct and dormant governance cells with safety confirmations.
  - Added `soma_sdk.governance.Governance` porcelain methods: High-level Python facade exposing `record_outcome`, `create_cell`, `create_rule`, and `rule_fitness`.
  - Added in-process helper functions `compute_cells_fitness` (`soma_core/lifecycle.py`) and `compute_token_census` (`soma_core/telemetry.py`) eliminating external subprocess overhead.
- **Pure-Stdlib Layer 0 Foundations**: Added `soma_core/scoring.py` and `soma_core/workspace.py` providing zero-dependency Wilson confidence interval scoring, SNR computation, and deterministic workspace root resolution decoupled from higher-level SDK packages.
- **Domain-Specific Core Engines**: Consolidated fragmented enzyme logic into cohesive Layer 0 modules under `soma_core/`:
  - `soma_core/arbitration.py`: Test-to-code (TTC) verification, deterministic oracle scoring, and checkpoint validation.
  - `soma_core/enforcement.py`: Pre-commit cell enforcement, CI outcome reporting, bug registry integrity, and documentation claim verification.
  - `soma_core/defects.py`: Escaped defect reporting, cell expiry pruning, and hot-zone diagnosis.
  - `soma_core/insights.py`: Structured insight capture and correlation engine.
  - `soma_core/homeostasis.py`: Session sleep memory consolidation, system coherence checking, interoception health reporting, and resilience engine.
  - `soma_core/sync.py`: Escalation sentinel, subagent liveness monitoring, team sync, HGT ribosome, immune sweep, and post-session hooks.
  - `soma_core/telemetry.py`: Telemetry signal processing, outcome engine, fitness updater, metrics snapshotting, cell quorum, cell coverage, and immune grading.
  - `soma_core/lifecycle.py`: Complete cell genetics and lifecycle domain (cell creation, promotion, demotion, transfer, metamorphosis, adaptation, selection, crossover, and fitness evaluation).

### Changed
- **Core Layer Decoupling & In-Process Execution**: Strictly enforced unidirectional architecture ensuring `soma_core` maintains zero upward imports into `soma_sdk`, `soma_cli`, `soma_mcp`, or `enzymes`. Replaced subprocess script forks in core sync and telemetry with direct module calls.
- **Public API Surface Definitions**: Added explicit `__all__` exports to 9 core helper modules (`receipts`, `locking`, `storage`, `frontmatter`, `evidence`, `quarantine`, `errors`, `verification_jobs`, `cell_inventory`).
- **Enzyme Forwarding Shims**: Converted 58 top-level enzymes into thin, backward-compatible dual-mode forwarding shims delegating to `soma_core/` while preserving full CLI parity, exit codes, monkeypatch hooks, and AST console encoding invariants.
- **CLI Flag Inheritance**: Attached `common_parser` parent to `soma completion` subcommand, allowing global options (`--plumbing`, `-v`, `-q`, `--format`) to be passed cleanly.
- **Scripts Architecture Reference**: Updated `docs/architecture/scripts.md` cataloging 149 executable modules (25 MCP/Core modules).
- **Single-Sourced Version Synchronization**: Synchronized release version `0.96.0` across all repository surfaces (`VERSION`, `pyproject.toml`, `README.md`, `soma_sdk/__init__.py`, `soma_sdk_js/package.json`, `docs/KNOWN_ISSUES_WINDOWS.md`, and `SECURITY.md`).

### Fixed
- **POSIX Flock Reentrancy Self-Deadlock**: Tracked lock acquisition depth via thread-local storage (`_lock_tls`) in `soma_core/telemetry.py::evidence_lock`, preventing reentrant POSIX flock self-deadlocks on Linux/macOS.
- **Single-Use Token Burn Timing**: Enforced unconditional single-use token invalidation upon redemption attempt (`consume=True`) in `soma_core/receipts.py`, eliminating brute-force parameter probing.
- **Rate Limiting Lease Isolation & Rollback Policy**: Implemented thread-local rate limit leases (`_mcp_tls`) and eliminated artificial rollbacks on tool execution failure, preventing token starvation while tracking genuine invocation attempts.
- **Python 3.9 Compatibility in MCP Server**: Added `from __future__ import annotations` and `Optional[str]` annotations to `soma_mcp/server.py`, preventing `TypeError: unsupported operand type(s) for |` during wheel smoke tests on Python 3.9 runners.
- **Canonical Relative Path Hashing in File Digests**: Normalized file paths relative to workspace root using POSIX forward slashes in `compute_file_digest`, preventing digest mismatch on relocated directories or Windows runners.
- **Constant-Time Byte-Safe HMAC Comparison**: Verified string types and encoded signatures to UTF-8 bytes before `hmac.compare_digest` in `soma_mcp/integrity.py::verify_signature`.
- **Outcome Session ID Scoping**: Defaulted `idempotency_scope` in `soma_sdk.governance.Governance.record_outcome` to `session_id if session_id else "global"` and forwarded `session_id` into telemetry signals.
- **Deduplicated YAML Frontmatter Parsing**: Delegated `soma_sdk/cells.py::_stdlib_parse_frontmatter` to `soma_core.frontmatter.parse_yaml_subset`.
- **Safe Post-Session Hook Execution**: Prevented `post-session` hook from triggering mutating `session-close` when transcript is missing, cleanly returning code 0 with a diagnostic message.
- **MCP Outcome Enum Parity**: Added `"pass"` and `"fail"` to `soma_report_outcome` input schema enum and mapped to `tp`/`fp`.
- **Invariant 6 Verification Rigor**: Strengthened Invariant 6 in `tests/test_mulch_invariants.py` to assert exact bug registry record count (`len(bugs["bugs"]) == 69`), sorted BUG_REGISTRY.json numerically, and verify ID uniqueness via `verify_unique_ids`.
- **Post-Tempest Remediations (C-01 to C-10, W-01 to W-19, I-01 to I-13)**:
  - **Layer Decoupling & Ingress Concurrency (C-01, C-02, C-03, C-10, W-02, W-06, W-07)**: Migrated `inference_provider`, `sweep_session`, and `evidence_collector` to `soma_core/`, popped receipts under lock immediately on redemption attempt, eliminated rate-limit quota eviction fallback, added `soma_request_receipt` dispatch handler in `soma_mcp/tools.py`, added AST Call dynamic import tests to Invariant 1, and isolated leases with `contextvars.ContextVar`.
  - **Security & Integrity Fail-Closed Gates (C-04, C-05, W-08, W-09, W-10, W-14, I-03, I-05)**: Enforced `CellCacheError` fail-closed on HMAC errors, returned exit code 1 on critical oracle checkpoints, handled unicode surrogate characters in constant-time comparisons, buffered file digest reads in 64KB chunks, added strict arbitration evidence checks, and added `CONIN$` and `CONOUT$` to Windows device guards.
  - **Workspace Resolution & Telemetry Inversion (C-06, C-07, C-08, W-01, W-03, W-04, W-17)**: Removed `start=__file__` workspace subversion across all enzymes and core modules, normalized `record_outcome` string arguments (`"fail"` / `"fp"` to `"fp"`), re-raised contract conflict exceptions (`EventConflictError`, `StaleGenerationError`), stripped `.md` extension in cell promotion, and mapped singular `rule_id`/`cell_id` to `cells_used` in MCP.
  - **CLI Flags, SDK Facades & Error Handling (C-09, W-13, W-15, W-16, W-18, I-01, I-02, I-04, I-09, I-10, I-11, I-12, I-13)**: Added `--workspace` to `common_parser` and unified root resolution, captured pytest stdout in regression test diagnostics, added `Governance.parse_cell_file` and delegated to `soma_core.frontmatter`, exported full SDK `__all__`, supported `--format json` in `soma status`, and confined paths in MCP security/performance audits.
  - **Invariant Rigor, Documentation & Parity (W-05, W-11, W-12, W-19, I-06, I-07, I-08)**: Completed `soma_core.enforcement.__all__`, added `__all__` presence assertion across all 19 `soma_core` modules, single-sourced version verification across `README.md` and `SECURITY.md`, and added parity methods to the JavaScript SDK (`recordOutcome`, `createRule`, `ruleFitness`, `parseCellFile`).

## [0.95.0] — 2026-10-05 — "Architecture Consolidation, Deep Defense & Storage Resiliency"

### Added
- **Pure-Python CLI Commands**: Added `soma transfer` (`soma_cli/transfer.py`) for cell transfers with fitness resets and `soma quarantine` (`soma_cli/quarantine.py`) for inspecting, listing, and pruning quarantined corrupt files.
- **Crash-Resilient Atomic Storage**: Added `soma_core/storage.py` providing `atomic_write_text`, `atomic_write_bytes`, and `async_atomic_write_text` with exponential backoff retry on Windows sharing violations (`WinError 32 ERROR_SHARING_VIOLATION`), directory fsync, and automatic cleanup of partial writes.
- **Quarantine Lifecycle Management**: Added `list_quarantine`, `inspect_quarantined_file`, and `prune_quarantine` in `soma_core/quarantine.py` with robust timestamp extraction from filenames (`<stem>.<timestamp>.corrupt`) and logs, plus universal UTF-8 BOM (`utf-8-sig`) decoding.
- **Verification Worker Registry & Bounded Shutdown**: Implemented `_ACTIVE_WORKERS` thread registry tracking and bounded join in `soma_core/verification_jobs.py` `shutdown_verification_engine`, ensuring clean worker termination without zombie processes or orphaned threads.

### Changed
- **Shell Enzyme Retirement & Consolidation**: Replaced bulky legacy shell implementations in `enzymes/safety_gate.sh`, `enzymes/immune_init.sh`, `enzymes/session_close.sh`, and `enzymes/cell_transfer.sh` with ultra-thin backward-compatible forwarding shims delegating to `soma_cli.hooks` and `soma_cli.transfer`, reducing over 800 lines of brittle shell code.
- **Scripts Architecture Reference**: Updated `docs/architecture/scripts.md` cataloging 140 executable modules (21 CLI commands, 16 MCP/Core modules).
- **Single-Sourced Version Synchronization**: Synchronized release version `0.95.0` across all repository surfaces (`VERSION`, `pyproject.toml`, `README.md`, `soma_sdk/__init__.py`, `soma_sdk_js/package.json`, `docs/KNOWN_ISSUES_WINDOWS.md`, and `SECURITY.md`).

### Fixed
- **Shell Evasion & Metacharacter Bypass**: Enhanced safety gate in `soma_cli/hooks.py` with pre-tokenization sanitization and multi-stage quote/escape dequoting, blocking command obfuscation (`\rm -rf /`, `r"m" -rf /`, `'r'm`, `git diff --o\utput=`).
- **Word-Bounded Branch Deletion Matching**: Fixed `soma_cli/hooks.py` regexes to require word boundaries and whitespace before flags (`\s+-(?:[a-zA-Z0-9]*[dDMf]...)\b`), preventing benign branch names with hyphens (e.g. `git branch feature-dashboard`) from being falsely blocked.
- **Git Config & Exec-Path Injection Guard**: Blocked arbitrary command execution via git option injection (`git -c`, `git --exec-path`, `git --config-env`) in `soma_cli/hooks.py`.
- **Deep Defense Path Traversal & Windows Device Names**: Hardened `confine_path` in `soma_mcp/security.py` and `enzymes/ttc_verifier.py` against null bytes (`\x00`), Windows reserved device names (`CON`, `PRN`, `AUX`, `NUL`, `COM1-9`, `LPT1-9`), NTFS alternate data streams (`:`), and extended device namespaces (`\\?\`, `\\.\`).
- **Strict Argument Type Validation**: Hardened `verify_receipt` in `soma_core/receipts.py` and MCP dispatch in `soma_mcp/tools.py` (`soma_scan`, `soma_verify_changes`, `soma_report_outcome`, `soma_capture_insight`) to reject non-string and non-list inputs with structured errors rather than unhandled type exceptions.

## [0.94.1] — 2026-10-05 — "Zero-Flaw Concurrency, Cross-Platform Parity & Sandbox Hardening"

### Fixed
- **CI xdist Flag Portability** (C-01): Corrected `pytest` argument detection in `Makefile` to check `--numprocesses` instead of `-n` (which clashed with `--no-header`), and added `pytest-xdist==3.6.1` to GitHub Actions workflow jobs (`validate.yml`), preventing unrecognized argument failures on fresh runner environments.
- **Windows Path Glob Normalization** (C-02): Resolved path matching failure in `enzymes/fitness_updater.py` where backslashes prevented `fnmatch` from matching POSIX-style glob patterns (`src/**`), fixing zero-cell signal regressions on Windows runners.
- **Thread-Reentrant FileLock Self-Deadlock** (C-03): Integrated thread-local recursion counters (`_THREAD_STATE`) into `soma_core/locking.py` `workspace_lock`, eliminating self-deadlock when the same thread re-acquires a lock across nested transactional operations.
- **Whitespace JSONL Quarantine False-Positive** (C-04): Fixed `soma_core/quarantine.py` `safe_read_jsonl` to require at least one non-whitespace line before triggering corruption quarantine, preventing healthy blank telemetry files from being unlinked.
- **Cell File Frontmatter Parser Integrity** (C-05): Added `startswith("---")` verification to `soma_core/quarantine.py` `safe_parse_cell_file`, preventing markdown files containing horizontal rules (`---`) in their body from suffering silent content truncation.
- **Safety Gate Metacharacter & Dangerous Flag Enforcement** (C-06): Hardened fast-path command validation in `soma_cli/hooks.py` by adding `(`, `)` subshell delimiters to metacharacters, blocking concatenated git branch deletion flags (e.g. `-Dmain`), and catching destructive write flags (`--output=`, `--ext-cmd=`).
- **MCP Tool Path Traversal Confinement** (C-07): Enforced strict workspace path confinement (`confine_path`) across `soma_scan` and `soma_propose_change` parameters in `soma_mcp/tools.py`, neutralizing directory traversal payloads attempting to escape the repository root.
- **Windows CLI Unicode Console Encoding** (C-08, I-03): Installed `sys.stdout.reconfigure(errors="replace")` guards at the entrypoint of all `soma_cli` tools (`hooks.py`, `checkpoint.py`, `demote.py`, `promote.py`, `pathcheck.py`), and extended `tests/test_enzyme_console_encoding.py` to continuously guard the entire `soma_cli/` package against Windows `cp1252` encoding crashes.
- **Worker Status Preservation on Daemon Shutdown** (W-01): Guarded verification pipeline worker state updates in `soma_core/verification_jobs.py` to prevent background threads from overwriting terminal `FAILED` status set during server shutdown.
- **Atomic Single-Use Receipt Invalidation** (W-02): Updated `soma_core/receipts.py` `verify_receipt(..., consume=True)` to invalidate single-use receipt tokens on failed verification attempts as well as successful ones, closing replay windows.
- **Zero-Signal SNR Boundary Invariant** (W-03): Corrected `CellFitness.snr_db` in `soma_sdk/cells.py` to return `-float("inf")` when $tp == 0$ and $fp > 0$ (pure noise), distinguishing defective cells from balanced 1:1 signal-to-noise ratios.
- **Unified Domain Error Hierarchy** (W-04): Inherited `soma_sdk.errors.SomaError` from `soma_core.errors.SomaError`, unifying exception handling across core and SDK consumer boundaries.
- **Checkpoint Coverage Mapping Reconciled** (W-05): Cleaned up phantom test mappings in `immune_system/verification/checkpoint_checks.py` `SOURCE_TO_TEST_MAP`, synchronizing registered files with actual behavioral suites.
- **Version Bump Test Fixture Completeness** (I-01): Populated all 7 release surfaces in `tests/test_phase4_enzymes.py` `test_bump_version_dry_run` and asserted strict exit code `rc == 0`.
- **Package Hierarchy Mutation Testing** (I-02): Enhanced `immune_system/verification/mutation_tester.py` to support regex-based package import patching (`from pkg.mod import ...`), allowing `test_pythonpath_package_import` to be un-skipped and verified green.
- **PowerShell MCP Interpreter Detection** (I-04): Updated `Merge-SomaMcpConfig` in `install/install.ps1` to dynamically resolve working Python interpreters rather than hardcoding `python3`.

## [0.94.0] — 2026-10-05 — "Operational Resilience, Invariant Correctness & Zero-Overhead Optimization"

### Added
- **Cross-Process & Thread-Safe File Locking** (Phase 2): Added `soma_core/locking.py` with `FileLock`, `ProcessSafeJSON`, cross-process timeout recovery, stale lockfile eviction (>60s), and reentrant thread synchronization for concurrent mutations across multiple processes.
- **Self-Healing File Quarantine & Atomic Fallback** (Phase 2): Added `soma_core/quarantine.py` with `QuarantineManager` to isolate corrupt or unparseable JSON/YAML files (`.soma/quarantine/<timestamp>_<filename>`), auto-heal empty or partial files, and ensure zero unhandled read crashes during high-concurrency cell indexing and telemetry ingestion.
- **Protected Daemon Worker Lifecycle** (Phase 2): Hardened background worker threads in `soma_core/verification_jobs.py` with graceful shutdown, queue draining, thread health checks, and worker respawn semantics.
- **Typed Domain Error Hierarchy** (Phase 3): Added `soma_core/errors.py` with concrete domain exceptions (`SomaError`, `SomaValidationError`, `CellCorruptError`, `ReceiptExpiredError`, `LockTimeoutError`) for deterministic error handling and failure diagnostics across the core engine.
- **Property-Based Invariant Verification** (Phase 3): Added `tests/test_math_properties.py`, `tests/test_idempotency.py`, and `tests/test_domain_errors.py` leveraging Hypothesis to mathematically prove Wilson confidence score bounds (`0.0 <= lower <= upper <= 1.0`), Laplace smoothing monotonicity, and lifecycle state transition idempotency.
- **Pure-Python Enzyme Migration & CLI Entrypoints** (Phase 4): Migrated 12 utility shell enzymes to standalone, native Python modules with backwards-compatible shell wrappers: `cell_create.py`, `cell_selection.py`, `cell_signal.py`, `cell_transfer.py`, `export_logs.py`, `immune_sweep.py`, `liveness_sentinel.py`, `log_finding.py`, `metrics_snapshot.py`, `post_session_hook.py`, `team_sync.py`, and `bump_version.py`. Added comprehensive unit tests in `tests/test_phase4_enzymes.py`.
- **Parallel Test Runner Integration** (Phase 1): Integrated `pytest-xdist>=3.5.0` and pinned `hypothesis>=6.100.0` in `pyproject.toml`, achieving a 3.9x acceleration in verification velocity (~71s down to ~18s across 2,270+ tests).

### Changed
- **Sub-0.1ms Safety Gate Fast-Path** (Phase 5): Optimized `soma_cli/hooks.py` with an instantaneous regex-compiled allow-list decision tree for benign, read-only commands (`git status`, `ls`, `cat`, `pytest`, etc.), clocking a 0.087ms mean execution latency (over 50x faster than the 5ms target).
- **Zero-Copy Directory Scanning** (Phase 5): Refactored evidence scanning and source-dir traversals in `immune_system/verification/checkpoint_checks.py` from `os.walk` to zero-copy `os.scandir` iterators, eliminating redundant string allocations and filesystem stat calls.
- **Fast-Path Cell Retrieval** (Phase 5): Optimized `soma_sdk/cells.py` (`get_cell`) with direct parent/subdirectory existence probes before falling back to recursive directory walks.
- **Unified Review & Apoptosis Escalation Sentinel** (Phase 4): Unified `enzymes/escalation_sentinel.py` to support dual-mode invocation: git-based sensitivity and diff review protocol recommendations alongside cell apoptosis emergency shutdowns.
- **Scripts Architecture Reference**: Updated `docs/architecture/scripts.md` cataloging 137 modules (69 utility automation scripts).
- **Single-Sourced Version Synchronization**: Synchronized release version `0.94.0` across all repository surfaces (`VERSION`, `pyproject.toml`, `README.md`, `soma_sdk/__init__.py`, `soma_sdk_js/package.json`, `docs/KNOWN_ISSUES_WINDOWS.md`, and `SECURITY.md`).

### Fixed
- **Subshell Overhead Elimination**: Replaced 18 legacy shell invocations with direct pure-Python execution paths, retaining backwards-compatible `.sh` delegations for external script invocations.
- **Windows Console Unicode Output Guard**: Enforced `sys.stdout.reconfigure(errors='replace')` guards across all CLI and enzyme scripts, preventing `UnicodeEncodeError` on legacy Windows `cp1252` consoles when emitting formatting emojis and symbols.
- **Pre-Commit Checkpoint Test Map Parity**: Registered all newly introduced enzymes in `SOURCE_TO_TEST_MAP` within `immune_system/verification/checkpoint_checks.py`, maintaining zero pre-commit warnings.

## [0.93.0] — 2026-10-05 — "Autonomous Lifecycle & Multi-Platform Parity"

### Added
- **Unified Cell Lifecycle State Machine** (Phase 1): Added `soma_core/lifecycle.py` defining canonical lifecycle states (`NEW`, `SURVIVE`, `ADAPT`, `EXTINCT`, `APOPTOSIS`, `WALL`, `GENOME`), Laplace-smoothed score calculations with Wilson bounds, protected rule invariants, and automated promotion/demotion evaluation.
- **Cross-Platform Lifecycle Hook Runner** (Phase 2, BUG-014, BUG-032): Added `soma_cli/hooks.py` and registered `soma hook <phase>` (`python -m soma_cli.hooks <phase>`), enabling native, pure-Python lifecycle hook execution (`pre-commit`, `safety-gate`, `pre-invocation`, `session-close`) on Windows without bash dependencies.
- **Native PowerShell Hook Deployment** (Phase 2): Added `-Hooks` switch and `Install-Hooks` function to `install/install.ps1`, replacing legacy bash warnings with native hook configuration for Gemini and Kiro platforms, and cross-platform pre-commit hook installation.
- **Asynchronous Verification Engine & Job Polling** (Phase 3): Added `soma_core/verification_jobs.py` with in-memory thread-safe job state machine (`QUEUED`, `RUNNING`, `COMPLETED`, `FAILED`), TTL cleanup, and background worker threads. Added `soma_poll_verification` read-only MCP tool with annotations for non-blocking Layer 2 verification polling and receipt issuance.
- **Arbitration Cycle 4 Evidence**: Added `.soma/evidence/arbitration_cycle_4.json` recording 0 divergences, 100% convergence across 4 files, and clean `SHIP` arbiter verdict.

### Changed
- **MCP Verification Async Mode**: Updated `soma_verify_changes` in `soma_mcp/tools.py` with optional `async_mode` parameter, returning immediate job tracking tokens when requested.
- **MCP Server Capabilities**: Expanded read tools to 9 (16 total advertised tools) in `soma_mcp/server.py` and updated rate limiting (`soma_poll_verification` up to 60 calls/min).
- **Scripts Architecture Reference**: Updated `docs/architecture/scripts.md` cataloging 122 scripts across all 7 categories (19 CLI commands, 12 MCP/Core modules).
- **Single-Sourced Version Synchronization**: Synchronized release version `0.93.0` across all repository surfaces (`VERSION`, `pyproject.toml`, `README.md`, `soma_sdk/__init__.py`, `soma_sdk_js/package.json`, and `docs/KNOWN_ISSUES_WINDOWS.md`).

### Fixed
- **PowerShell Rule Encoding & BOM Parity** (BUG-014): Explicit UTF-8 decoding and encoding in `install/install.ps1`, preserving UTF-8 BOM across Windows PowerShell 5.1 and PowerShell 7.
- **PowerShell Lifecycle Hook Parity** (BUG-032): Resolved absence of lifecycle hooks on native Windows environments via `soma hook` integration in `install/install.ps1`.
- **Pre-Commit Checkpoint Noise Elimination**: Added `SOURCE_TO_TEST_MAP` (57 mappings) and directory-aware candidate test discovery in `immune_system/verification/checkpoint_checks.py`, eliminating 67 false-positive `Missing test file for...` warnings during pre-commit checks.
- **Cross-Platform Temp Directory Portability**: Replaced hardcoded `/tmp` paths in `enzymes/ttc_verifier.py` with standard `tempfile.gettempdir()`.
- **Bug Registry Full Resolution**: Verified all 69 registered bugs in `docs/project/BUG_REGISTRY.json` are fixed and verified (0 open bugs remaining).

## [0.92.3] — 2026-10-05 — "Maelstrom & Adaptive Remediation"

### Added
- **Kiro Platform Support** (BUG-066, C-08): Added platform detection, steering rules directory mapping (`.kiro/steering/`), installed skill discovery, and CLI help choices for the Kiro agent environment.
- **Standalone Frontmatter Parser** (BUG-064, C-06): Added `soma_core/frontmatter.py` as a zero-dependency frontmatter and metadata parser, decoupling `soma_sdk/governance.py` from the MCP JIT runtime engine and eliminating layer inversion.
- **Protected Rules Demotion Guard** (BUG-067, C-09): Added `PROTECTED_RULES` protection in `soma_cli/demote.py`, strictly prohibiting demotion of foundational governance rules (`cost-optimization`, `providence`, `git-workflow`, `architectural-tenets`, `testing`, `tdd-protocol`).
- **Cryptographic Receipt Capacity & Expiry** (W-01): Added TTL expiration pruning and capacity capping (`MAX_RECEIPTS = 1000`) in `soma_core/receipts.py` to prevent memory exhaustion and replay attacks.
- **MCP Layer Transparency** (W-07): Added explicit transparency notifications when Layer 2 adversarial verification is requested over MCP, clarifying that MCP execution defaults to Layer 1 verification.

### Changed
- **Threshold & Extinction Alignment** (I-06): Realigned cell fitness status boundaries in `enzymes/cell_fitness.py` (`0.15 <= dec_score <= 0.7` for `ADAPT`, `< 0.15` for `EXTINCT`), establishing mathematical consistency with `soma_sdk/cells.py` and `tests/test_threshold_recalibration.py`.
- **Escalation Sentinel Diff Metric** (BUG-068, C-10): Rewrote `get_diff_size` in `enzymes/escalation_sentinel.sh` to calculate inserted plus deleted lines via `git diff --numstat` instead of counting changed files, and prevented subsequent Rule 6 checks from downgrading prior high-severity escalations.
- **Evidence Credit Weights** (W-06): Bound `credit_weight` within `[0.0, 10.0]` in `soma_core/evidence.py` to prevent unbounded telemetry manipulation of fitness scoring ledgers.
- **MCP Cell Cache Protection** (W-04): Prevented in-place cache mutation in `soma_mcp/jit_engine.py` by performing defensive copies of cell dictionaries before attaching runtime scoring metadata.
- **Single-Sourced Version Synchronization** (I-04): Synchronized release version `0.92.3` across all 6 repository surfaces (`VERSION`, `pyproject.toml`, `README.md`, `soma_sdk/__init__.py`, `soma_sdk_js/package.json`, and `docs/KNOWN_ISSUES_WINDOWS.md`).

### Fixed
- **Shell Injection & Unicode Escapes in Hook** (BUG-059, C-01): Quoted heredocs and escaped Git log parameters in `enzymes/post_session_hook.sh`, preventing shell code execution and `\U` unicode syntax crashes on arbitrary commit messages.
- **MCP Fail-Closed Integrity Verification** (BUG-060, C-02): Enforced fail-closed exception handling (`CellCacheError`) in `soma_mcp/cell_cache.py` when HMAC or manifest signatures fail, eliminating silent bypasses.
- **Telemetry Contract Normalization Drift** (BUG-061, C-03): Unified symmetric normalization across `enzymes/outcome_engine.py` and `soma_sdk/telemetry.py` readers and writers, preventing dropped outcome events during replay.
- **Infinite Root-Walk Loops on Windows and Container Roots** (BUG-062, C-04): Hardened upward traversal in `enzymes/cell_create.sh`, `enzymes/cell_signal.sh`, `enzymes/team_sync.sh`, and `enzymes/cell_transfer.sh` to check for both `/` and `dirname "$curr" == "$curr"`, preventing infinite loops on Windows drives (`C:`) and container mount points.
- **Uninstall Rule Truncation in CLAUDE.md** (BUG-063, C-05): Replaced brittle regex cuts in `install/uninstall.sh` with safe delimiter parsing to prevent orphaning rule bodies or truncating user files to EOF.
- **Packaged Module Import Failures** (BUG-065, C-07): Resolved bare sibling imports in `enzymes/oracle_checkpoint.py` with dynamic `sys.path` injection and package-relative resolution.
- **ZeroDivisionError on Telomere Days** (BUG-069, C-11): Added type and zero guards in `enzymes/cell_fitness.py` and `enzymes/fitness_landscape.py` against invalid, zero, or `None` `telomere_days` attributes.
- **Test Tautology and Duplication Elimination** (T-01 to T-04):
  - *T-01*: Removed shadowed duplicate definitions of `test_retry_after_partial_append` in `tests/test_outcome_engine_insights.py`, truncated file body duplicates in `tests/test_mcp_report_outcome.py`, and redundant tests in `tests/test_outcome_engine.py`.
  - *T-02*: Replaced circular self-arithmetic assertions in `tests/test_local_promotion_decay.py` with true behavioral integration tests verifying `evaluate_promotions`.
  - *T-03*: Tightened vacuous `isinstance(result, dict)` assertions to concrete status and schema contract validations in `tests/test_mcp_tools_contract.py`.
  - *T-04*: Removed `execute_tool` monkeypatching in `tests/test_mcp_dispatch.py` to test actual MCP dispatch flows end-to-end.
- **Safety Gate Hardening** (W-02): Removed `STEERING_SAFETY_GATE=disabled` bypass in `enzymes/safety_gate.sh`, anchored command regular expressions, and added explicit protection against `rm -rf .` and `shutil.rmtree`.
- **CRLF Safety in Installer** (W-03): Added `\r*$` anchoring to Kiro trigger transformation regexes in `install/install.sh` to prevent trailing carriage return corruption.
- **MCP Optional Argument Null Guards** (W-05): Guarded optional arguments (`files`, `cells_used`, `context_files`, `proposed_content`, `file_path`) in `soma_mcp/tools.py` against `None` values passed by clients.
- **Makefile Pipeline Subshell Exit Masking** (I-01): Replaced masked pipeline subshells (`ls ... | while read ...; done || echo`) with conditional checks and fixed `echo="  (none)"` syntax error in `Makefile`.
- **Outcome Engine Logging Hygiene** (I-02): Replaced bare `except Exception: pass` blocks in `enzymes/outcome_engine.py` with structured debug logging.
- **Bug Registry Verification** (I-05): Registered BUG-059 through BUG-069 with root-cause categorization, pattern analyses, and passing regression test links.

## [0.91.1] — 2026-10-04 — "Temp Artifact Clean & Release Hygiene"

### Fixed
- **Temporary Artifact Cleanup**: Removed accidental temporary test coverage file (`coverage_baseline.txt`) from git tracking.
- **`.gitignore` Hardening**: Added `coverage_baseline.txt` to `.gitignore` to prevent re-introduction.
- **Release Hygiene**: Synchronized version strings across documentation and manifests.

## [0.91.0] — 2026-10-04 — "Tempest Review Remediations & Governance Hardening"

### Added
- **MCP Tool Annotations**: Added required `readOnlyHint`, `destructiveHint`, `idempotentHint`, `openWorldHint`, and `title` annotations to all 15 MCP tools to comply with m8ven trust score requirements.
- **Documentation**: Added `PRIVACY.md` to clarify the local-only nature of the MCP server versus the opt-in cloud nature of the CLI, establishing dual-scope boundaries.
- **Test Coverage**: Added test coverage for read-only MCP tools.
- **`.gitignore` Updates**: Added `.soma/cells/*` to ignore local experiment cells by default, cleaned up duplicate `.hypothesis/` entries, and ensured local-only secrets (`.soma/keys/manifest.key` and `.soma/human_insights.jsonl`) are strictly ignored.

### Changed
- **Test Suite De-duplication & Decomposition**: Broken down massively bloated test files (`test_v090_hardening.py`, `test_telemetry_bugfixes.py`, and `test_redteam_followups.py`) into proper behavioral modules (e.g. `test_outcome_engine.py`, `test_cli_sync.py`, `test_immune_sweep.py`). Updated `BUG_REGISTRY.json` to properly map regression tests to their new homes.
- **Tool Architecture**: Moved `soma_audit_security` and `soma_audit_performance` into read-only tooling since they strictly compute heuristics without mutating state, and corrected inverted annotations on `soma_fitness`.
- **Docs Drift**: Reconciled the total script count in architecture documentation to 118, accounting for recent utility script additions, and marked v0.90 bugs fixed in Bug Registry.

### Fixed
- **Consumer Workspace Fallback for Escalation Sentinel** (BUG-048): Fixed `enzymes/ttc_verifier.py` failing to resolve `escalation_sentinel.sh` in external consumer projects lacking an `enzymes/` folder.
- **Cell Creation Path Traversal** (BUG-049): Sanitized `cell_type` parameter in `enzymes/cell_create_nl.py` with basename extraction, preventing directory traversal outside `.soma/cells/`.
- **Version Bump Shell Parameter Injection** (BUG-050): Hardened `enzymes/bump_version.sh` regex substitutions against unvalidated shell parameter injection into executable code templates.
- **Workspace Parameter Loss in MCP Proposal Router** (BUG-051): Restored missing `workspace` parameter in `soma_mcp/tools.py::soma_propose_change` so path confinement resolves against `_canonical_workspace`.
- **Silent Exception Swallowing in Core Enzymes** (BUG-052): Replaced bare `except Exception: pass` with structured error logging across `cell_scan.py`, `cell_deps.py`, `cell_coverage.py`, and `immune_grade.py`.
- **Layer 2 Verification Attestation Integrity** (BUG-053): Corrected `soma_verify_changes` in `soma_mcp/tools.py` which falsely attested `layer1_only: false` without executing Layer 2 adversarial verification.
- **Zero-Dependency Boundary Protection** (BUG-054): Removed top-level `import yaml` in `soma_sdk/cells.py`, restoring zero-dependency conformance on bare Python runtimes.
- **Session Close Git Sync Order Inversion** (BUG-055): Reordered `enzymes/session_close.sh` so git commit and push occur after outcome engine and cell fitness updates complete.
- **Cryptographic Cache HMAC Verification Fail-Closed** (BUG-056): Enforced fail-closed raising of `CellCacheError` in `soma_mcp/cell_cache.py` on HMAC signature mismatches.
- **Timing Side Channel & Non-Destructive Token Checking** (BUG-057): Used constant-time comparisons in `soma_core/receipts.py` and prevented deletion of receipts during non-consuming verification checks.
- **Evidence Arbiter Import Guard Category Mapping** (BUG-058): Added missing `import_guard` mapping to `immune_system/verification/arbiter.py::TOOL_TO_CATEGORY`.
- **Tautological Mocks**: Rewrote `tests/test_mcp_dispatch.py` to remove brittle mock-heavy tautological tests. Tests now verify functional boundaries instead of strict 1-to-1 implementation assertions.
- **Maelstrom Remediation**: Resolved tautological test assertions across `tests/test_local_promotion_decay.py` and `tests/test_outcome_engine.py` by converting to real subprocess integration tests and tightening signal thresholds.

## [0.90.0] — 2026-10-03 — "Security & Hardening"

### Added
- **`soma completion {bash,zsh,fish}`**: prints a shell completion script for every subcommand, option and choice value (for example `init --platform`). `soma_cli/completion.py` generates it at runtime from the argparse parser, so it can't drift from the CLI. Soma never edits dotfiles; `QUICKSTART.md` ("Shell completion") gives the line to add, such as `eval "$(soma completion zsh)"`. Tests: `tests/test_completion.py`, which also syntax-checks the output with `bash -n` and `zsh -n` when those shells are installed.
- **`soma doctor --fix-path [--yes]`**: the opt-in alternative to copying the BUG-041 PATH line by hand. It appends that line, marked `# added by soma doctor --fix-path`, to `~/.zshrc` (honours `ZDOTDIR`), `~/.bashrc` (macOS: `~/.bash_profile`) or fish's `config.fish` (honours `XDG_CONFIG_HOME`, uses `fish_add_path`). It is a dry run unless you confirm at the prompt or pass `--yes`, and without a terminal it only prints the file and line. It is idempotent, refuses an rc file that resolves outside your home directory (including through a symlink), writes atomically and keeps the file mode, and never edits a PowerShell `$PROFILE` (it prints the command instead). The installers still never edit dotfiles. Each added line is recorded under `path_lines` in `~/.soma/manifest.json`; `install/uninstall.sh` and `install/uninstall.ps1` list it as `[MOD] <rc> (remove soma PATH line)` and remove exactly that line, restoring the file byte for byte (a file doctor created is deleted again if nothing else is in it). An edited line is left alone with a warning. `install.sh` carries `path_lines` over when it rewrites the manifest. Tests: `tests/test_doctor_fix_path.py`.
- **`soma doctor` MCP launcher check**: MCP configs start the server with `python3 -m soma_mcp`. Doctor now resolves `python3` from `PATH` the way the MCP host does and reports whether it works, is missing, is the Windows Store App Installer stub (exit 49, or a Store message and no output), or runs but cannot import `soma_mcp`, with the fix for each. The check is advisory and doesn't change doctor's exit code. Tests: `tests/test_doctor_mcp_launcher.py`.
- **Open bugs BUG-033 and BUG-034** in the Bug Registry: `soma status` miscounts installed core rules (#55), and `mutation_tester` fails open when tests cannot run (#54). Both were reproduced on v0.89.0.
- **Open bugs BUG-036, BUG-037 and BUG-038**: `uninstall.sh` under Git Bash rejects every path (#62), the Git Bash `python3` Store stub (#64, split out of BUG-010), and enzyme scripts crashing on a cp1252 stdout (#65).
- **`SECURITY.md`**: supported versions (current minor line only), private reporting through GitHub private vulnerability reporting, response goals, scope and out-of-scope, and a summary of the security model (MCP receipts and workspace confinement, evidence integrity, installer confinement, release digests). Linked from the README documentation table. Test: `tests/test_security_policy.py`.
- **Open bug BUG-040**: recording an outcome leaves `.soma/evidence/.signals.lock` as an untracked file, because no ignore rule covers it (#70).
- **Windows pytest job in CI** (B3): `validate.yml` gains `test-windows`, which runs the full suite on `windows-latest` (Python 3.9 and 3.12) under Git Bash against the validated wheel. `HOME` and `USERPROFILE` point under `runner.temp` (BUG-010), and `PYTHONUTF8=0` keeps the cp1252 defaults. Failures fail the job. Regression tests: the `test_windows_test_job_*` tests in `tests/test_ci_workflows.py`.

### Changed
- **BUG-013 root cause** recorded in the Bug Registry and `docs/KNOWN_ISSUES_WINDOWS.md`: generated verification tests embed unescaped Windows paths and fail with a `unicodeescape` `SyntaxError`.
- **BUG-015** now links to #57, and **BUG-014** to its own issue #59 (split from #48, which the v0.89.0 BOM fix closed). **BUG-032** is listed in `docs/KNOWN_ISSUES_WINDOWS.md`.

### Fixed
- **`soma status` miscounted core rules for installer-based Claude setups** (BUG-033, #55): the installers merge rules into `~/.claude/CLAUDE.md`, but status only counted loose `*.md` files and, finding none, reported the package's own `genome/` count (a 1-rule `CLAUDE.md` showed "19 active"). Status now counts the Soma sections in `CLAUDE.md`, in both the installer format and the `soma init` marker format, plus loose files, without counting a rule twice, and never falls back to `genome/` when `CLAUDE.md` has Soma content. Regression tests: `tests/test_status_claude_md.py`, including one that runs `install/install.sh claude` under an isolated `HOME`.
- **`soma completion zsh` colons and BOM-prefixed rule files**: `:` in option help (e.g. `--rules` "(default: standard)") is now escaped as `\:` so zsh `_arguments` descriptions aren't cut short; `soma status` and `soma_sdk.cells.parse_cell_file` read rule/cell files as `utf-8-sig`, so BOM-prefixed files from PowerShell 5.1 `Set-Content -Encoding UTF8` keep their frontmatter `id` and aren't double-counted against `CLAUDE.md`. Tests: `tests/test_completion.py`, `tests/test_status_claude_md.py`, `tests/test_cells_bom.py`.
- **Windows: cell inventory rejected any cell edited after creation** (BUG-035, #61): `soma_core/cell_inventory.py` compared `os.stat` and `os.fstat` signatures that included `st_ctime_ns`, which Windows reports as creation time from one and change time from the other. `soma_scan` and `soma_list_cells` failed, and `soma_request_receipt` returned `Internal error`, so no write or execute MCP tool could run on Windows. `st_ctime_ns` is now left out of the signature on Windows, and cells are opened with `O_BINARY` so the snapshot holds the exact on-disk bytes. Regression tests: `test_receipt_flow_works_after_cell_edited_since_creation`, `test_cell_edited_after_creation_is_inventoried`. The `O_BINARY` change also fixes `test_inventory_is_stable_and_captures_exact_bytes` on Windows. The stale-receipt tests now match the exact verifier message, because their `"receipt"` substring check also accepted unrelated errors such as the missing-receipt error.
- **Windows: installer tests wrote to the real user profile** (BUG-010, #47): under Git Bash `resolve_home()` prefers `USERPROFILE`, and six `tests/test_install_lifecycle.py` calls overrode only `HOME`. The shared `run()` helper in `tests/conftest.py` now sets `USERPROFILE` to `HOME` when a test overrides `HOME` alone. Regression test: `tests/test_home_isolation.py`.
- **Windows: `soma status` crashed on a cp1252 stdout** (BUG-012, #49): printing an emoji raised `UnicodeEncodeError` and the command exited 1. `soma` and `enzymes/verify_bug_registry.py` now reconfigure stdout with `errors="replace"`; standalone enzyme scripts are still affected (open BUG-038). `tests/test_rule_metadata.py` reads rule files as UTF-8. Regression tests: `tests/test_cli.py::TestNonUtf8Console`, `tests/test_bug_registry.py::test_error_report_survives_cp1252_stdout`.
- **Windows-only test failures** (BUG-013, #50): generated tests now escape `tmp_path` (`{str(tmp_path)!r}`); path assertions compare `Path.parts` or normalized paths; byte-sensitive files are written as UTF-8 with LF; `tests/conftest.py` gains `require_bash()` (replacing hard-coded `/bin/bash`) and `symlink_or_skip()`; the execute-bit test skips on Windows. On Windows the suite goes from 49 to 12 failures (BUG-036, BUG-038).
- **`mutation_tester` failed open when tests couldn't run** (BUG-034, #54): `check()` counted any test failure as a killed mutant, so a test file with a syntax error, import error or wrong assertion reported `verdict=True`. It now runs the tests against the unmutated source first and returns `verdict=False` (`lines=[-1]`) when that baseline fails. Regression tests: `tests/test_verification/test_mutation_tester.py::TestMutationTesterFailsClosed`.
- **`mutation_tester` skipped most mutation kinds** (BUG-039, #66): comparison, `and`/`or`, statement-deletion and return-value mutations were counted but never applied, so a test that never checked a comparison reported `verdict=True`. Every collected mutation is now applied; docstring deletion and `return None` are no longer generated, since they are equivalent mutants no test can kill. Regression tests: `tests/test_verification/test_mutation_tester.py::TestMutationTesterAppliesEveryCollectedMutation`.
- **Recording an outcome left `.soma/evidence/.signals.lock` untracked** (BUG-040, #70): `evidence_lock()` keeps its lock file, and no ignore rule covered it, so `git add -A` would commit it. `.soma/evidence/.gitignore` now lists it. Regression tests: `tests/test_telemetry.py::TestEvidenceLockIgnoredByGit`, which also checks that the committed evidence files are still not ignored.
- **Windows: `uninstall.sh` under Git Bash refused every path** (BUG-036, #62): MSYS paths (`/c/...`, `/tmp/...`) reached the confinement check in native Windows Python unconverted, so `os.path.isabs()` rejected them and nothing was removed. The check now maps them with `cygpath`, resolved from `PATH` by the shell, since a bare name in Windows Python also searches the current directory. Three defects behind it are fixed too: `read_manifest_field` wrote CRLF in the console code page, so every entry but the last, and non-ASCII names, silently dropped out of the plan; an entry it couldn't encode (a lone surrogate) ended the list early, and uninstall then exited 0 and deleted the manifest; and a refusal could crash while printing its own path. Hardening: on Windows the check also refuses path segments that end in a space or a dot, and `:` stream syntax, which Win32 would resolve to a different name than the one checked. Regression tests: the Git Bash path-form, Win32-normalisation and manifest-reader tests in `tests/test_uninstall_confinement.py`.
- **Windows: enzyme scripts crashed on a cp1252 stdout** (BUG-038, #65): standalone scripts under `enzymes/` and `immune_system/verification/` printed emoji or other non-ASCII and exited 1 with `UnicodeEncodeError` when output was redirected or captured, including hook runs. All 29 entry points with non-ASCII output now reconfigure stdout with `errors="replace"` at the start of their `__main__` block, the same guard as BUG-012. `tests/test_enzyme_console_encoding.py` covers it, and the 3 Windows failures in `tests/test_crossover_structured.py` are fixed.
- **`soma` was "command not found" under zsh after `pip install --user`, with no guidance** (BUG-041): zsh doesn't read `~/.profile`, where `~/.local/bin` is added to `PATH`. The new `soma_cli/pathcheck.py` finds where pip put the script, checks exact `PATH` entries, and prints the line to add for zsh, bash, fish or PowerShell and the file it belongs in; it never edits dotfiles. `soma doctor`, `install/install.sh` and `install/install.ps1` print it. The Makefile now installs with the resolved interpreter's pip (`"$(SOMA_PYTHON_BIN)" -m pip`, BUG-037) and shows pip's errors when every attempt fails, instead of discarding them. Added `python3 -m soma_cli` and `soma --version`, and a troubleshooting section in `QUICKSTART.md`. Regression tests: `tests/test_pathcheck.py`, `tests/test_doctor.py::test_cli_check_prints_zsh_remedy_when_unresolvable`.
- **Git Bash: the Windows Store `python3` stub broke hooks and shell enzymes** (BUG-037, #64): `command -v python3` succeeds for the App Installer stub, which exits 49 when run. `enzymes/soma_python.sh` resolves the first of `python3`, `python` and `py -3` that actually runs Python 3 (`SOMA_PYTHON` overrides it), and all calls go through `soma_py`.
- **`immune_sweep.sh` aborted unless `SOMA_DATA_DIR` was exported** (BUG-042): it read `$RESOLVED_HOME`, which nothing set, under `set -u`. It now uses `resolve_home`, and creates its governance directory on a fresh home. Regression test: `tests/test_v090_hardening.py::test_immune_sweep_runs_without_soma_data_dir`.
- **`uninstall.sh` without Python 3 used a lexical confinement check** (BUG-043): see Security. Regression test: `tests/test_v090_hardening.py::test_manifestless_uninstall_without_python_removes_nothing`.
- **Inline Python in enzymes no longer imports CWD modules** (BUG-044): `soma_py` strips CWD entry from `sys.path[0]` for inline code while preserving user site-packages. Regression test: `tests/test_redteam_followups.py`.
- **`uninstall.sh` Claude `settings.json` cleanup is confined and previewed** (BUG-045): settings files holding `hooks.soma` are previewed as `[MOD]`, checked against `ALLOWED_ROOTS`, and rewritten atomically preserving mode. Regression test: `tests/test_redteam_followups.py`.
- **`verify_bug_registry.py` timed out on clean Windows installation** (BUG-046, #80): dynamic timeout budget based on test count and pytest summary ID matching.
- **The `soma init` pre-commit hook aborted commits with only `soma: not found`** (BUG-047): it ran a bare `soma checkpoint`, which doesn't resolve when `soma` isn't on the hook's `PATH` (zsh and other non-login shells after `pip install --user`, GUI git clients, IDEs). The hook now falls back to the interpreter that ran `soma init`, and with neither it fails with a message that names `soma doctor` and the `PATH` fix. Re-running `soma init` refreshes an existing hook block in place and keeps your own lines; `soma doctor` reports an old block. Regression tests: `tests/test_precommit_hook_fallback.py`.

### Security
- **PyPI Trusted Publishing (OIDC)**: `publish.yml` no longer uses a long-lived `PYPI_API_TOKEN` or `twine`. The publish job runs in the `pypi` environment with `id-token: write` and uploads through `pypa/gh-action-pypi-publish`. It uploads only the files `verify_dist.py verify` printed, copied into `publish-dist/`, because `dist/` also holds `SHA256SUMS`. The build-once, digest-verified, no-rebuild chain is unchanged.
- **Least-privilege tokens**: both workflows set top-level `permissions: contents: read`; only `build-wheel` (attestations) and `publish` (OIDC) are granted more, at job level.
- **SHA-pinned actions**: every third-party action is pinned to a full commit SHA with a `# vX.Y.Z` comment; `.github/dependabot.yml` updates `github-actions` and `pip` weekly.
- **Dependency audit**: a new `dependency-audit` job in `validate.yml` runs `pip-audit --strict .` on the runtime dependencies in `pyproject.toml` and fails on any finding. `pip-audit` is installed in CI only.
- **Build provenance**: `build-wheel` signs SLSA provenance for the wheel and sdist with `actions/attest-build-provenance` on push and release builds. It is skipped on pull requests, because fork PRs get no OIDC token. The publish action also uploads PEP 740 attestations to PyPI.
- Regression tests: `tests/test_ci_workflows.py`.

## [0.89.0] — 2026-10-02 — "MCP Execution Security"

### Added
- **Opaque, stateful, session-bound receipts for MCP execution** (Fixes BUG-009): The server now requires single-use cryptographic receipts for all write and execute tools, fetched via `soma_request_receipt`. This ensures only trusted MCP connections can mutate workspace state, mitigating cross-workspace CSRF attacks.
- **Strict workspace injection boundaries** in the MCP dispatcher. The server forcibly injects the operator-configured `_canonical_workspace` into write and execute tools, ignoring client-provided `workspace` arguments, preventing path traversal via rogue arguments.
- **Open-bug tracking in the Bug Registry**: entries take `status: open|fixed` (default `fixed` for existing entries). `enzymes/verify_bug_registry.py` requires only the core fields for open bugs, rejects open bugs that set fix fields, and skips regression-test collection for them.
- **`platform_compat` root-cause category** and open bugs BUG-008–BUG-014 (Windows and MCP issues; GitHub issues #45–#50) and BUG-015 (`soma checkpoint`/`soma sync` wipe cell fitness on a fresh clone).
- **`docs/KNOWN_ISSUES_WINDOWS.md`**: open Windows issues, workarounds, and impact.

### Changed
- **README**: known-issue notes for the MCP server and Windows; the Windows rows of the platform table are now ⚠️ where open bugs apply.
- **`soma_request_receipt` classification**: Reclassified from `_WRITE_TOOLS` to `_READ_TOOLS` so it remains discoverable in `tools/list` when execution mode is disabled.

### Fixed
- **MCP write/execute tools unusable from MCP hosts** (BUG-009, #46): Handshake designed for direct clients replaced with session-bound receipt architecture. Regression test: `test_mcp_dispatch.py`.
- **`install.ps1` failed to parse under Windows PowerShell 5.1** (BUG-011, #48): the installers were UTF-8 without a BOM, so PS 5.1 read them as cp1252. They are now saved with a UTF-8 BOM. Regression test: `test_powershell_scripts_with_non_ascii_have_utf8_bom`. CI: new Windows PowerShell 5.1 dry-run step in `validate.yml`.
- **MCP server crashed on Windows at startup** (BUG-008, #45): `soma_mcp/tools.py` and `soma_sdk/telemetry.py` imported `fcntl` unconditionally. Both now fall back to unlocked appends when `fcntl` is unavailable, matching `enzymes/fitness_updater.py`. Regression tests: `tests/test_fcntl_optional.py`.
- `tests/test_diagnose_hot_zones.py`: the "Insufficient data" snapshot test assumed fewer than 10 registry entries; it now asserts the warning tracks the registry size.

### Fixed (pre-release review)
- **Canonical workspace was never injected** (BUG-016): the assignment sat after an unconditional `return`, so write/execute tools honoured a client-supplied `workspace`. The dispatcher now strips server-owned keys (`workspace`, `receipt`, `_sessionToken`) from every call, read tools included, and injects the operator-configured workspace after receipt verification. Privileged calls fail closed when no canonical workspace is configured. Tests: `tests/test_mcp_receipt_binding.py`.
- **Receipts bound to empty digests** (BUG-017): receipts now bind sha256 digests of the target files named in the arguments (`file_path`, `files`, `context_files`) and of every cell under `.soma/cells`, recomputed at redemption. Paths outside the workspace are rejected at issuance. Note: any cell edit (including an outcome-engine fitness update) inside the 300 s receipt window makes outstanding receipts stale; request a new one.
- **Telemetry `event_id` was not enforced** (BUG-018): `append_signal` now holds a cross-process evidence lock (`.soma/evidence/.signals.lock`; `fcntl`, `msvcrt` or thread-lock fallback), treats an identical replay as a no-op, raises `EventConflictError` for a changed payload, returns the persisted record, and stamps every record with the epoch `generation`.
- **Epoch migration was a placeholder** (BUG-019): `run_epoch_migration` now holds the evidence lock for the whole cutover, snapshots every ledger into `snapshot/gen-<n>/` with `SHA256SUMS`, converts legacy `fitness.jsonl`/`outcomes.jsonl` rows with deterministic event ids, skips MCP twins and already-migrated rows, aborts unchanged on a reconciliation mismatch, writes atomically, and fences writers via `append_signal(expected_generation=...)` / `StaleGenerationError`.
- **Human-insight cursor advanced before persistence** (BUG-020): reading no longer writes the cursor. `main()` appends evidence first; insight events carry a stable id, so a retry after a partial failure dedupes instead of duplicating. The cursor is then committed atomically, and cell frontmatter is updated only after that, so a retry never applies a boost twice. Appends are fenced on the generation the run observed. Partial trailing lines are re-read.
- **MCP outcomes could be double counted by migration**: `soma_report_outcome` now writes one `outcome_id` into both the legacy `outcomes.jsonl` row and its idempotent `signals.jsonl` twin, and migration dedupes on that id. Rows without an id fall back to timestamp matching.
- **Uninstall path confinement was lexical** (BUG-021): `uninstall.sh` and `uninstall.ps1` validate every manifest field and the full removal plan against canonical allowed roots before any mutation, fail closed, and re-check each path at the sink. Symlinked or junctioned ancestors are accepted only when their target stays inside the allowed root (stow-style `~/.kiro -> ~/dotfiles/.kiro` works; a link out of `$HOME` is refused). OneDrive placeholders, which carry the ReparsePoint attribute without being links, are not treated as redirections.
- **`quality_gate` crashed on Python 3.14** (BUG-022): dropped the removed `ast.Str` alias.
- **Release could ship untested bytes** (BUG-023): one build records `SHA256SUMS`; the sdist and the matrix-installed wheel are smoke-tested outside the checkout (`python -I`, `PYTHONPATH` unset, module origins asserted under site-packages) by `.github/scripts/wheel_smoke.py`; `publish.yml` verifies the digests and uploads only the verified files.
- **BUG-009 registry entry** used a non-schema `resolved_in` field and lacked `changelog_ref`, so the registry failed its own verifier and broke CI.

---

## [0.88.2] — 2026-10-01 — "Documentation Updates"

### Documentation
- Removed deprecated API Key fields from `README.md` configuration table.

---

## [0.88.1] — 2026-10-01 — "Credential Hardening"

### Security
- **Deprecated Plaintext API Keys**: Removed `GEMINI_API_KEY`, `ANTHROPIC_API_KEY`, and `OPENAI_API_KEY` from configuration files (`soma.conf`, `.soma/credentials.conf`).
- **Enforced Secure Storage**: `inference_provider.py` now exclusively resolves credentials via environment variables or the system `keyring`, mitigating the risk of accidentally committing secrets.

---

## [0.88.0] — 2026-10-01 — "Key Management"

### Added
- **HMAC-SHA256 key management** (`soma_mcp/integrity.py`): 256-bit key generation, storage in `.soma/keys/manifest.key` with `0o600` permissions, key rotation with `.bak` backup.
- **Manifest signing**: `save_manifest()` auto-signs when key exists; `verify_signature()` uses constant-time `hmac.compare_digest`.
- **`soma_generate_manifest` MCP tool**: Generates and signs cell integrity manifests, with optional key creation. Added to `_EXECUTE_TOOLS` tier (requires session auth).
- **Signature verification in cell cache**: `cell_cache.py` logs HMAC verification status during refresh.
- **10 new security test cases**: Key CRUD, signing determinism, tamper detection, auto-sign on save, graceful unsigned fallback.

### Technical
- Stdlib only (`hmac` + `secrets`), no new dependencies.
- Signs only the `cells` dict (not metadata) for canonical determinism.

---

## [0.87.0] — 2026-10-01 — "Content Cleanup"

### Removed
- **Deleted `soma_run.py`** (221 lines): Legacy master orchestrator, fully replaced by MCP server (`soma_mcp/`) and CLI (`soma_cli/`). Zero importers found in codebase.

### Changed
- **`docs/architecture/scripts.md`**: Marked "Master Pipeline Orchestrator" section as removed, pointing to `soma_mcp/`.
- **`soma_sdk_js/README.md`**: Replaced `soma_run.py` reference with MCP server.

---

## [0.86.0] — 2026-10-01 — "Security Hardening"

### Added
- **Path confinement** (`soma_mcp/security.py` — NEW): `confine_workspace()` rejects workspaces without `.soma/cells/`; `confine_path()` blocks path traversal and symlink escape; `validate_cell_names()` rejects fabricated cell names.
- **Enzyme import allowlist** (`soma_mcp/tools.py`): Frozen allowlist + `_safe_import_enzyme()` prevents rogue `.py` files in `enzymes/` from being loaded.
- **SHA-256 cell integrity manifests** (`soma_mcp/integrity.py` — NEW): Manifest generation and verification during cell cache refresh with graceful degradation.
- **Session token auth** (`soma_mcp/server.py`): Token generated on `initialize`, required for write/execute tools, read tools remain open.
- **Per-tool rate limiting** (`soma_mcp/server.py`): Sliding window rate limits on execution-heavy tools.
- **Permission tiers**: All tools classified into `_READ_TOOLS`, `_WRITE_TOOLS`, `_EXECUTE_TOOLS` frozensets.
- **31 new security test cases** (`tests/test_security.py` — NEW): Path confinement, cell validation, integrity manifests, enzyme allowlist, auth tiers, rate limiting.

### Fixed
- **`tests/test_mcp_verify.py`**: Updated 8 test fixtures to create valid `.soma/cells/` workspaces (required by new confinement checks).

---

## [0.85.1] — 2026-10-01

### Fixed
- **Python 3.9 compatibility** (`enzymes/diagnose_hot_zones.py`): Added `from __future__ import annotations` — `dict | None` union syntax (PEP 604) requires 3.10+ at runtime. (BUG-006)

---

## [0.85.0] — 2026-10-01 — "Antifragile"

### Added
- **Hot Zone Engine** (`soma_sdk/hot_zones.py`): Pure-function module computing file heat and pattern heat from the bug registry. Cells covering historically-buggy files or recurring root cause categories receive a fitness score boost.
- **Configurable thresholds** in `BUG_REGISTRY.json`: `file_heat_threshold` (default 2), `pattern_heat_threshold` (default 3), `max_file_boost` (0.5), `max_pattern_boost` (0.3), `min_outcomes_for_boost` (3).
- 17 new tests in `tests/test_hot_zones.py` — threshold activation, cap enforcement, tag-to-category mapping, workspace integration.

### Changed
- `soma_mcp/jit_engine.py`: `express()` now applies hot zone boost after initial fitness scoring. Multiplicative formula ensures zero-scored cells stay at zero.

### Design
The antifragile loop: Bugs → Registry → Hot zones → Cell boost → Better governance → Fewer bugs → ♻️

---

## [0.84.0] — 2026-10-01 — "Bug Ledger"

### Added
- **Bug Registry** (`docs/project/BUG_REGISTRY.json`): Machine-parseable registry with root cause taxonomy (`path_error`, `schema_drift`, `silent_failure`, `mapping_error`, `dead_code`), severity levels, regression test links, and pattern descriptions. Backfilled with Bugs 1–5.
- **Verification enzyme** (`enzymes/verify_bug_registry.py`): Validates schema, ID uniqueness, root cause categories, and regression test existence.
- **Governance cell**: `trap-unregistered-bug-fix` — gate enforcement requiring BUG_REGISTRY.json entries alongside bug fixes.
- 9 new tests in `tests/test_bug_registry.py` — schema validation, uniqueness, and integration with the real registry.

---

## [0.83.0] — 2026-10-01 — "Fast Path"

### Added
- **JIT Cell Cache** (`soma_mcp/cell_cache.py`): mtime-based in-memory cache eliminates redundant disk I/O when the MCP server calls `express()`. Cells are re-parsed only when files in `.soma/cells/` change.
- 9 new tests in `tests/test_cell_cache.py` — cache hits, invalidation on add/modify/delete, expired cell skipping, schema compatibility.

### Changed
- `soma_mcp/jit_engine.py`: `express()` now uses module-level `CellCache` singleton instead of `load_all_cells()` per invocation.

---

## [0.82.0] — 2026-10-01 — "Consolidation"

### Fixed
- **Bug 4**: `sync.py` no longer clobbers cell scores to 0.0 when a cell has triggers but no tp/fp outcomes. Score is preserved until actual outcome data arrives.
- **Bug 5**: `outcome_engine.py::append_fitness_log()` no longer writes to dead-end `.soma/cells/fitness.jsonl`. Now routes through unified `soma_sdk.telemetry.append_signal()` to `.soma/evidence/signals.jsonl`.
- **Bug 5b**: `cell_selection.sh` lifecycle actions redirected from `.soma/cells/fitness.jsonl` to `.soma/evidence/lifecycle.jsonl`.

### Changed
- **Writer migration**: `fitness_updater.py`, `soma_mcp/tools.py` (soma_report_outcome), and `outcome_engine.py` now write through `soma_sdk.telemetry.append_signal()`.
- **CLI wrapper**: `python3 -m soma_sdk.telemetry` enables bash scripts to write signals through the unified path.
- **ROADMAP.md**: Phase 4 → ✅ Shipped, Phase 4.5 → ✅ Shipped, Phase 4.6 added.
- **README.md**: CI outcome reporter moved from "Planned" to shipped.

### Added
- **Governance cell**: `trap-roadmap-status-drift` — gate enforcement requiring ROADMAP.md updates alongside releases.

---

## [0.81.0] — 2026-10-01 — "Smoke Detector"

### Added
- **CI Outcome Reporter** (Phase 4.5b): `enzymes/ci_outcome_reporter.py` — report-only advisory that matches cells to changed files via `target_paths` globs, computes per-file credit weights (conserved 1/N), and proposes signals (pass→`trigger`, fail→`fp`). Integrated into CI as a GitHub Actions step summary.
- **Unified telemetry writer** (Phase 4.5a): `soma_sdk/telemetry.py` — `append_signal()` with file-locked concurrent writes, schema validation, and canonical evidence log at `.soma/evidence/signals.jsonl`.
- **Governance cell**: `trap-bugfix-without-regression-test` — mechanical enforcement requiring regression tests for every bug fix.
- **TDD test suite**: 4 new test files — `test_telemetry.py` (8), `test_ci_outcome_reporter.py` (10), `test_telemetry_bugfixes.py` (8). Total: 1,518 passed.

### Fixed
- **Bug 1**: `outcome_engine.py` read from wrong path (`.soma/outcomes.jsonl` → `.soma/evidence/outcomes.jsonl`).
- **Bug 2**: `outcome_engine.py` expected wrong schema key (`cells_used` list → also accepts `cell_id` string).
- **Bug 3**: `sync.py` silently ignored agent outcomes (`success`/`failure` now mapped to tp/fp).

---

## [0.80.0] — 2026-10-01 — "Consensus"

### Added
- **Quorum sensing** (Phase 4.1): `evaluate_quorum()` detects when ≥N cells trigger simultaneously on the same changed files, escalates to the highest `minimum_mode`, and logs events to JSONL. Extracted from CLI `main()` for testability.
- **Gate enforcement DSL** (Phase 4.2): `soma_sdk/invariants.py` with `check_import_banned()` (AST-based), `check_file_must_exist()`, `check_invariants()` aggregate, and `evaluate_enforcement()` three-tier ladder.
- **Enforcement ladder**: `advisory` (warn, exit 0) → `mechanical` (block, exit 1) → `gate` (block, exit 1). Unknown tiers default to advisory.
- **TDD test suite**: 3 new test files — `test_quorum.py` (11), `test_gate_invariant_dsl.py` (9), `test_enforcement_ladder.py` (7). Total: 1,492 passed, 7 skipped.

### Fixed
- **Documentation cleanup**: 9 doc files updated — stale version refs, broken post-restructure links, removed claim terminology, outdated phase statuses.
- **Stale release branches**: Deleted 10 local release branches (`release/v0.60` through `release/v0.75`).

### Claims Unlocked
- `claim_quorum_sensing` — Multi-rule consensus for high-confidence decisions
- `claim_gate_enforcement` — Invariant DSL-based gate enforcement in CI

---

## [0.75.0] — 2026-10-01 — "Credit Where Due"

### Added
- **Credit assignment** (Phase 3.1): `prob_round()` probabilistic rounding, `compute_credit_weights()` per-file scope narrowing with credit conservation. Signal provenance tracked in JSONL via `credit_weight` and `signal_method` fields.
- **Mutation operators** (Phase 3.2): Comparison swap (`<`↔`>`, `<=`↔`>=`, `==`↔`!=`), boolean swap (`and`↔`or`), statement deletion (stmt→pass), return value mutation (`return X`→`return None`).
- **TDD test suite**: 8 new behavioral test files — `test_credit_assignment.py` (14), `test_outcome_engine.py` (18), `test_jit_engine_behavioral.py` (22), `test_error_handling.py` (13), `test_mcp_tools_contract.py` (12), `test_tournament_integration.py` (8), `test_crossover_structured.py` (12), `test_mutation_tester_upgraded.py` (10).

### Fixed
- **Crossover target_paths** (Phase 3.6): `cell_crossover.py` now merges `target_paths` as deduplicated union of both parents. Previously omitted entirely, making child cells unable to match any files.
- **Crossover tags**: Tags now merged as union instead of reset to empty list.

### Changed
- `compute_fitness_signals()` accepts optional `changed_files` kwarg for credit weighting.
- `update_cell_fitness()` uses `prob_round(credit_weight)` for tp/fp counter updates.
- `append_fitness_log()` includes `credit_weight` and `signal_method` provenance.
- Claim registry: `claim_credit_assignment`, `claim_structured_crossover`, `claim_tournament_selection` unlocked.

### Metrics
- Test suite: **1465 passed**, 7 skipped, 0 failed (up from 1359 in v0.74)

---

## [0.71.0] — 2026-10-01 — "Branch Sync"

### Fixed
- **Gitflow step 7**: Release checklist now merges **main** back to develop (not the release branch). Previous workflow skipped main's PR merge commit, causing main and develop to diverge over 5 releases.

---

## [0.74.0] — 2026-10-01 — "Foundation"

### Added
- `soma_sdk/errors.py`: Complete error hierarchy (SomaError → CellParseError, CellNotFoundError, CellPathTraversalError, FitnessError)
- `soma_sdk/scoring.py`: Wilson-bounded fitness scoring (bayesian_posterior, laplace_score, _wilson_interval)
- `soma_sdk/cells.py`: Canonical cell parser (parse_cell_file, write_cell_frontmatter, load_cell, _sanitize_cell_id)
- `tests/test_bayesian_correctness.py`: 17 mathematical ground truth tests
- `tests/test_sdk_behavioral.py`: 21 SDK public API tests
- `tests/test_escaped_defects.py`: 12 antifragile behavior tests
- `tests/test_cell_deps_behavioral.py`: 5 co-trigger detection tests
- `tests/test_integration_lifecycle.py`: 8 end-to-end lifecycle tests
- `tests/test_threshold_recalibration.py`: 12 boundary value tests

### Changed
- Migrated 27 enzyme/CLI files from inline YAML parsing to canonical `parse_cell_file()`
- `CellFitness.bayesian()` upgraded from Wald approximation to Wilson score interval
- `Cell.is_extinct` / `Cell.is_promotable` now use `laplace_score()` import
- `enzymes/bayesian_score.py` converted to thin wrapper re-exporting from `soma_sdk.scoring`
- `enzymes/cell_deps.py` added `--workspace` argument for testability

### Metrics
- Suite: 1359 passed, 5 skipped, 0 failed
- Claims: 8 unlocked, 5 locked, 7 removed (20/20 verified)
- Net code change: +1606/-353 lines across 41 files

---

## [0.73.0] — 2026-10-01 — "Stop the Bleeding"

### Added
- `docs/CLAIM_REGISTRY.json`: Machine-readable claim tracking (locked/unlocked/removed)
- `enzymes/verify_readme_claims.py`: CI gate verifying README claims against tests
- `tests/test_static_invariants.py::test_version_is_single_sourced`: Version sync invariant
- `docs/ROADMAP.md`: Future features moved from README
- `docs/RELEASE_WORKFLOW.md`: Codified gitflow release procedure

### Changed
- README stripped to earned claims only — removed 7 unverified claims
- Fixed `exit 1` bug in pre-commit hook generation (cell_enforce.py)
- Version synced across pyproject.toml and VERSION file

### Removed
- Unearned README claims: evolutionary computation, gate enforcement, < 1.0% waste rate, deterministic verification, inflated test count

---

## [0.70.0] — 2026-10-01 — "Genesis"

### Added
- **`soma genesis` command**: Scans codebase architecture with 8 language-agnostic detectors and generates governance cell candidates.
  - Detectors: module boundaries, config stores, shared state, API surfaces, data pipelines, state machines, test boundaries, dependency walls
  - All generated cells start as vacuoles with `proposed_type` frontmatter
  - Generates `docs/organelles.md` architecture map
  - Flags: `--dry-run`, `--json`, `--force`, `--yes`

### Security
- Path traversal fix: import regex rejects relative imports; `is_relative_to()` containment check
- Memory exhaustion fix: streaming `read(limit)` replaces `read_text()[:limit]`
- Symlink guard: `is_symlink()` check before all file writes

### Fixed
- Dry-run no longer creates `.soma/cells/vacuoles/` directory
- `docs/organelles.md` respects `--dry-run`, `--force`, and symlink guards
- `input()` wrapped in `try/except` for headless environments
- `rglob` replaced with filtered `_iter_source_files` (no `.git`/`.venv` traversal)
- Frontmatter/markdown sanitization prevents injection via crafted identifiers
- 80% I/O reduction via single-pass source cache across 5 detectors

---

## [0.62.2] — 2026-10-01 — "Documentation Sweep"

### Fixed
- **README.md**: Version badge 0.60.0 → 0.62.2, test badge 1162 → 1228, script count 58 → 57. Added `soma sync` to CLI table. Added PyPI install to Quick Start. Added Python 3.9+ label.
- **QUICKSTART.md**: Added all CLI commands (sync, checkpoint, oracle, promote, demote, doctor, verify). Fixed repo URL. Updated PyPI status from "coming soon" to available. Added PEP 668 hint. Added Kiro platform.
- **SCRIPTS.md**: Full recount and rewrite — 39 → 57 scripts cataloged.
- **CONTRIBUTING.md**: Added Python 3.9 compat requirement, CI matrix info, test command, `from __future__ import annotations` requirement.
- **pyproject.toml**: Added Python 3.9/3.10/3.11/3.12 classifiers.

---

## [0.62.1] — 2026-10-01 — Patch

### Fixed
- **`make install`**: Handle PEP 668 externally-managed Python environments (`--user --break-system-packages` fallback chain).
- **`make install`**: Print PATH hint when `~/.local/bin` is not on PATH.
- **`install.sh`**: Fix skill install crash when a previously-installed file/symlink is being replaced by a directory (`cp: cannot overwrite non-directory`).

---

## [0.62.0] — 2026-10-01 — "Evidence Pipeline"

### Added
- **`soma sync` command**: Reconciles `.soma/evidence/fitness.jsonl` and `outcomes.jsonl` with cell frontmatter. Supports `--dry-run` and `--json` flags.

### Fixed
- **Fitness pipeline disconnect**: `fitness_updater.py` wrote trigger events to JSONL but never updated cell frontmatter, causing `immune_grade.py` and `cell_fitness.py` to report zero fitness despite evidence existing.
- **`soma checkpoint`** now auto-syncs evidence → frontmatter before running quality checks, so the report card is always fresh.
- **`fitness_updater.py`** now auto-syncs frontmatter after writing JSONL, closing the pipeline gap.

### Changed
- Bootstrapped fitness evidence from two Supercell session transcripts (170+ trigger events, 42 cells scored).

---

## [0.61.0] — 2026-10-01 — "Python 3.9 Compatibility"

### Fixed
- **Python 3.9 runtime crash**: 6 files in `immune_system/verification/` used PEP 604 union syntax (`X | None`) in function signatures without `from __future__ import annotations`, causing `TypeError: unsupported operand type(s) for |` on Python 3.9. Added the future import to all affected files.

### Changed
- **CI matrix**: Added Python 3.9 to test matrix (Ubuntu, macOS, Windows).
- **CI publish**: Auto-publish to PyPI on GitHub release creation via `PYPI_API_TOKEN` secret.

---

## [0.60.0] — 2026-09-30 — "Two-Layer Verification & Cell Lifecycle"

### Added
- **Two-Layer Verification System** (`immune_system/verification/`):
  - **Layer 1 (Deterministic AST Tools)**: Objective, ungameable evidence collection via `persistence_checker`, `call_graph`, `mutation_tester`, `branch_coverage`, and `import_guard`. Orchestrated via `runner.py` producing boolean `ToolEvidence`.
  - **Layer 2 (Adversarial Information-Partitioned Agents)**: Multi-agent verification leveraging information asymmetry between Spec Agent (sees task specification) and Code Agent (sees implementation/tests).
  - **Deterministic Arbiter**: Set-algebra adjudication over a fixed 14-category risk taxonomy, issuing `SHIP`, `BLOCK`, or `REVISE` verdicts with zero LLM in the loop.
  - **Transcript Verifier**: Post-hoc validation of self-reported agent claims against JSONL session logs.
- **Unified CLI Suite** (`soma`): 9 subcommands — `init`, `status`, `report`, `doctor`, `verify`, `checkpoint`, `oracle`, `promote`, `demote`.
  - `soma verify`: Full two-layer verification with `--layer1-only` support.
  - `soma checkpoint`: Fast deterministic quality gate with `--pre-commit` hook integration.
  - `soma oracle`: Cell health classification (healthy, noisy, expired, unobserved).
  - `soma promote` / `soma demote`: Automated lifecycle evaluation with `--dry-run` and `--json`.
  - `soma init`: Enhanced with `--rules {minimal|standard|full}`, MCP config, and pre-commit hook.
- **Cell Lifecycle Engine** (`immune_system/verification/lifecycle.py`):
  - Deterministic state machine: Vacuole → Wall → Genome (and demotions).
  - Grounded in JSONL evidence ledgers, not YAML frontmatter.
  - Promotion: triggers ≥ 20, tp_rate > 0.85, age > 30 days.
  - Demotion: fp_rate > 0.5 or dormancy ≥ 90 days.
- **MCP Tools**: Added `soma_verify_changes` and `soma_checkpoint` for zero-API-key in-agent verification.
- **Supercell Review Intensity**: New highest review tier (above Tempest) — adversarial Prosecutor/Defender pairs per prong, iterative fix-revalidate with no deferrals until clean ship.
- **Quality Gate Checks**: Assertion density, bare `pass` detection, import verification, test sanity.
- **Doc Consistency Tests**: 6 tests verifying README ↔ SKILL.md intensity level consistency.
- **Test Suite**: 1184 tests with shared fixtures (`tests/helpers_cell.py`).
- **Governance Cells**: 44 total — 20 walls, 2 plasmodesmata, 3 membranes, 3 chloroplasts, 16 vacuoles.
  - NEW: `trap-stdout-protocol-corruption` (wall) — hooks emitting to stdout after JSON.
  - NEW: `trap-tautological-test` (wall) — tests that verify nothing.
  - NEW: `contract-sdk-feature-parity` (plasmodesmata) — Python/JS SDK method parity.
- **SDK Parity**: Added `entropy()` and `adversarial()` to Python SDK (matching JS SDK).

### Changed
- Package discovery updated to include `immune_system*`.
- Pre-commit hook auto-installed by `soma init`.
- Architecture diagram widened for Supercell intensity level.
- **SDK `is_extinct`/`is_promotable`**: Now use Bayesian scoring aligned with `cell_promote.py` standards (score > 0.85, triggers ≥ 20) instead of legacy `raw_score`.
- **DRY**: `outcome_engine.py` imports canonical `resolve_workspace()` from `soma_resolve.py`. Intentional duplication in `soma_mcp/` documented (zero-dep wall).
- **Type Annotations**: Added to all public APIs in `governance.py`, `cells.py`, `jit_engine.py`, `bayesian_score.py`.
- **Test Fixtures**: Deduplicated `soma_workspace`, `_write_cell`, `_make_cell` into shared `helpers_cell.py`.
- **Hardcoded Paths**: `safety_gate.sh` and `immune_init.sh` now use `${SOMA_LOGS_DIR}` / `${SOMA_CONF}` env vars with fallbacks.
- **Makefile validate**: Now covers `soma_cli/` and `immune_system/` in addition to `enzymes/`, `soma_mcp/`, `soma_sdk/`.
- **Docs**: Fixed ABSTRACT contribution count (3→4), step count (12,000→11,900), removed duplicate PHYLOGENY section, added Phase 16/18/19/20/21 stubs.

### Fixed
- **Evidence Pipeline**: 4 critical bugs fixed (schema mismatch, dead detectors, missing FPSR extraction).
- 2 new evidence detectors: `test-before-implementation`, `no-hardcoded-paths`.
- **Security (Supercell S1)**: Code injection via `.format()` in `branch_coverage.py` — paths now escaped with `repr()`.
- **Security (Supercell S2)**: Path traversal via `--files` — containment check added to `verify.py`.
- **Correctness (Supercell C1)**: Outcomes path/schema desync between MCP and lifecycle engine.
- **Correctness (Supercell C2)**: JSONL crash on non-dict lines in lifecycle evidence loading.
- **Correctness (Supercell C3)**: Lifecycle threshold bugs (boundary values, min sample size, dormancy).
- **Bug**: 5 pre-existing `test_status.py` failures from real filesystem leak through platform auto-detection.
- **Robustness (Phase 2)**: 9 fixes across verification tools:
  - `branch_coverage.py`: Parse `missing_branches`, add subprocess timeout (120s), UTF-8 encoding.
  - `transcript_verifier.py`: FileNotFoundError guard, tool_calls-based write detection (no more content-string false positives), collection error sentinel `(-1,-1)`, multi-run false positive fix.
  - `immune_init.sh`: JSON protocol corruption — 4 echo statements redirected to stderr.
  - `escalation_sentinel.sh`: Frontmatter `target_paths` parsing replaces fragile hypothesis regex.
- **Layer 2 Fail-Open (Phase 3)**: Empty spec agent predictions now produce `Verdict.BLOCK` instead of silently passing through to `SHIP`.

---

## [0.60.0-rc] — 2026-09-30 — "Wire Verification & Cell Lifecycle RC"

### Added
- **Gitflow**: Standardized branch lifecycle with session pattern rules.
- **Content Coherence Tests**: Automated doc ↔ code consistency validation.
- **MCP Self-Install**: `soma init` auto-configures MCP server in agent config.
- `soma init --rules {minimal|standard|full}`: Tiered rule installation.
- **Wire Verification System (Phase 2)**: End-to-end evidence pipeline validation.
- **Pre-Commit Hook**: Deterministic quality gate via `soma checkpoint --pre-commit`.
- **Cell Lifecycle Engine**: Oracle, promote, and demote commands with deterministic state machine.
- **Supercell Review Process**: Highest review tier — adversarial Prosecutor/Defender pairs per prong.
- **Checkpoint Extraction**: Deterministic quality gate checks (assertion density, bare `pass`, imports).
- **Evidence Pipeline Fix**: 4 critical bugs (schema mismatch, dead detectors, missing FPSR extraction).

### Changed
- 5 review cycles completed during RC hardening.

---

## [0.52.0] — 2026-09-30 — "Gitflow & Hardening"

### Added
- **Gitflow**: Standardized branch lifecycle in `docs/GITFLOW.md`.
- **Gitflow Review Gate**: Rule enforcing branch naming and PR-based landing.

### Fixed
- All 15 findings from v0.52 production audit.
- 4 must-fix findings from audit round 2.
- Hardcoded absolute paths in documentation.

---

## [0.51.0] — 2026-09-30 — "Soma CLI & Distribution"

### Added
- **Soma CLI** (`soma_cli/`): `soma init`, `soma status`, `soma report`.
- Starter pack manifests and templates.
- CLI entrypoints in `pyproject.toml`.

### Fixed
- 10 audit findings across argument validation, path resolution, error reporting.

---

## [0.50.0] — 2026-09-29 — "Incentive-Compatible Governance"

> Tagged release — Version jump from v0.22.0 reflects Phases 23–50: TTC Oracles, JIT context, interoception, and the evidence pipeline.

### Added
- **Evidence Pipeline**: `evidence_collector.py`, `fitness_updater.py`, `cell_expiry.py`, `oracle_checkpoint.py`, `post_session_hook.sh`.
- **Mechanism Design Framework** (`docs/MECHANISM_DESIGN.md`).
- **Fitness Updater**: Automated fitness scoring from evidence ledgers.
- **Cell Expiry**: Time- and session-based cell lifecycle enforcement.
- **Oracle Checkpoint**: Cell health classification with evidence grounding.
- **Trap Cells**: `trap-fix-one-not-all`, `trap-unverified-delegation`, `trap-local-green-ci-red`.
- README trustworthiness rewrite.

### Changed
- Fitness ledger decoupled from frontmatter → append-only JSONL.
- `pyyaml` accepted as mandatory dependency.
- Idle overhead stabilized at ~3,800 tokens/turn (down 8.6%).
- 6 audit rounds completed.

### Fixed
- Tautological assertions and brittle source-code grepping remediated (515+ tests).
- Critical fitness inflation bug.
- CI execution hang from hook test sourcing.

---

## [0.31.0] — 2026-09-29 — "Human Insight Pipeline"

### Added
- **Human Insight Pipeline**: Structured pathway for human-observed defects to influence cell fitness.
- **TDD Protocol** (`genome/.oracles/tdd-protocol.md`): Test-driven development with sequential phase gates.
- **Mechanism Design Framework**: Incentive-compatible governance architecture documentation.
- **Evidence Collector**: Automated correlation of rule compliance with session outcomes.

---

## [0.30.0] — 2026-09-29 — "Two-Layer Verification Foundation"

### Added
- **Two-Layer Verification Framework**: Deterministic AST tools (Layer 1) + adversarial information-partitioned agents (Layer 2).
- **Import Guard** (`import_guard`): Layer 1 tool detecting unguarded third-party imports that crash CI.
- **Keyring Secret Storage**: Secure credential management for inference providers.

---

## [0.25.0] — 2026-09-28 — "TTC & Biological Docs"

### Added
- **TTC/Tempest MCP Tooling**: Test-Time Compute oracle integration with MCP server.
- **Last Gasp Auto-Escalator**: Pre-failure evaluation mechanism that auto-escalates before token budget is consumed.
- **Biological Documentation Suite**: PHYLOGENY.md, MECHANISM_DESIGN.md, and naming unification docs.

### Fixed
- 15 bug fixes across the governance pipeline.

---

## [0.22.0] — 2026-09-28 — "Soma Rebirth"

### Breaking Changes
- **Project renamed**: Prism AI Steering → **Soma**
- **Repository**: `prism-ai-steering` → `soma`
- **SDK packages**: `prism-steering` → `soma-steering` (Python + npm)
- **Config**: `steering.conf` → `soma.conf`
- **Directory**: `.prism/` → `.soma/` (auto-migrated on install)

### Added — Biological Naming Unification
- `rules/` → `genome/` — Rules are now **Genes** in the organism's **Genome**
- `skills/` → `organs/` — Skills are now **Organs** (complex multi-cell structures)
- `scripts/` → `enzymes/` — Scripts are now **Enzymes** (catalytic reactions)
- `governance/` → `immune_system/` — Governance is the **Immune System**
- `EVOLUTION.md` → `PHYLOGENY.md` — Project history as evolutionary tree
- Half-Life → Telomere Shortening — Biological aging mechanism
- `governance_*.py` → `immune_*.py` — All governance scripts renamed
- Auto-migration in `install.sh`: detects `.prism/` and renames to `.soma/`

### Added — Host-Agent Delegation (Provider Abstraction)
- `enzymes/inference_provider.py` — Multi-provider inference abstraction
- Supports Gemini, Anthropic, OpenAI, and prompt-only mode
- `--provider` flag on `cell_create_nl.py`: `auto|gemini|anthropic|openai|prompt-only`
- `SOMA_INFERENCE_PROVIDER` config key in `soma.conf`
- No API key required when running inside an AI agent via MCP

### Added — MCP Stdio Server
- `soma_mcp/` — Model Context Protocol server for host-agent delegation
- Tools: `soma_create_cell`, `soma_scan`, `soma_grade`, `soma_coverage`, `soma_fitness`, `soma_list_cells`
- `soma_create_cell` delegates LLM reasoning to the host agent — zero API key needed
- Runnable as `python -m soma_mcp` or configured in any agent's MCP settings
- Works with Gemini Antigravity, Claude Code, Cursor, and any MCP-compatible agent

## [0.21.1] — 2026-09-28

### Added
- `cell_enforce.py`: Auto-generates enforcement artifacts for promoted cells
- Mechanical cells generate pre-commit hook checks in `.soma/enforcement/`
- Gate cells generate runtime assertion classes in `.soma/enforcement/`
- `enforcement_artifact` field links cells to their generated artifacts
- Coverage map now shows enforcement tier per directory
- Pre-commit hook runs mechanical checks from `.soma/enforcement/`
- Auto-trigger enforcement generation on tier promotion
- Script count: 38 → 39

## [0.21.0] — 2026-09-28

### Added
- Tiered enforcement system: cells declare `advisory`, `mechanical`, or `gate` enforcement level
- `cell_escaped_defects.py`: Independent defect tracking from CI/tests/crashes (breaks self-evaluation loop)
- Enhanced fitness formula: `bayesian_mean × (1 - escaped_defect_rate) × tier_weight`
- Enforcement tier promotion/demotion lifecycle in `cell_promote.py --tier-check`
- Tier distribution in governance report card
- Backfilled all existing cells with `enforcement: advisory`
- Script count: 37 → 38

## [0.20.0] — 2026-09-27

### Added
- Natural language cell creation (`cell_create_nl.py`) via Gemini API with multi-source API key resolution
- Python SDK (`soma_sdk/`): `pip install soma-steering` for programmatic governance access
- Counterfactual replay (`--counterfactual --cell <name>`): ROI estimation against historical commits
- Adversarial cell testing (`cell_adversarial.py`): probe cells for bypass vulnerabilities
- Governance entropy rate (`immune_entropy.py`): fossilization detection via Shannon entropy
- `pyproject.toml` for PyPI packaging
- Script count: 34 → 37

## [0.19.1] — 2026-09-27

### Fixed
- `cell_create.sh`: Added `--minimum-mode` and `--id` flags
- `cell_coverage.py`: Excludes .soma/, vendor/, .git/ from coverage counts
- `cell_fitness.py`: Fixed UnboundLocalError in --bayesian mode

### Added
- `install/hooks/pre-commit`: Git pre-commit hook for automatic cell scanning
- `cell_deps.py`: Cell dependency graph with Mermaid output
- `immune_grade.py`: Single-grade governance report card
- Script count: 32 → 34

## [0.19.0] — 2026-09-27

### Added
- Wall extinction immunity (walls immune to apoptosis, get APOPTOSIS_WARNING instead)
- Specificity penalty (anti-Goodhart: penalize cells triggering >80% of sessions)
- Bayesian cell fitness (`--bayesian`): Beta-Binomial posterior with Jeffrey's prior
- Antifragile fitness bonus (+5% per survived Tempest/Maelstrom review)
- Signal-to-noise ratio (SNR dB) per cell in fitness output
- `cell_quorum.py`: Detect systemic issues when ≥3 cells trigger simultaneously
- `cell_coverage.py`: Visualize governance blind spots across codebase
- `immune_replay.py`: Retrospective "would cells have caught this?" analysis
- `immune_trends.py`: Cross-session trend dashboard with Shannon diversity index
- Dormant spore archive (pruned cells saved to `.spores.jsonl`, reactivated on match)
- `cell_genesis_stochastic.py`: Random template injection every N sessions
- Mulch→Cell pipeline: Tempest findings auto-create vacuole cells
- Script count: 27 → 32

## [0.18.1] — 2026-09-27

### Fixed
- Wire `escalation_sentinel.sh` into `immune_init.sh` (was orphaned)
- Escalation sentinel now scans walls AND membranes for `minimum_mode`
- Thorns terminology disambiguation in README

### Added
- `cell_scan.py`: Automated diff→cell triggering via git diff and target_paths
- `target_paths` field in cell YAML schema
- `DEFAULT_REVIEW_MODE` and `MINIMUM_REVIEW_MODE` in soma.conf
- Session fitness dashboard in session_close.sh

## [0.18.0] — 2026-09-27

### Added
- Centralized workspace resolution (`soma_resolve.py`) — CWD-first, vendor-safe
- Automated evolutionary loop in `session_close.sh`
- Apoptotic fast-kill in `cell_fitness.py` (FP > 2×TP)
- Homeostatic governance intensity in `immune_init.sh`

### Changed
- All scripts use `soma_resolve.py` instead of inline resolution
- Script count: 25 → 26

## [0.17.1] — 2026-09-27

### Added
- Cell lineage tracking (`lineage` block in YAML) — phylogenetic tree support
- Per-type telomere shortening configuration (`CELL_TELOMERE_WALL`, etc.)
- Effector→Memory auto-transition via `decay_to` field
- Benchmark protocol (`docs/BENCHMARK.md`)

## [0.17.0] — 2026-09-27

### Added
- GA crossover operator (`cell_crossover.py`) — merges complementary cell hypotheses
- Tournament selection (`cell_tournament.py`) — diversity-preserving cell selection
- Cell metamorphosis (`cell_metamorphose.py`) — vacuole → wall → rule maturity paths
- Horizontal gene transfer (`cell_transfer.sh`) — cross-project cell sharing with fitness reset
- Fitness landscape visualization (`fitness_landscape.py`) — ASCII governance dashboard
- Confidence telomere shortening decay in `cell_fitness.py` — stale cells fade naturally
- Effector/memory cell flags in `cell_create.sh` — incident response patterns
- Incident response templates (`templates/incident-response/`)
- `CELL_TELOMERE_DAYS` configuration in `soma.conf.example`

### Changed
- Script count: 20 → 25
- `cell_signal.sh` now records `last_trigger_date` for telomere shortening calculation

## [0.16.0] — 2026-09-27

### Added
- External fitness signal API (`cell_signal.sh`) — any system (CI/CD, monitoring, game results) can feed outcomes to cells
- Programmatic cell creation (`cell_create.sh`) — create cells from automated systems
- Cell demotion (`cell_demote.py`) — reverse promotion when cells cause issues in new contexts
- Cell templates by domain (`templates/`) — RL training, web backend, infrastructure, data pipeline
- 14 domain-specific cell templates with self-pruning (`expiry_sessions: 5`)
- Template auto-detection in Genesis Stage 5 based on project dependencies

### Changed
- Script count: 18 → 20

## [0.15.1] — 2026-09-27

### Added
- Liveness sentinel script (`liveness_sentinel.sh`) for subagent health monitoring
- Enhanced Genesis Lichen phase with magic number / hardcoded coordinate detection
- Enhanced Plasmodesmata detection with explicit patterns (pip install -e, shared DBs, protobuf imports)

## [0.15.0] — 2026-09-27

### Added
- Team topology: `TEAM_REPO` and `ORG_REPO` configuration for multi-developer governance convergence
- `team_sync.sh` for push/pull/status of shared cells and metrics
- Clean uninstaller (`uninstall.sh`) with backup/restore and manifest tracking
- Install manifest (`~/.soma/manifest.json`) for safe uninstall
- Backup-on-install: archives existing config before overwriting
- Peer-reviewed research abstract (`ABSTRACT.md`) with 5-reviewer record (`REVIEWS.md`)
- GitHub Actions CI workflow
- `CONTRIBUTING.md` with CLA language
- `VERSION` file and semantic versioning

### Changed
- Deprecated legacy per-platform installers in favor of unified `install.sh`
- Script count: 15 → 17

## [0.14.0] — 2026-09-27

### Added
- Cross-repo fitness aggregation (`cell_fitness.py --cross-repo`)
- Adaptive cell refinement (`cell_adapt.py`)
- Speciation/promotion path (`cell_promote.py`) — local cells graduate to global rules
- Plasmodesmata cell type for cross-repo connections

## [0.13.0] — 2026-09-27

### Added
- Cytogenesis infrastructure (`.soma/cells/`)
- Cell fitness scoring (`cell_fitness.py`)
- Cell selection lifecycle (`cell_selection.sh`)
- Four cell types: Vacuole, Chloroplast, Cell Wall, Membrane
- Genesis Stage 5: automated cell generation

## [0.12.0] — 2026-09-27

### Added
- Calibrated tokenizer (1.35 ratio, validated against Gemini API)
- Apache 2.0 license, NOTICE file, privacy statement
- Privacy-safe metrics via `METRICS_REPO` configuration
- Rule compression optimization

### Changed
- Token census now uses empirical calibration instead of estimates

## [0.11.0] — 2026-09-27

### Added
- Cross-platform validation (bash + PowerShell)
- Genesis onboarding skill (5-stage codebase reconnaissance)
- 66-session expanded dataset analysis
- Unified installer (`install.sh`) replacing per-platform scripts

### Changed
- Renamed project from internal naming to Soma

## [0.10.0] — 2026-09-26

### Added
- Tempest cross-conversation analysis
- Subagent nesting (E11)
- Adaptive review orchestrator
- Escalation sentinel script

## [0.9.0] — 2026-09-26

### Added
- Maelstrom academic integration (Refutation Gate, Boundary Verification, Orthogonal Personas)
- FPSR metric (First-Pass Success Rate)

## [0.1.0–0.8.0] — 2026-09-26

### Added
- Initial governance rules (Providence, cost optimization, subagent delegation)
- Review protocol (Breeze through Tempest, Spores through Mulch)
- Testing and git workflow rules
- Lifecycle hooks (governance_init, safety_gate, session_close)
- Experiment framework (E1–E22)
- Metrics infrastructure (token census, metrics snapshot)

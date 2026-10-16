# ADR 0015: Language-Agnostic AST Analysis via Normalized AST Drivers (NAD)

## Status
**Accepted** (v1.1.0 — 2026-10-08; updated for Aegis Guardrails v3.2.0)

**v4 status (2026-10-15): in force, with one change.** The protocol and the TypeScript, Go and Rust drivers stay ([ADR 0005](0005-v4-plan-of-record.md) §5). A repository can no longer name driver commands (§5 "Config", review H5), so the `.aegis/slots.yaml` route below is withdrawn; the `install/drivers/` copies and `aegis detect` are cut.

## Context
Aegis Guardrails' Layer 1 verification subsystem (`aegis_core/verification/`) enforces deterministic, evidence-based code quality checks before any AI-generated change can be arbitrated or committed. Among these tools, the Call Graph Completeness Checker (`aegis_core/verification/call_graph.py`) and Mutation Tester (`aegis_core/verification/mutation_tester.py`) rely fundamentally on Abstract Syntax Tree (AST) analysis to:
1. Extract function, method, class, and export definitions.
2. Resolve intra-module and inter-module call sites without false-positive regex collisions.
3. Identify syntactically valid operator and comparison mutation candidates.

Historically, these checkers were implemented directly against Python's standard library `ast` module (`ast.parse`, `ast.NodeVisitor`). While effective for pure Python projects, this created severe limitations for polyglot codebases:
1. **Language Inequity**: Non-Python source files (TypeScript, JavaScript, Go, Rust) in polyglot repositories were either silently skipped or blocked from Layer 1 reachability and mutation verification.
2. **Repository Bloat Trap**: Naively bundling third-party multi-language parsers (such as Tree-Sitter grammars, Babel, or compiled C/WASM binaries) would bloat the distribution repository by dozens of megabytes, add native platform compilation dependencies, and directly violate Aegis Guardrails' strict zero-dependency runtime guarantee (`dependencies = []`).
3. **Sandbox & Architecture Portability**: Binary distribution or heavy language runtime bundling would break execution on minimal containers, BSD/Solaris, ARM, or locked-down developer environments.

## Decision
1. **The Normalized AST Driver (NAD) Protocol**: Establish a language-agnostic Intermediate Representation (`NormalizedAST`) and driver contract in `aegis_core/ast/`. The schema decouples AST consumers (call graph reachability, mutation testing) from language-specific AST producers.
2. **Standard Intermediate Representation Schema (`aegis_core.ast.schema`)**:
   - `DefinitionNode`: Canonical function, method, class, and type definitions with export status.
   - `CallSiteNode`: Explicit invocation targets, source lines/columns, and caller scope.
   - `ImportNode`: Module specifiers and imported symbols.
   - `MutationPoint`: Syntactically valid mutation candidates with operator swaps, byte offsets, and line/column coordinates.
3. **Dual Execution Paths**:
   - **Native Python Fast-Path (In-Process)**: Python source files continue to be parsed directly in-process via stdlib `ast.parse` in `aegis_core.ast.drivers.python`, maintaining sub-millisecond execution with zero process overhead.
   - **Host-Native Process Drivers (External)**: Non-Python source files execute lightweight host-native CLI drivers resolved via `.aegis/slots.yaml` (`ast_driver_{ext}` or `ast_driver`) or registered in `ASTDriverRegistry` (`aegis_core/ast/runner.py`).
4. **Strict Confinement and Timeouts**:
   - Drivers execute via vector arguments (`shell=False`) with a non-blocking, enforced 3.0-second timeout (`ASTDriverTimeoutError`, `AST_RUNNER_TIMEOUT_SECONDS = 3.0`).
   - Workspace confinement verifies that source files cannot traverse outside the active workspace directory.
5. **Zero Bundled Grammars / Zero Runtime Dependencies**:
   - The core distribution bundles zero external grammar packages or compiled binaries.
   - Reference driver recipes (`install/drivers/ts_ast.js`, `install/drivers/go_ast.go`, `install/drivers/rust_ast.py`) use host tools (Node.js, Go stdlib `go/parser`, Python stdlib) and standard system utilities.
6. **Diagnostic Transparency**:
   - `aegis doctor` (`aegis_cli/doctor.py`) and `aegis detect` (`aegis_cli/detect.py`) inspect configured AST drivers, verifying executable resolution or falling back gracefully to native Python analysis.

## Consequences

### Positive
- **Polyglot Verification**: Layer 1 Call Graph reachability and Mutation Testing seamlessly analyze Python, TypeScript, JavaScript, Go, Rust, and any language with a configured driver.
- **Zero Bloat**: Repository and package wheel size remain minimal; pure Python standard library runtime is strictly preserved (`dependencies = []`).
- **Decoupled Evolution**: Supporting a new language (e.g., Java, C#) requires only a small CLI recipe emitting JSON, with zero changes to `aegis_core/verification/` logic.
- **Fast and Resilient**: Python files experience zero performance regression; polyglot files execute in <150ms per file, bounded by strict 3.0s timeouts.

### Negative / Trade-offs
- **Host Runtime Dependency for Polyglot Files**: Analyzing non-Python files (other than Python and bundled pure-Python Rust parsing) requires the corresponding language runtime (e.g., `node` for TypeScript, `go` for Go) to be installed on the host or configured in `.aegis/slots.yaml`. If missing, Aegis fails closed or skips gracefully according to slot configuration.
- **Inter-Process Serialization**: External polyglot drivers involve JSON serialization and subprocess launch, adding ~50–150ms overhead per polyglot file analyzed compared to in-process parsers.

## Verification & Compliance
- **Schema & Roundtrip Tests**: `tests/unit/core/test_normalized_ast_schema.py` validates serialization, deserialization, and lookup semantics.
- **Driver Runner Tests**: `tests/unit/core/test_ast_driver_runner.py` verifies timeout enforcement, error propagation, and workspace confinement.
- **Polyglot Call Graph Tests**: `tests/unit/verification/test_polyglot_call_graph.py` validates reachability, orphan detection, and comment/string filtering across polyglot files.
- **Polyglot Recipes & Mutation Tests**: `tests/unit/core/test_polyglot_recipes.py` verifies Node.js/TypeScript driver recipes, Go recipe syntax, and byte-offset mutation application.


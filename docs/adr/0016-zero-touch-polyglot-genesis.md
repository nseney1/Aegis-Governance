# ADR 0016: Zero-Touch Genesis Polyglot Provisioning & Rust Driver

## Status
**Accepted** (v1.2.0 — 2026-10-08; updated for Aegis Guardrails v3.2.0)

**v4 status (2026-10-15): partly superseded by [ADR 0005](0005-v4-plan-of-record.md) §5.** Zero-touch provisioning of `.aegis/slots.yaml` is withdrawn: a repository-writable file that names commands executes code ([review](0005-evidence-review.md) H5). `aegis detect` and the `install/drivers/` copies are cut. The Rust driver and the diff-base fix in `aegis_core/verification/runner.py` stay.

## Context
Following ADR 0015 (Normalized AST Driver Protocol), Aegis Guardrails introduced language-agnostic verification capabilities for non-Python source code (TypeScript, JavaScript, Go). However, adoption in real-world polyglot repositories faced friction:
1. **Manual Provisioning Barrier**: Developers onboarding polyglot repositories had to manually create or edit `.aegis/slots.yaml` with language driver slots (`ast_driver_ts`, `ast_driver_go`) and copy template drivers.
2. **Missing Rust Support**: Rust source files (`.rs`) lacked an AST driver recipe, leaving Rust definitions, imports, calls, and mutation points unverifiable by Layer 1.
3. **CI/Release Verification Drift**: On clean release tags or merge commits without PR base branches, Layer 1 deterministic verification suffered fallback disconnects when `HEAD~1` was queried without passing the resolved diff base into `aegis_core/verification/runner.py::_get_modified_lines`.

## Decision
1. **Zero-Touch Polyglot Detection & Provisioning (`aegis_core.ast.detect`)**:
   - `detect_project_languages(workspace_root)`: Fast-scans the repository for primary programming languages (Python, TypeScript, JavaScript, Go, Rust) via manifest inspection (`package.json`, `go.mod`, `Cargo.toml`) and directory file extension sampling with standard ignores (`target/`, `node_modules/`, `.git/`, `dist/`, `build/`).
   - `resolve_recommended_drivers(detected_languages)`: Maps detected non-Python languages to recommended driver templates and slot commands.
   - `provision_ast_driver_slots(workspace_root, detected_languages)`: Automatically provisions `.aegis/slots.yaml` and copies driver templates into `.aegis/drivers/` without requiring manual developer configuration.
2. **First-Class Rust AST Driver (`install/drivers/rust_ast.py`, `aegis_core/ast/drivers/templates/rust_ast.py`)**:
   - A pure Python standard library driver (`rust_ast.py`) parsing Rust files into Normalized AST JSON (with an in-process fast path via `parse_rust_source`).
   - Extracts:
     - Function, struct, enum, trait, and impl definitions with `pub` visibility.
     - `use` import declarations.
     - Function/method invocation call sites and macro invocations (`println!`, etc.).
     - Binary and comparison operator mutation points (`+` ↔ `-`, `*` ↔ `/`, `==` ↔ `!=`, `<` ↔ `>`, etc.).
3. **Init & Detect Integration (`aegis init`, `aegis detect`)**:
   - Both commands (`aegis_cli/init.py`, `aegis_cli/detect.py`) run polyglot language detection and provision driver slots during project setup or on demand.
4. **Self-Healing Diagnostics (`aegis doctor --fix`)**:
   - `aegis doctor` (`aegis_cli/doctor.py`) reports unconfigured AST drivers for detected repository languages.
   - Passing `--fix` automatically provisions missing `.aegis/slots.yaml` slots and driver files.
5. **Deterministic Verification Diff-Base Synchronization (`aegis_core/verification/runner.py`, `aegis_cli/verify.py`)**:
   - `aegis_cli/verify.py::resolve_target_files` records the matching diff reference (`_diff_base`) and passes it into `runner.run_layer1(..., diff_base=ref)`.
   - `runner.py::_get_modified_lines` accepts `diff_base` and falls back to `HEAD~1...HEAD` and `HEAD~1`, ensuring consistent modified-line scoping on clean post-merge pushes, release tags, and PRs alike.

## Consequences

### Positive
- **True Zero-Touch Onboarding**: `aegis init` and `aegis detect --fix` configure complete polyglot AST verification out of the box with zero manual YAML authoring.
- **Pure Stdlib Runtime Maintained**: The Rust AST driver is written entirely in Python stdlib (`dependencies = []`), adhering strictly to Aegis Guardrails' zero-dependency runtime standard.
- **Robust CI & Release Publishing**: Layer 1 verification reliably resolves modified lines on release workflows and post-merge `main` pushes without false-positive whole-file regressions.
- **Self-Healing Workspaces**: `aegis doctor --fix` remediates unconfigured driver slots seamlessly.

### Negative / Trade-offs
- **Rust Driver Heuristics**: The standard-library Rust driver relies on token-level scanning rather than full compiler-grade macro expansion (e.g., `rustc -Z ast-json`), prioritizing zero external dependencies and fast (<10ms) execution over deep macro expansion.

## Verification & Compliance
- **Detection & Provisioning Tests**: `tests/unit/core/test_polyglot_detect.py`.
- **Rust AST Driver Tests**: `tests/unit/core/test_rust_ast_driver.py`.
- **CLI Polyglot Integration Tests**:
  - `tests/unit/cli/test_init_polyglot.py`.
  - `tests/unit/cli/test_genesis_polyglot.py`.
  - `tests/unit/cli/test_doctor_polyglot.py`.
- **Layer 1 Diff-Base & Fallback Tests**: `tests/unit/verification/test_layer1.py`.


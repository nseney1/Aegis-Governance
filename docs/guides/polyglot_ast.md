# Polyglot AST Analysis Guide

> Language-agnostic Layer 1 static analysis via `NormalizedAST` (`aegis_core/ast/schema.py`) and `ASTDriverRunner` (`aegis_core/ast/runner.py`).

---

## 1. Architecture Overview

Aegis Guardrails v3.2.0 decouples Layer 1 deterministic verification (call graph reachability, orphan symbol detection, import guards, and mutation testing) from Python-specific AST traversal using the **Normalized AST Driver (NAD) Protocol**:

1. **In-Process Python Fast-Path (`aegis_core/ast/drivers/python.py`)**:
   - All `.py` files are parsed in-process via `parse_python_ast()` using Python's standard library `ast` module.
   - Executes in sub-millisecond time with zero subprocess overhead.
2. **External Host-Native Drivers (`ASTDriverRunner` in `aegis_core/ast/runner.py`)**:
   - When Aegis analyzes non-Python source files (`.rs`, `.ts`, `.tsx`, `.js`, `.jsx`, `.go`), `ASTDriverRunner` resolves the configured driver via `ASTDriverRegistry` and `.aegis/slots.yaml`.
   - Drivers execute as isolated subprocesses (`shell=False`), confined to the workspace root via `confine_path_internal`, with a strict 3.0-second timeout (`ASTDriverTimeoutError`).
   - Each driver parses the target file and emits a `NormalizedAST` JSON payload to `stdout`.

---

## 2. Auto-Detection & Provisioning (`aegis detect --fix`)

Aegis can automatically detect languages in your repository, provision reference AST drivers into `.aegis/drivers/`, and bind them in `.aegis/slots.yaml`:

```bash
# Scan workspace languages and preview recommended AST drivers
aegis detect

# Provision .aegis/drivers/{rust_ast.py,ts_ast.js,go_ast.go} and update .aegis/slots.yaml
aegis detect --fix
```

### `.aegis/slots.yaml` Driver Configuration

`SlotRegistry` (`aegis_core/skills/slots.py`) and `ASTDriverRegistry` (`aegis_core/ast/runner.py`) resolve extension-specific keys (`ast_driver_<ext>`) or a global fallback (`ast_driver`) from `.aegis/slots.yaml`:

```yaml
# .aegis/slots.yaml
slots:
  ast_driver_rs: "python3 .aegis/drivers/rust_ast.py"
  ast_driver_ts: "node .aegis/drivers/ts_ast.js"
  ast_driver_tsx: "node .aegis/drivers/ts_ast.js"
  ast_driver_js: "node .aegis/drivers/ts_ast.js"
  ast_driver_go: "go run .aegis/drivers/go_ast.go"
```

If no driver is configured for a file extension, `ASTDriverRunner` raises `NoDriverConfiguredError` internally and Layer 1 gracefully skips external AST checks for that extension without false-positive failures.

---

## 3. `NormalizedAST` Schema (`aegis_core/ast/schema.py`)

External drivers accept the target source file path as their final argument:
```bash
<driver_command> <path/to/source/file>
```
and emit a JSON object deserialized by `NormalizedAST.from_dict()` (`aegis_core/ast/schema.py`):

```json
{
  "version": "1.0",
  "file_path": "src/service.ts",
  "language": "typescript",
  "definitions": [
    {
      "name": "calculateTax",
      "kind": "function",
      "line": 10,
      "is_exported": true,
      "class_name": null
    }
  ],
  "call_sites": [
    {
      "target": "helperFunction",
      "line": 15,
      "caller_scope": "calculateTax"
    }
  ],
  "imports": [
    {
      "source": "./utils",
      "imported_symbols": ["helperFunction"],
      "line": 1,
      "is_type_only": false
    }
  ],
  "mutation_points": [
    {
      "line": 12,
      "col": 11,
      "original_op": "===",
      "replacement_op": "!==",
      "mutation_type": "cmpop",
      "function_scope": "calculateTax",
      "byte_offset": 142
    }
  ]
}
```

### Dataclass Contracts in `aegis_core/ast/schema.py`

| Dataclass | Fields | Purpose |
|:----------|:-------|:--------|
| **`NormalizedAST`** | `file_path`, `language`, `definitions`, `call_sites`, `imports`, `mutation_points`, `version` | Root container returned by `ASTDriverRunner.run()` |
| **`DefinitionNode`** | `name`, `kind` (`function`/`method`/`class`/`constant`), `line`, `is_exported`, `class_name` | Symbol declaration used by call graph and reachability analyzers |
| **`CallSiteNode`** | `target`, `line`, `caller_scope` | Function/method invocation edges for call graph construction |
| **`ImportNode`** | `source`, `imported_symbols`, `line`, `is_type_only` | Module dependency edges inspected by `import_guard` |
| **`MutationPoint`** | `line`, `col`, `original_op`, `replacement_op`, `mutation_type`, `function_scope`, `byte_offset` | Candidate operators mutated by `mymut` mutation testing |

---

## 4. Reference Drivers (`.aegis/drivers/`)

When provisioned via `aegis detect --fix`, Aegis installs zero-dependency reference drivers into `.aegis/drivers/`:

- **Rust Driver (`.aegis/drivers/rust_ast.py`)**:
  - Pure Python 3.10+ recursive-descent / token-stream extractor for `.rs` files (`fn`, `pub fn`, `struct`, `impl`, `trait`, `use`, call sites, and comparison/arithmetic mutation points).
- **TypeScript / JavaScript Driver (`.aegis/drivers/ts_ast.js`)**:
  - Uses the official `typescript` compiler API if present in `node_modules`, automatically falling back to a deterministic zero-dependency lexer in bare Node.js environments.
- **Go Driver (`.aegis/drivers/go_ast.go`)**:
  - Uses Go's standard library (`go/parser`, `go/token`, `go/ast`, `encoding/json`) with zero external module dependencies.

---

## 5. Diagnostics & Verification

Verify driver health and run polyglot Layer 1 checks from the CLI:

```bash
# Verify configured AST driver executables and .aegis/slots.yaml bindings
aegis system doctor

# Run Layer 1 deterministic AST verification across Python and polyglot files
aegis check
```

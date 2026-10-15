# Contributing to Aegis Guardrails

Thank you for your interest in contributing to **Aegis Guardrails**!

Aegis is a zero-dependency, local-first adaptive governance framework, AST verification engine, and Model Context Protocol (MCP) server for AI coding agents.

---

## 1. Development Setup

### Prerequisites
- **Python 3.10+** (pure standard library runtime; `pytest` and `hypothesis` for test execution)
- **Git**

### Clone & Editable Install
```bash
git clone https://github.com/nseney1/Aegis-Guardrails.git
cd Aegis-Guardrails
pip install -e ".[dev]"
```

### Verify Environment Health
```bash
aegis --version
aegis system doctor
```

---

## 2. Running Tests & Verification

Before opening a Pull Request, run the full test suite and Layer 1 deterministic verification:

```bash
# Run the full test suite
python3 -m pytest -q

# Run documentation & release contract checks
python3 -m pytest tests/unit/core/test_documentation_accuracy.py -q

# Run Layer 1 deterministic AST checks (syntax, import_guard, call_graph, pytest, mymut)
aegis check
```

> **Note on Local Test Caches**: Property-based testing generates `.hypothesis/` and pytest generates `.pytest_cache/`. Never commit binary test caches to version control.

---

## 3. Branching & Pull Request Workflow (Gitflow + Independent Review Gate)

Aegis enforces a strict Gitflow workflow with structural separation between code authors and reviewers (`rules/gitflow-review-gate.md`):

| Target Branch | Purpose | Review & Merge Authority |
|:--------------|:--------|:-------------------------|
| `develop` | Feature and bugfix integration (`feature/*`, `fix/*`) | Independent AI audit subagent or maintainer review required before merge |
| `main` | Production releases (`release/*`, `hotfix/*`) | Human maintainer review and merge only |

### Submitting Changes
1. Fork the repository and branch from `develop`:
   ```bash
   git checkout -b feature/your-change develop
   ```
2. Implement your change following existing architectural boundaries (`aegis_core`, `aegis_mcp`, `aegis_cli`, `aegis_sdk`).
3. Ensure zero runtime third-party dependencies are added to `pyproject.toml` (`dependencies = []`). Any optional integration must be guarded with `try/except ImportError`.
4. Add behavioral unit/integration tests covering both happy and sad paths.
5. Verify all tests pass (`python3 -m pytest -q`) and run `aegis check`.
6. Open a Pull Request targeting `develop`.

### Release Gate 4.5 (`aegis check --release`)
All release branches and tag candidates must pass **Release Gate 4.5**:
```bash
aegis check --release
```
Gate 4.5 cryptographically verifies that:
- The working tree is clean.
- The latest adversarial arbitration cycle concluded with a `SHIP` verdict.
- The arbitration receipt's `tree_hash` matches `git rev-parse HEAD^{tree}`.
- Every modified file in `origin/main...HEAD` is covered by the verified receipt.

---

## 4. Authoring Rules & Skills

### Adaptive Workspace Rules (`.aegis/rules/`)
Workspace rules live in `.aegis/rules/{invariants,traps,gates,methods}/` and use `AegisYAML` frontmatter:
- **`invariant`** (`invariants/`): Hard architectural and security constraints (`enforcement: gate`).
- **`trap`** (`traps/`): Historical anti-patterns and regressions (`enforcement: advisory` or `gate`).
- **`gate`** (`gates/`): Pre-commit, CI, and verification gates (`enforcement: gate`).
- **`method`** (`methods/`): Workflow guidance, personas, and practices (`enforcement: advisory`).

Create a new rule via CLI or MCP:
```bash
aegis rule create --type trap --id my-new-trap --title "Prevent Unbounded Retries"
aegis rule list
```

### Core Rules (`rules/`) & Agent Skills (`skills/`)
- **Core Rules (`rules/`)**: Foundational rules shipped with Aegis must trace back to an observed failure mode, include a falsifiable hypothesis, and pass `aegis check`.
- **Agent Skills (`skills/<skill-name>/SKILL.md`)**: Horizontal capabilities defined with `AegisYAML` frontmatter (`id`, `tier`, `consumes`, `produces`, `handoff_targets`, `slot_constraints`). Inspect skills and slot bindings with:
  ```bash
  aegis skill list
  aegis skill inspect <skill-id>
  aegis skill slots
  ```

---

## 5. Privacy & Security Invariants

All contributions must uphold Aegis's local-first privacy and security guarantees:
- **Zero Telemetry Exfiltration**: Never add outbound network calls to `aegis_mcp` or default CLI workflows.
- **Workspace Confinement**: All file operations must resolve through `confine_path_internal` / `Workspace.confine`.
- **Privacy Invariant**: Evidence ledgers (`.aegis/evidence/`) record only sanitized aggregate counts, booleans, and rule IDs—never raw secrets, credentials, or external user PII.

See [PRIVACY.md](PRIVACY.md), [SECURITY.md](SECURITY.md), and [NOTICE](NOTICE) for complete details.

---

## 6. Contributor License Agreement & Code of Conduct

By submitting a pull request, you agree that your contributions are licensed under the **Apache License 2.0** ([LICENSE](LICENSE)) that covers this project, and you certify that you have the right to grant this license.

Be respectful, constructive, and evidence-driven — the same principles that govern our AI agents govern our community.

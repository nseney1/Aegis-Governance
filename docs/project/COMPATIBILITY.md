# Backwards Compatibility Guarantee (SemVer 2.0)

> Formal commitment to stability, zero silent breaking changes, and predictable evolution for **Aegis Guardrails** (`v3.2.0`).

---

## 1. Scope & Guarantee

Aegis Guardrails strictly adheres to [Semantic Versioning 2.0.0](https://semver.org/).

### Semantic Versioning Rules
- **Patch Releases (`3.2.x`)**: Bug fixes, defect remediation, performance optimizations, and documentation updates. Zero breaking changes to any public API, CLI command, MCP tool schema, or rule frontmatter format.
- **Minor Releases (`3.x.0`)**: Backward-compatible feature additions, new MCP tools, new verification checks, and opt-in configurations. No public API or CLI behavior will be removed or altered in a backwards-incompatible manner.
- **Major Releases (`4.0.0`)**: Breaking architectural changes. Any breaking change must undergo a minimum two-minor-version deprecation cycle with loud warnings and migration tooling.

---

## 2. Public API Surface

The following surfaces are classified as **Public Contracts** protected by this guarantee in `v3.2.0`:

1. **Python SDK (`aegis_sdk`)**:
   - `aegis_sdk.Governance`
   - `aegis_sdk.rules.Rule`, `RuleFitness`, `parse_rule_file`
   - `aegis_sdk.scoring` (`wilson_lower_bound`, `wilson_interval`, `compute_snr`)
   - `aegis_sdk.errors` hierarchy (`AegisError`, `AegisValidationError`, `RuleNotFoundError`, `RuleParseError`, `RulePathTraversalError`)
2. **CLI Porcelains (`aegis` / `aegis_cli`)**:
   - Core verbs: `aegis init`, `aegis status`, `aegis check` (including `--release`, `--layer1-only`, `--plan`, `--rebuttal`), `aegis rule` (`list`, `promote`, `demote`, `archive`, `clean`), `aegis system`
   - Inspection & lifecycle: `aegis doctor`, `aegis detect`, `aegis sync`, `aegis report`, `aegis install`, `aegis uninstall`, `aegis verify`, `aegis checkpoint`, `aegis completion`
   - Workspace migration: `aegis migrate` (`--dry-run`, `--json`)
   - Headless plumbing: `aegis agent`
3. **MCP Server (`aegis-mcp` / `aegis_mcp`)**:
   - All 17 registered `aegis_*` tool names and input schemas in `aegis_mcp/registry.py`.
   - Tool tier classifications (`Read` default, `Write` receipt-required, `Execute` opt-in receipt-required).
   - State-bound, burn-before-compare cryptographic receipts (`ReceiptManager`).
   - Opt-in response projection semantics (`view`, `fields`) and `AEGIS-V01` secret scrubbing.
4. **Rule & Governance Schema**:
   - Rule YAML frontmatter structure parsed by `AegisYAML` (`aegis_core/yaml.py`).
   - Canonical rule types (`invariant`, `trap`, `gate`, `boundary`, `persona`, `contract`) and review taxonomy (`Patrol`, `Sweep`, `Vanguard`, `Bulwark`, `Fortress`, `Citadel` in `aegis_core/taxonomy.py`).
   - Field semantics for `id`, `type`, `enforcement`, `target_paths`, `fitness`, `hypothesis`, `prediction`, `falsification`, `minimum_mode`.
   - `.aegis/` and `.aegis/rules/` filesystem directory conventions.

---

## 3. Legacy `.soma` → `.aegis` Workspace Migration (`aegis migrate`)

Workspaces created under the legacy Soma layout (`.soma/cells/`) are supported via a deterministic, one-way atomic upgrade path:

- **Upgrade Command**: Run `aegis migrate` (supports `--dry-run` and `--json` via `aegis_cli/migrate.py`).
- **What `aegis migrate` Does**:
  1. Atomically migrates `.soma/` state and `.soma/cells/` directories to `.aegis/` and `.aegis/rules/` (`invariants/`, `traps/`, `gates/`, `boundaries/`, `personas/`, `contracts/`).
  2. Rewrites legacy biological frontmatter fields (`vacuole` → `trap`, `wall` → `invariant`, `membrane` → `boundary`, `chloroplast` → `persona`, `plasmodesmata` → `contract`) and legacy review modes (`breeze` → `patrol`, `gale` → `sweep`, `trident` → `vanguard`, `maelstrom` → `bulwark`, `tempest` → `fortress`, `supercell` → `citadel`).
  3. Preserves all evidence ledgers (`.aegis/evidence/signals.jsonl`, `outcomes.jsonl`) and rule fitness history.
- **Upgrade Sentinel**: If an unmigrated `.soma/` directory is detected without `.aegis/`, Aegis emits an explicit diagnostic instructing the user to run `aegis migrate`.

---

## 4. Deprecation Policy

When an existing public capability is scheduled for replacement:
1. **Notice Phase**: The feature is marked deprecated in documentation and emits a `DeprecationWarning` (or CLI warning) pointing to the modern replacement.
2. **Grace Period**: The deprecated interface remains functional for a minimum of two minor releases before removal in the next major release.
3. **Removal**: Deprecated interfaces are never removed in a patch or minor release within the same major version series.

---

## 5. Platform & Runtime Guarantees (v3.2.0)

- **Supported AI Coding Platforms (`aegis_cli/platforms/`)**:
  - **Gemini / Antigravity** (`~/.gemini/config/rules/`, `~/.gemini/config/skills/`, MCP integration)
  - **Claude Code** (`~/.claude/` or `<project>/.claude/`, `CLAUDE.md`, `.mcp.json`)
  - **Cursor** (`.cursor/rules/`, `.cursor/mcp.json`)
  - **GitHub Copilot** (`.github/copilot-instructions.md`, `.vscode/mcp.json`)
  - **Kiro** (`.kiro/steering/`, `.kiro/settings/mcp.json`)
- **Python Runtime**: Pure Python standard library with zero mandatory runtime dependencies (`dependencies = []`). First-class support across **Python 3.10, 3.11, 3.12, and 3.13** (with `from __future__ import annotations` maintaining compatibility back to Python 3.9).
- **Operating Systems**: First-class support and continuous CI testing across **Ubuntu (Linux)**, **macOS**, and **Windows** (Windows 11 with PowerShell 5.1+, PowerShell 7+, and Git Bash).


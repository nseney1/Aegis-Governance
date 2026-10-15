# Aegis Guardrails Quickstart Guide

## What Aegis Does

**Aegis Guardrails** (v3.2.0) is an adaptive governance, AST verification, and Model Context Protocol (MCP) server framework for AI coding agents. It installs self-evolving governance rules, enforces a two-layer verification pipeline, and records empirical outcome evidence with zero runtime dependencies.

---

## 1. Installation

Choose the option that matches your environment.

### Option 1: Install from PyPI (Recommended)

**Requires:** Python 3.10+ and `pip` (or `pipx`).

```bash
pip install aegis-guardrails
# Or in an isolated user-wide environment:
pipx install aegis-guardrails
```

### Option 2: Editable Source Install

**Requires:** Git, Python 3.10+, and `pip`.

```bash
git clone https://github.com/nseney1/Aegis-Guardrails.git
cd Aegis-Guardrails
pip install -e ".[dev]"
```

> **PEP 668 (externally managed Python)?** Use a virtual environment (`python3 -m venv .venv && source .venv/bin/activate`) or `pipx install aegis-guardrails` (`pipx ensurepath` places `aegis` on your `PATH`).

### Verify the Install

```bash
aegis --version
aegis system doctor
```

### `aegis: command not found`?

`pip install --user` puts `aegis` in your user scripts directory (`~/.local/bin` on Linux), which may not be on `PATH`. Run `python3 -m aegis_cli.cli system doctor` (use `python` on Windows) to inspect your environment. Typical `PATH` fixes:

| Shell | Add to | Line |
|:--|:--|:--|
| zsh | `~/.zshrc` | `export PATH="$HOME/.local/bin:$PATH"` |
| bash | `~/.bashrc` (macOS: `~/.bash_profile`) | `export PATH="$HOME/.local/bin:$PATH"` |
| fish | `~/.config/fish/config.fish` | `fish_add_path $HOME/.local/bin` |
| PowerShell | user `Path` variable | `[Environment]::SetEnvironmentVariable(...)` printed by `aegis system doctor` |

Prefer automated setup? Run `aegis system doctor --fix-path` for a dry-run preview, or `aegis system doctor --fix-path --yes` to append the `PATH` entry for `zsh`, `bash`, or `fish`.

---

## 2. First Run with `aegis init` & `.mcp.json` Setup

`aegis init` auto-detects Gemini, Claude Code, Cursor, Copilot, and Kiro markers, scaffolding `.aegis/rules/`, `.aegis/slots.yaml`, and platform integrations.

```bash
# Auto-detect platform and initialize workspace governance
aegis init --yes

# Initialize with MCP server configuration (.mcp.json)
aegis init --mcp --yes

# Inspect workspace status and run Layer 1 verification
aegis status
aegis check
```

Useful `aegis init` options:

```bash
aegis init --dry-run
aegis init --rules minimal --platform claude
aegis init --rules standard --mcp --platform cursor --yes
aegis init --rules full --platform gemini --force --yes
```

Running `aegis init --mcp` writes a project-local `.mcp.json` (or platform-specific MCP config) pointing to `python3 -m aegis_mcp`:

```json
{
  "mcpServers": {
    "aegis": {
      "command": "python3",
      "args": ["-m", "aegis_mcp"],
      "env": {
        "AEGIS_WORKSPACE": "/path/to/your/repo",
        "AEGIS_EXECUTION_ENABLED": "1"
      }
    }
  }
}
```

---

## 3. Core CLI Workflow

```bash
# 1. Workspace initialization & MCP setup
aegis init                    # Auto-detect AI platform & configure .aegis/
aegis init --mcp              # Generate .mcp.json for MCP-compatible agents

# 2. Workspace status & outcome reporting
aegis status                  # View active rules, lifecycle tiers, and Bayesian fitness
aegis report --rule <id> --outcome pass   # Record rule execution outcome signal

# 3. Two-Layer Verification Gate
aegis check                   # Layer 1 deterministic AST checks (syntax, imports, call graph, pytest, mymut)
aegis check --hook            # Fast git pre-commit verification gate
aegis check --full            # Full Layer 1 + Layer 2 adversarial arbitration
aegis check --in-band         # Zero-key interactive Layer 2 charge-sheet verification
aegis check --release         # Release Gate 4.5 cryptographic receipt verification

# 4. Adaptive Rule Management (.aegis/rules/)
aegis rule list               # List rules with Thompson Sampling & Wilson fitness scores
aegis rule create --type trap --id my-trap --title "Avoid Silent Catch"
aegis rule promote <id>       # Promote rule up lifecycle tiers
aegis rule demote <id>        # Demote rule down lifecycle tiers
aegis rule archive            # Archive decayed or quarantined rules
aegis rule clean              # Clean redundant or leaked rules

# 5. Skills, Handoffs & System Diagnostics
aegis skill list              # List horizontal agent skills in the SkillGraph
aegis skill inspect <id>      # Inspect skill metadata, consumes/produces, and slots
aegis skill slots             # Inspect .aegis/slots.yaml bindings
aegis handoff --from <s1> --to <s2> --type <ArtifactType> --payload <json>
aegis detect --fix            # Auto-detect project stack and provision polyglot AST drivers
aegis system doctor           # Health diagnostics and environment repair
aegis system hook             # Install or inspect git pre-commit hooks
```

---

## 4. Shell Completion

`aegis completion <shell>` generates a completion script for `bash`, `zsh`, or `fish` directly from the CLI parser:

| Shell | Add to | Line |
|:--|:--|:--|
| zsh | `~/.zshrc` (after `compinit`) | `eval "$(aegis completion zsh)"` |
| bash | `~/.bashrc` | `eval "$(aegis completion bash)"` |
| fish | `~/.config/fish/config.fish` | `aegis completion fish \| source` |

---

## 5. Starter Governance Rules

- `providence`: Grounds claims in codebase evidence and enforces read-before-write.
- `destructive-ops`: Mandates dry-runs and explicit confirmation before destructive mutations.
- `testing`: Enforces behavioral tests, sad-path coverage, and bans `ast.parse` test stubs.
- `cost-optimization`: Minimizes wasted tokens while preserving verification accuracy.
- `git-workflow`: Enforces safe branching, conventional commits, and `.gitignore` hygiene.

---

## Next Steps

- [Documentation Index](docs/index.md) — Full guide index by audience
- [MCP Gateway Guide](docs/guides/mcp_gateway.md) — 17 MCP tools, receipt security, and `RuleCache`
- [Rule Lifecycle Guide](docs/guides/rule_lifecycle.md) — Canonical rule types, `AegisYAML`, and Bayesian fitness
- [Verification Pipeline Guide](docs/guides/verification_pipeline.md) — Layer 1 AST checks, Layer 2 Arbiter, and Gate 4.5
- [CONTRIBUTING.md](CONTRIBUTING.md) — Development setup and PR review workflow

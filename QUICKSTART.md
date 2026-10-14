# Aegis Quickstart Guide

## What Aegis Does

Aegis (formerly Soma) is a governance framework for AI coding agents. It installs governance rules, provides a clean 5-noun-verb CLI and MCP server, and records evidence for adaptive rule management.

## Installation

Choose the option that matches your environment.

### Option 1: Install the CLI from PyPI

**Requires:** Python 3.9+ and `pip`.

```bash
pip install aegis-governance
```

### Option 2: Editable source install

**Requires:** Git, Python 3.9+, and `pip`.

```bash
git clone https://github.com/nseney1/Soma-Governance.git
cd Soma-Governance
pip install -e .
```

### Option 3: Install CLI and agent integration with Make

**Requires:** Git, Python 3.9+, `pip`, Bash, and GNU Make.

```bash
git clone https://github.com/nseney1/Soma-Governance.git
cd Soma-Governance
make install AEGIS_PLATFORM=gemini
```

> **PEP 668 (externally managed Python)?** Use an isolated virtual environment. If that is not possible, `pip install --user aegis-governance` may be appropriate for your system.

> **Tip:** for a user-wide CLI, `pipx install aegis-governance` keeps Aegis in its own environment and `pipx ensurepath` puts it on `PATH` for you.

### Verify the install

```bash
aegis --version
aegis system doctor
```

### `aegis: command not found`?

`pip install --user` puts `aegis` in your user scripts directory (`~/.local/bin` on Linux), which is often not on `PATH`. zsh in particular does not read `~/.profile`. Run `python3 -m aegis_cli system doctor` (use `python` on Windows): it prints the directory and the exact line for your shell. Typical fixes:

| Shell | Add to | Line |
|:--|:--|:--|
| zsh | `~/.zshrc` | `export PATH="$HOME/.local/bin:$PATH"` |
| bash | `~/.bashrc` (macOS: `~/.bash_profile`) | `export PATH="$HOME/.local/bin:$PATH"` |
| fish | `~/.config/fish/config.fish` (or `$XDG_CONFIG_HOME/fish/config.fish`) | `fish_add_path $HOME/.local/bin` |
| PowerShell | user `Path` variable | the `[Environment]::SetEnvironmentVariable(...)` line printed by `aegis system doctor` |

Open a new terminal afterwards. Until then, `python3 -m aegis_cli system doctor` works anywhere `aegis` would.

Prefer not to edit the file yourself? `python3 -m aegis_cli system doctor --fix-path` shows the exact file and line it would append (a dry run); add `--yes`, or answer `y` at its prompt, to apply it. It works for zsh, bash and fish only, marks the line `# added by aegis system doctor --fix-path`, does nothing if the line is already there, and records it so `install/uninstall.sh` removes exactly that line again. The installers themselves never edit your dotfiles, and `--fix-path` never touches a PowerShell `$PROFILE`.

If `git commit` fails with an aegis pre-commit message, the hook could not find `aegis` either: fix `PATH` as above, then re-run `aegis init` to refresh the hook.

## First Run with `aegis init`

`aegis init` detects Gemini, Claude Code, Cursor, and Copilot markers. If detection is ambiguous, select one of those platforms explicitly.

```bash
aegis init --platform gemini --yes
aegis status
aegis check
```

Useful setup flags verified by `aegis --help`:

```bash
aegis init --dry-run
aegis init --rules minimal --platform claude
aegis init --rules standard --mcp --platform cursor --yes
aegis init --rules full --platform copilot --force --yes
```

## Kiro and Generic MCP Installation

Kiro is supported by the Bash installer; it is not auto-detected by `aegis init`.

```bash
bash install/install.sh kiro --dry-run
bash install/install.sh kiro
```

For any MCP-compatible agent, generate a project-local `.mcp.json` with the Bash installer:

```bash
bash install/install.sh mcp --dry-run
bash install/install.sh mcp
```

## The 5 Clean Verbs

```bash
# Workspace initialization & platform setup
aegis init              # Auto-detect AI platform & configure governance

# Workspace status & metrics
aegis status            # View active rules, lifecycle distribution, and fitness stats

# Unified verification gate
aegis check             # Layer 1 deterministic AST verification
aegis check --hook      # Fast git pre-commit verification gate
aegis check --full      # Full verification with adversarial Layer 2 rebuttal
aegis check --release   # Release Gate 4.5 validation

# Rule lifecycle management
aegis rule list         # List rules with Bayesian fitness scores
aegis rule promote <id> # Promote rule up lifecycle tiers
aegis rule demote <id>  # Demote rule down lifecycle tiers
aegis rule archive      # Archive decayed or quarantined rules
aegis rule clean        # Clean redundant or leaked rules

# System diagnostics & driver management
aegis system doctor     # Health diagnostics and repair
aegis system hook       # Install or inspect git pre-commit hooks
aegis system drivers    # AST driver detection and provisioning
aegis system skills     # Inspect agent skills and slots
```

## Shell completion

`aegis completion <shell>` prints a completion script for `bash`, `zsh` or `fish`. It is generated from the CLI's own argument parser each time, so it always matches your installed version. Aegis never edits your dotfiles: add the line yourself, then open a new terminal.

| Shell | Add to | Line |
|:--|:--|:--|
| zsh | `~/.zshrc` (after `compinit`; oh-my-zsh runs it for you) | `eval "$(aegis completion zsh)"` |
| bash | `~/.bashrc` | `eval "$(aegis completion bash)"` |
| fish | `~/.config/fish/config.fish` | `aegis completion fish \| source` |

Without oh-my-zsh, put `autoload -Uz compinit && compinit` before the zsh line. To avoid running `aegis` at every shell start, save the script once instead, e.g. `aegis completion zsh > ~/.zfunc/_aegis` (with `~/.zfunc` on your `fpath`) or `aegis completion fish > ~/.config/fish/completions/aegis.fish`, and re-run it after upgrading Aegis.

## Make Targets

The repository Makefile provides `help`, `info`, `install`, `install-gemini`, `install-kiro`, `install-copilot`, `install-claude`, `install-mcp`, `install-windows`, `uninstall`, `doctor`, `validate`, `update`, `status`, and `test`. Run `make help` for descriptions.

## What the Standard Starter Rules Do

- `providence`: grounds claims in evidence and requires read-before-write.
- `destructive-ops`: requires safety gates for dangerous operations.
- `testing`: requires behavioral tests and meaningful failure coverage.
- `cost-optimization`: limits wasted tokens and compute without sacrificing correctness.
- `git-workflow`: defines safe, consistent Git practices.

## Next Steps

See [README.md](README.md) for MCP configuration, receipt usage, SDK examples, and architecture details.

# Aegis Guardrails: rules and an MCP server that keep AI coding agents on track

Aegis keeps Claude Code, Codex CLI and Antigravity on your project's rules. It gives each agent the rules for the files it is about to edit, then checks the change before commit and in CI.

[![PyPI](https://img.shields.io/pypi/v/aegis-guardrails)](https://pypi.org/project/aegis-guardrails/)
[![Python](https://img.shields.io/pypi/pyversions/aegis-guardrails)](https://pypi.org/project/aegis-guardrails/)
[![License: Apache 2.0](https://img.shields.io/badge/license-Apache--2.0-blue)](https://github.com/nseney1/Aegis-Guardrails/blob/main/LICENSE)
[![Runtime dependencies: 0](https://img.shields.io/badge/runtime%20dependencies-0-brightgreen)](https://github.com/nseney1/Aegis-Guardrails/blob/main/pyproject.toml)
[![CI](https://github.com/nseney1/Aegis-Guardrails/actions/workflows/validate.yml/badge.svg)](https://github.com/nseney1/Aegis-Guardrails/actions/workflows/validate.yml)

## What is Aegis?

Aegis is a Python package with no runtime dependencies that gives you a CLI (`aegis`) and an MCP server (`aegis-mcp`). Your rules are short markdown files in `.aegis/rules/`, committed with your code, and before an agent edits a file the `aegis_scan` tool hands it only the rules that apply to that file. `aegis check` then runs deterministic checks, including code patterns your rules ban, in a git pre-commit hook and in CI, and a local ledger records how each rule fared.

## Why guardrails for AI coding agents?

An instructions file (`AGENTS.md`, `CLAUDE.md`, `.cursorrules`) is a gentleman's agreement: nothing checks that the agent followed it. Agents break it in three ways:

- **They skip rules.** Under task pressure an agent follows the letter of a rule and misses its point.
- **They forget.** Long sessions compact their context, and every new session starts from zero.
- **They fail open.** A check that crashed, a tool that is missing or a rule that never loaded looks exactly like "no problem found".

In one coding session analyzed step by step, 749 of 1,339 agent steps (55.9%) were rework. The largest items were guessed UI controls (180 steps), the wrong Python environment (110) and a test that polled forever (103), and each became a rule Aegis ships. That is one session by one developer with no second rater; the sources and caveats are in [Why Aegis is built this way](https://github.com/nseney1/Aegis-Guardrails/blob/main/docs/why-aegis.md).

## Quick start

You need Python 3.9 or newer and a git repository.

```bash
pip install aegis-guardrails
cd my-app
aegis init --host claude-code,codex-cli   # or --host auto: every supported host found on this machine
```

If pip stops with `externally-managed-environment` (PEP 668, as many Linux distributions and Homebrew Python do), run `pipx install aegis-guardrails` or install into a virtual environment. If your shell then says `aegis: command not found`, run `python3 -m aegis_cli <command>` instead (`python -m aegis_cli` on Windows); `aegis init` and `aegis doctor` print the PATH fix for your shell.

`aegis init` prints its plan and asks before it writes anything. After you confirm, it reports (absolute paths shortened to `~`):

```text
  ✅ .aegis/config.json: created (hosts: codex-cli, claude-code)
  ✅ .aegis/.gitignore: created
  Starter rules (preset=standard) in .aegis/rules/personas/:
    ✅ providence
    ✅ destructive-ops
    ✅ testing
    ✅ cost-optimization
    ✅ git-workflow
    They apply to no file until you set their target_paths (aegis status lists them).
  ✅ AGENTS.md: created
  ✅ ~/.aegis/workspaces.json: added
  ✅ codex-cli: registered (codex mcp add aegis --env AEGIS_CLIENT=codex-cli -- ~/.local/bin/aegis-mcp)
  ✅ claude-code: registered (claude mcp add --scope user aegis -e AEGIS_CLIENT=claude-code -- ~/.local/bin/aegis-mcp)
    🪝 Pre-commit hook installed (~/code/my-app/.git/hooks/pre-commit)
```

Now add a rule that agents will see and `aegis check` will enforce. Save this as `.aegis/rules/invariants/no-eval.md`:

```markdown
---
id: no-eval
type: invariant
domain: security
enforcement: gate
hypothesis: Agents reach for eval() to parse input
target_paths:
  - "**/*.py"
forbid_ast:
  calls: [eval, exec]
---
Never call `eval` or `exec` on data. Parse it with `json.loads` or `ast.literal_eval`.
```

An agent that calls `aegis_scan` before editing `app.py` gets this rule (`aegis scan app.py` shows the same thing in a shell). If the change calls `eval` anyway, the check fails, and so does `git commit`, because the pre-commit hook runs the same check. With no file arguments, `aegis check` looks only at tracked files: your changes and staged files (on a clean tree, what the branch adds to its base). It skips untracked files, so `git add` a new file first, or name it: `aegis check app.py`.

```text
$ git add app.py
$ aegis check
checkpoint: all checks passed
🔴 forbid_ast:no-eval: app.py — Forbidden call 'eval' matched rule forbid_ast.calls
Layer 1: 1/3 FAILED — forbid_ast:no-eval
```

Commit `.aegis/` and `AGENTS.md`; the local ledger in `.aegis/state/` is git-ignored. Run `aegis doctor` to see, for each host, whether the server is registered, whether the bootstrap reaches the agent, and which enforcement tier is in force. Finally, make CI the floor, since `git commit --no-verify` skips the local hook:

```yaml
- uses: actions/checkout@v7
  with:
    fetch-depth: 0          # aegis check diffs the pull request against its base branch
- uses: actions/setup-python@v7
  with:
    python-version: "3.12"
- run: pip install aegis-guardrails && aegis check
```

## Works with your agents

| Host | How `aegis init --host` wires it | Instructions the agent reads |
|---|---|---|
| **Claude Code** (`claude-code`) | `claude mcp add --scope user aegis` | `AGENTS.md`, but only when there is no `CLAUDE.md`. If the repo has one, `init` adds an `@AGENTS.md` block to it; it never creates one. |
| **Codex CLI** (`codex-cli`) | `codex mcp add aegis` | `AGENTS.md` (Codex truncates it past 32 KiB) |
| **Antigravity** (`antigravity`: app, IDE and `agy`) | an `aegis` entry in `~/.gemini/config/mcp_config.json` | `AGENTS.md` (24,000 bytes per file). Antigravity tells the server no workspace, so run `aegis init` once per repo on each machine. |
| **Gemini CLI** | Retired: Google refuses the client for individual Code Assist accounts, and Antigravity is the Gemini-family host. `aegis init --host gemini-cli` exits with status 2 and points you to `--host antigravity`. | — |

On every host the enforcement is the same today: advisory rules through the bootstrap and `aegis_scan`, the git pre-commit hook as the local floor, and CI as the authority. Per-host agent hooks (Claude Code's can block an edit; Codex's fail open) are planned for v4.1. Claude Desktop chat sessions are recognized but not registered. Every host runs `aegis-mcp` with your own user's permissions.

## How it works

1. `aegis init` writes a 572-byte bootstrap block into `AGENTS.md` (no rule text) and registers the `aegis` MCP server with your hosts. The server repeats the same guidance in its MCP instructions, which editing files cannot remove.
2. Before editing, the agent calls `aegis_scan` with the files it will change. It gets only the rules whose `target_paths` match: three at most, gates and invariants first (two of them at most), within a 2,000-token budget by default.
3. The agent edits, runs its tests and reports with `aegis_report_outcome`.
4. `aegis check` runs Layer 1 (deterministic checks, including every `forbid_ast` ban) in the pre-commit hook and in CI. `aegis check --full --plan "..." --llm-cmd 'claude -p'` adds an optional model review.
5. Outcomes go to an append-only local ledger. `aegis sync` turns them into fitness scores and suggests promotions, which a person applies and commits.

The full story, with diagrams, is in [How Aegis works](https://github.com/nseney1/Aegis-Guardrails/blob/main/docs/how-it-works.md). Every command, flag and MCP tool schema is in the generated [reference](https://github.com/nseney1/Aegis-Guardrails/blob/main/docs/reference.md).

## What's included

- **A CLI** with 10 commands (`init`, `uninstall`, `doctor`, `migrate`, `check`, `scan`, `status`, `rule`, `sync`, `hook`) and **an MCP server** with 4 tools (`aegis_scan`, `aegis_report_outcome`, `aegis_create_rule`, `aegis_list_rules`).
- **12 starter [rules](https://github.com/nseney1/Aegis-Guardrails/tree/main/rules)**: grounding claims in the code before acting, dry runs before destructive commands, behavioral tests, test-first development, git hygiene and more. `aegis init --rules minimal|standard|full` seeds 2, 5 or all 12. They apply to no file until you set their `target_paths`.
- **15 [skills](https://github.com/nseney1/Aegis-Guardrails/tree/main/skills)**, `SKILL.md` playbooks for reviews, audits, incident debugging, refactoring and more. Copy the ones you want into your host's skills folder; `aegis init --skills` is planned for v4.1.
- **AST checks for Python** (in process), plus drivers that ship in the wheel for Rust, TypeScript/JavaScript (needs `node`) and Go (needs `go`); `aegis init` turns them on for the languages it detects.
- **A Python SDK facade**, `aegis_sdk.Governance`, for tools that read rules and fitness.

## Rules that earn their place

A rule starts as a **trap** ("agents keep doing X here"). With evidence it can be promoted to an **invariant** (must always hold) and then to a **gate**. Invariants and gates are served before advisory rules in every scan, and a rule with `forbid_ast` patterns is enforced by `aegis check` whatever its type. `aegis sync` suggests a promotion when a rule has at least 20 verdicts in the ledger, the 90% Wilson lower bound of its true-positive rate (decayed by age) is at least 0.85, and it is at least 30 days old. It suggests demoting or archiving a rule that mostly fires wrongly. Nothing moves until a person runs `aegis sync --apply` or `aegis rule promote`, and that change goes through review like any other commit. Aegis never rewrites a rule file on its own.

Be clear about what the score means today: every rule that matched a change's files shares that check's pass or fail, and agent self-reports count too. So fitness ranks which rules agents see first; it does not prove a rule helped. A per-rule credit model, built on evidence the agent cannot forge and shown with its sample size, is planned for v4.3, together with CI-witnessed outcomes, rule integrity checked through git, regression discipline, a calibrated Layer-2 arbiter, security scanners with SARIF output and a loop for human corrections. See the roadmap in [Why Aegis is built this way](https://github.com/nseney1/Aegis-Guardrails/blob/main/docs/why-aegis.md).

## What Aegis does not do

Aegis does not claim enforcement it lacks. `aegis doctor` reports these tiers, in these words:

| Tier | Mechanism | What gets past it |
|---|---|---|
| Advisory | AGENTS.md bootstrap, MCP instructions, JIT rules | any agent: it is guidance |
| Best-effort | per-host pre-tool hooks | planned for v4.1: Claude Code's can block, Codex's fail open |
| Local floor | git pre-commit runs aegis check --hook (--no-verify bypasses it) | anyone using `git commit --no-verify` |
| Authoritative | CI runs aegis check on the exact SHA; a human merges | a pull request that also weakens the rules or the CI workflow it is checked with, unless a person reviews those changes |

**CI is the floor.** Put `aegis check` in CI and require it before merge: it is the strongest tier, but not tamper-proof. CI checks a pull request against the rules in the pull request itself, so a pull request that deletes a rule and breaks it passes. Review every change under `.aegis/` and to your CI workflow like code; protecting the reviewed rules from the change they judge is planned for v4.3.

- It does not force an agent to scan. Hosts are prompted to, and `aegis status --compliance` measures each host's scan-before-edit rate.
- It does not sandbox agents or sign anything. Rule files are protected only by your review of the pull requests that change them.
- It sends nothing anywhere unless you ask: see the FAQ below.

## FAQ

**How do I add guardrails to Claude Code?** Run `aegis init --host claude-code` in the repo. It registers the server at user scope, so every Claude Code session can use it, and the bootstrap in `AGENTS.md` tells the agent to call `aegis_scan`. If the repo already has a `CLAUDE.md`, `init` adds an `@AGENTS.md` import block to it, because Claude Code skips `AGENTS.md` when a `CLAUDE.md` exists.

**How do I add guardrails to Codex CLI?** Run `aegis init --host codex-cli`. It runs `codex mcp add aegis`, and Codex reads the bootstrap from `AGENTS.md` natively.

**What is AGENTS.md?** A plain markdown instructions file in the repository root that coding agents such as Codex CLI, Antigravity and Claude Code read at the start of a session. Aegis writes only one small marked block into it. Your rules stay in `.aegis/rules/` and reach the agent through `aegis_scan`, so they never bloat the file.

**Does Aegis send my code anywhere?** No. The CLI and the MCP server make no network calls, and the ledger stays in `.aegis/state/` on your machine. The exception is Layer 2: `aegis check --full` pipes the change to the model command you name with `--llm-cmd`, for example `claude -p`. `aegis init --host` also runs your hosts' own CLIs to register the server.

**I used Aegis 3.x. How do I upgrade?** Run `aegis migrate` to see the plan, then `aegis migrate --apply` (it backs up every file it changes). Then run `aegis doctor --fix` to remove stale v3 MCP entries (such as `soma`) and legacy rule blocks in instruction files, again backing up each file first.

## Documentation, contributing, security, license

- [How Aegis works](https://github.com/nseney1/Aegis-Guardrails/blob/main/docs/how-it-works.md): the loop, rules, MCP delivery, checks, the ledger, hosts and enforcement.
- [Why Aegis is built this way](https://github.com/nseney1/Aegis-Guardrails/blob/main/docs/why-aegis.md): the evidence, what went wrong in v3, the v4.3 roadmap.
- [Reference](https://github.com/nseney1/Aegis-Guardrails/blob/main/docs/reference.md): every command, flag and MCP tool, generated from the code.
- [Plan of record (ADR 0005)](https://github.com/nseney1/Aegis-Guardrails/blob/main/docs/adr/0005-v4-plan-of-record.md) and the [changelog](https://github.com/nseney1/Aegis-Guardrails/blob/main/CHANGELOG.md).
- [Contributing](https://github.com/nseney1/Aegis-Guardrails/blob/main/CONTRIBUTING.md) and [privacy](https://github.com/nseney1/Aegis-Guardrails/blob/main/PRIVACY.md).
- Security issues: report them privately as described in [SECURITY.md](SECURITY.md).

Apache 2.0. Copyright 2026 Nicholas Seney. See [LICENSE](https://github.com/nseney1/Aegis-Guardrails/blob/main/LICENSE) and [NOTICE](https://github.com/nseney1/Aegis-Guardrails/blob/main/NOTICE).

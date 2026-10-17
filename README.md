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

If pip stops with `externally-managed-environment` (PEP 668, as many Linux distributions and Homebrew Python do), run `pipx install aegis-guardrails` or install into a virtual environment. If your shell then says `aegis: command not found`, run `pipx ensurepath` after a pipx install, activate the virtual environment, or run the script by its full path (on Linux `~/.local/bin/aegis` after `pip install --user`); `aegis init` and `aegis doctor` print the PATH fix for your shell. Do not fall back to `python3 -m aegis_cli` inside a repository: `-m` imports from the current directory first.

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
  Active rule in .aegis/rules/invariants/:
    ✅ no-eval: bans eval() and exec() in **/*.py, methods named eval or exec included (df.eval(), model.eval()); aegis check and the pre-commit hook enforce it
    Next: add a rule for your own code with aegis rule create (aegis rule create --help)
  ✅ AGENTS.md: created
  ✅ ~/.aegis/workspaces.json: added
  ✅ codex-cli: registered (codex mcp add aegis --env AEGIS_CLIENT=codex-cli -- ~/.local/bin/aegis-mcp)
  ✅ claude-code: registered (claude mcp add --scope user aegis -e AEGIS_CLIENT=claude-code -- ~/.local/bin/aegis-mcp)
    🪝 Pre-commit hook installed (~/code/my-app/.git/hooks/pre-commit)
```

`init` seeds one rule that is active from day one: `.aegis/rules/invariants/no-eval.md` (leave it out with `--rules none-active`). It matches by call name, so a method called `eval` or `exec` (pandas `df.eval()`, PyTorch `model.eval()`, SQLModel `session.exec()`) fails the check too; delete the file, or use `none-active`, if your code relies on those. Here is what it looks like, as a template for your own (`aegis rule create` writes one for you):

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

An agent that calls `aegis_scan` before editing `app.py` gets this rule (`aegis scan app.py` shows the same thing in a shell). If the change calls `eval` anyway, the check fails, and so does `git commit`, because the pre-commit hook runs the same check on the staged content, which is what the commit records. If the repository already has a shell pre-commit hook, the Aegis block goes first in it, after the old file is copied to `~/.aegis/backups/`; a hook written in another language stops `aegis init` before it writes anything, and `aegis hook install --force` replaces it (keeping the copy). With no file arguments, `aegis check` looks only at tracked files: your changes and staged files (on a clean tree, what the branch adds to its base). It skips untracked files, so `git add` a new file first, or name it: `aegis check app.py`.

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
| **Kiro** (`kiro`, experimental: IDE and CLI) | an `aegis` entry in `~/.kiro/settings/mcp.json` | `AGENTS.md` |
| **Gemini CLI** | Retired: Google refuses the client for individual Code Assist accounts, and Antigravity is the Gemini-family host. `aegis init --host gemini-cli` exits with status 2 and points you to `--host antigravity`. | — |

On every host, rules are advisory through the bootstrap and `aegis_scan`, the git pre-commit hook is the local floor, and CI is the authority. `aegis hook install --host <host>` adds a pre-tool hook that stops destructive commands and edits to files nobody scanned first, with a different strength on each host (the tier table under "What Aegis does not do" lists them; `aegis doctor` shows what is installed). It writes your user's host settings; `--scope project` writes the repository's instead, which your teammates' hosts will run. Claude Desktop chat sessions are recognized but not registered. Every host runs `aegis-mcp` and the hooks with your own user's permissions.

## How it works

1. `aegis init` writes a 572-byte bootstrap block into `AGENTS.md` (no rule text) and registers the `aegis` MCP server with your hosts. The server repeats the same guidance in its MCP instructions, which editing files cannot remove.
2. Before editing, the agent calls `aegis_scan` with the files it will change. It gets only the rules whose `target_paths` match: three at most, gates and invariants first (two of them at most), within a 2,000-token budget by default.
3. The agent edits, runs its tests and reports with `aegis_report_outcome`. `aegis check --record --tests` runs them on a snapshot of the exact tree and records the result as a label; a report with no such row is kept as `claimed` and earns no rule credit.
4. `aegis check` runs Layer 1 (deterministic checks, including every `forbid_ast` ban) in the pre-commit hook and in CI. `aegis check --full --plan "..." --llm-cmd 'claude -p'` adds an optional model review.
5. Outcomes go to an append-only local ledger. `aegis sync` turns them into fitness scores and suggests promotions, which a person applies and commits.

The full story, with diagrams, is in [How Aegis works](https://github.com/nseney1/Aegis-Guardrails/blob/main/docs/how-it-works.md). Every command, flag and MCP tool schema is in the generated [reference](https://github.com/nseney1/Aegis-Guardrails/blob/main/docs/reference.md).

## What's included

- **A CLI** with 15 commands (`init`, `uninstall`, `doctor`, `migrate`, `check`, `approve`, `scan`, `status`, `rule`, `sync`, `hook`, `team`, `skills`, `benchmark`, `package`) and **an MCP server** with 5 tools (`aegis_scan`, `aegis_report_outcome`, `aegis_create_rule`, `aegis_list_rules`, `aegis_capture_insight`).
- **Host surfaces.** A host is the config plane its apps share: `codex-cli` covers the Codex CLI, IDE extension and ChatGPT desktop app; `claude-code` covers the CLI, IDE extensions and the desktop app's Code tab; `antigravity` the app, IDE and `agy`; `kiro` (experimental) the Kiro IDE and CLI. `--host` accepts the surface names too (for example `codex-app`, `kiro-ide`), and `--host auto` finds apps by their config directories and app bundles as well as CLIs on PATH. `aegis doctor` warns when a host reads the `AGENTS.md` bootstrap but has no Aegis MCP registration.
- **12 starter [rules](https://github.com/nseney1/Aegis-Guardrails/tree/main/rules)**: grounding claims in the code before acting, dry runs before destructive commands, behavioral tests, test-first development, git hygiene and more. `aegis init --rules minimal|standard|full` seeds 2, 5 or all 12. They apply to no file until you set their `target_paths`.
- **15 [skills](https://github.com/nseney1/Aegis-Guardrails/tree/main/skills)**, `SKILL.md` playbooks for reviews, audits, incident debugging, refactoring and more. `aegis skills sync` (or `aegis init --skills`) copies them into `.claude/skills/` for Claude Code and `.agents/skills/` for Codex CLI and Antigravity, and later runs replace only Aegis's own unedited copies.
- **AST checks for Python** (in process), plus drivers that ship in the wheel for Rust, TypeScript/JavaScript (needs `node`) and Go (needs `go`); `aegis init` turns them on for the languages it detects.
- **A Python SDK facade**, `aegis_sdk.Governance`, for tools that read rules and fitness.

## Agent teams

When several agents work in parallel, each in its own worktree and branch (a lane), whoever dispatches them can declare each lane's paths: `aegis team claim docs --paths 'docs/**' README.md`. The lease is a git ref every worktree sees, and a claim whose paths may overlap another live lane's is refused. A lease is cooperative conflict input, not a lock, not an identity and not proof that an agent is still working.

The gate is `aegis check --lane docs`: every path the lane changed since its merge base must be inside its paths, and no Python test may disappear or gain a skip. Any finding fails, and the reviewer decides with the findings in view. With the lease or `--paths` the result is self-attested, because the lane can write those; with `--base-policy` the paths come from `.aegis/team.json` on the base branch, and the result is witnessed. As a CI job it is advisory in v4.1. `aegis team metrics` counts denied claims and conflicting merges, which decide whether leases earn their place. Details are in [How Aegis works](https://github.com/nseney1/Aegis-Guardrails/blob/main/docs/how-it-works.md).

## Rules that earn their place

A rule starts as a **trap** ("agents keep doing X here"). With evidence it can be promoted to an **invariant** (must always hold) and then to a **gate**. Invariants and gates are served before advisory rules in every scan, and a rule with `forbid_ast` patterns is enforced by `aegis check` whatever its type. `aegis sync` computes four sample-size states (`untestable`, `insufficient (n=K)` with no precision number shown until `n >= 25`, `inconclusive`, and `decided`) over CI-confirmed checks, git detector replay (`caught` vs `leaked`), and human-adjudicated labels, with session-count decay (`w = 2^(-delta / H)`) over heartbeat-alive eligible sessions. Inline `# aegis: allow` comments record `contested` overrides (never false positives) and flag rules with high override rates for review. Nothing moves until a person runs `aegis sync --apply`, `aegis sync --pr` (which opens a human-reviewed PR with up to 3 sampled examples per rule, never auto-merged), or `aegis rule promote`. Aegis never rewrites a rule file on its own.

Be clear about what the score means today: every rule that matched a change's files shares that check's pass or fail. An agent's report without a recorded check counts for nothing (v4.3), and agent self-reports alone can never promote a rule to a gate. `aegis check --ci` checks rule weakening, fail-to-pass regression discipline on bug-fix commits, PR-native `--format github|sarif` output, and opt-in `--coverage` / `--perf` gates; `aegis rule insight` (`add`, `review`, `enable`) plus `aegis_capture_insight` close the loop from human corrections in `~/.aegis/insights/` to draft proposals in `.aegis/proposals/`; and the Layer-2 arbiter logs falsifiable predictions for `aegis check --calibration`. Details are in [Why Aegis is built this way](https://github.com/nseney1/Aegis-Guardrails/blob/main/docs/why-aegis.md).

## What Aegis does not do

Aegis does not claim enforcement it lacks. `aegis doctor` reports these tiers, in these words:

| Tier | Mechanism | What gets past it |
|---|---|---|
| Advisory | AGENTS.md bootstrap, MCP instructions, JIT rules | any agent: it is guidance |
| Best-effort | per-host pre-tool hooks | everything on a host without `aegis hook install --host`, a Codex hook you have not trusted in `/hooks`, edits made through shell commands, and any call when Aegis itself errors: the hooks fail open. Installed, `aegis doctor` reports Claude Code: blocking (documented; fails open on error) [DOC] (exit 2, documented by Anthropic); Codex CLI: blocking once trusted in /hooks (documented; fails open) [DOC] (exit 2, documented by OpenAI); Antigravity: blocks destructive commands (live); scan gate records only [LIVE] (exit 1, verified live). Antigravity hooks are unavailable on Windows |
| Local floor | git pre-commit runs aegis check --hook (--no-verify bypasses it) | anyone using `git commit --no-verify` |
| Authoritative | CI runs aegis check on the exact SHA; a human merges | a pull request that also weakens the rules or the CI workflow it is checked with, unless `aegis check --ci` runs as a required check and a person reviews or signs (`aegis approve`) those changes. `aegis doctor` prints the trust tier (A, B or C) GitHub actually enforces |

**CI is the floor.** Agent hooks are guardrails, not a security boundary. Put `aegis check` in CI and require it before merge: it is the strongest tier, but not tamper-proof. Plain `aegis check` enforces the rules in the pull request itself, so a pull request that deletes a rule and breaks it passes it. `aegis check --ci` catches that: it flags every way a gate or invariant binds less than on the base branch, and passes such a change only with a signed `aegis approve` commit. Add it to your pull-request workflow as a required check. `aegis_scan` already serves gates and invariants from the reviewed base commit, so a branch-local edit never binds the agent. Review every change under `.aegis/` and to your CI workflow like code.

- It does not force every agent to scan. With the hook installed, Claude Code (and Codex, once trusted) blocks an edit to a file no scan covered within the scan window (an hour by default); Antigravity only records it, and edits made through shell commands pass everywhere. `aegis status --compliance` measures each host's scan-before-edit rate.
- It does not sandbox agents or sign anything itself. Rule files are protected by your review of the pull requests that change them, by `aegis check --ci` when CI requires it, and by the signatures `aegis approve` asks your own key for.
- It sends nothing anywhere unless you ask: see the FAQ below.

## FAQ

**How do I add guardrails to Claude Code?** Run `aegis init --host claude-code` in the repo. It registers the server at user scope, so every Claude Code session can use it, and the bootstrap in `AGENTS.md` tells the agent to call `aegis_scan`. If the repo already has a `CLAUDE.md`, `init` adds an `@AGENTS.md` import block to it, because Claude Code skips `AGENTS.md` when a `CLAUDE.md` exists. `aegis hook install --host claude-code` then adds the pre-tool hook that blocks unscanned edits and destructive commands.

**How do I add guardrails to Codex CLI?** Run `aegis init --host codex-cli`. It runs `codex mcp add aegis`, and Codex reads the bootstrap from `AGENTS.md` natively. For the pre-tool hook, run `aegis hook install --host codex-cli`, then trust the hook in Codex's `/hooks` screen: until you do, Codex skips it without a word.

**What is AGENTS.md?** A plain markdown instructions file in the repository root that coding agents such as Codex CLI, Antigravity and Claude Code read at the start of a session. Aegis writes only one small marked block into it. Your rules stay in `.aegis/rules/` and reach the agent through `aegis_scan`, so they never bloat the file.

**Does Aegis send my code anywhere?** No. The CLI and the MCP server make no network calls, and the ledger stays in `.aegis/state/` on your machine. The exception is Layer 2: `aegis check --full` pipes the change to the model command you name with `--llm-cmd`, for example `claude -p`. `aegis init --host` also runs your hosts' own CLIs to register the server.

**I used Aegis 3.x. How do I upgrade?** Run `aegis migrate` to see the plan, then `aegis migrate --apply` (it backs up every file it changes). Until you do, `aegis status`, `aegis scan` and `aegis sync` refuse to run in that repository and name the v3 files v4 does not read, `aegis check` warns and still runs, and `aegis init` refuses while `.soma/` holds rules. Then run `aegis init --host <your hosts>` (for example `--host claude-code,codex-cli`, or `--host auto`) to register the MCP server and write the `AGENTS.md` bootstrap. Last, run `aegis doctor --fix` to remove stale v3 MCP entries (such as `soma`) and legacy rule blocks in instruction files, again backing up each file first. The [changelog](https://github.com/nseney1/Aegis-Guardrails/blob/main/CHANGELOG.md#upgrading-from-3x) lists what `aegis migrate` converts.

## Documentation, contributing, security, license

- [How Aegis works](https://github.com/nseney1/Aegis-Guardrails/blob/main/docs/how-it-works.md): the loop, rules, MCP delivery, checks, the ledger, hosts and enforcement.
- [Why Aegis is built this way](https://github.com/nseney1/Aegis-Guardrails/blob/main/docs/why-aegis.md): the evidence, what went wrong in v3, and the v4.3 trust and evidence model.
- [Reference](https://github.com/nseney1/Aegis-Guardrails/blob/main/docs/reference.md): every command, flag and MCP tool, generated from the code.
- Plan of record (ADR 0005, ADR 0006) and the [changelog](https://github.com/nseney1/Aegis-Guardrails/blob/main/CHANGELOG.md).
- [Contributing](https://github.com/nseney1/Aegis-Guardrails/blob/main/CONTRIBUTING.md) and [privacy](https://github.com/nseney1/Aegis-Guardrails/blob/main/PRIVACY.md).
- Security issues: report them privately as described in [SECURITY.md](SECURITY.md).

Apache 2.0. Copyright 2026 Nicholas Seney. See [LICENSE](https://github.com/nseney1/Aegis-Guardrails/blob/main/LICENSE) and [NOTICE](https://github.com/nseney1/Aegis-Guardrails/blob/main/NOTICE).

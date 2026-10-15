# Spec: mix-and-match hosts (any vendor × any surface)

- **Status**: v2, **accepted** with ADR 0005 (2026-10-15). It incorporates the author's H1–H8 answers, the adversarial review (feasibility, red team, scope), and the refactor sweep's layout consolidation. This spec is the build sheet for ADR 0005 §6 step 3 (v4.0-c).
- **Goal**: Aegis works for any combination of agent hosts on the same repos:
  - CLI only (Codex CLI + Claude Code CLI + `agy`);
  - IDE or desktop only;
  - mixed.

  The author runs Codex CLI (OpenAI), the Claude Code desktop app (Anthropic) and Antigravity (Google) on the same repos, often at the same time.
- **Evidence**: verified 2026-10-15 on Linux with sandboxed config dirs, probe MCP servers and two live probes:
  - codex-cli 0.162.1;
  - Claude Code 2.1.287 CLI / 2.1.295 desktop;
  - `agy` 1.2.16;
  - Antigravity app 2.19.1.

  Unverified items are marked (U).

## 1. Problem (v3.3 / Wave 1)

- **One platform per run, keyed by vendor.** `gemini` means Antigravity *and* Gemini CLI, and `claude` means Claude Code *and* Claude Desktop. Unknown clients default to `gemini`.
- **Rule text is inlined into instruction files.** A project `CLAUDE.md` gets 33.7 KB. That truncates silently on Codex (32 KiB) and Antigravity (24,000 B per file). There is no `AGENTS.md` support.
- **Every writer registers both `aegis` and `soma`**, so hosts load two toolsets.
- **The server takes `AEGIS_WORKSPACE` or the cwd.** When the cwd is `$HOME`, it creates `~/.aegis/rules` and governs the home directory with zero rules.

## 2. Verified host facts

| Host | clientInfo.name | Roots | Spawn cwd / env | Instructions read | MCP registration |
|---|---|---|---|---|---|
| **codex-cli** | `codex-mcp-client` | none (`[]`) | thread cwd; env allowlist | `AGENTS.md` chain (honoured even in untrusted repos, verified live); 32 KiB cap, silent truncation | `codex mcp add aegis --env K=V -- CMD` (user TOML; Aegis never writes TOML) |
| **claude-code** | `claude-code` | yes | launch dir; `CLAUDE_PROJECT_DIR` | `CLAUDE.md` hierarchy; reads `AGENTS.md` only if no `CLAUDE.md` exists (≥ 2.1.277) | `claude mcp add --scope user aegis -e K=V -- CMD` |
| **claude-desktop** | `local-agent-mode-<key>` | union of open sessions | `$HOME`; minimal env | n/a | identity only (H4): Aegis no longer registers here |
| **antigravity** (app, IDE, `agy`) | `antigravity-client` | none / `[]` (verified live) | launch dir; full env; eager spawn at startup | `AGENTS.md`, `GEMINI.md`; 24,000 B per file | `~/.gemini/config/mcp_config.json` (JSON, no `${}` expansion) |
| **gemini-cli** (later) | `gemini-cli-mcp-client` | yes | config cwd | `GEMINI.md` only, unless `context.fileName` lists `AGENTS.md` | `gemini mcp add -s user` |

Every host runs `aegis-mcp` unsandboxed with the user's privileges, so Aegis's own confinement is the only boundary.

Codex also sends a per-call `_meta.x-codex-turn-metadata.workspaces` (verified live). It is host-attested, because the model cannot set it.

## 3. Design

### 3.1 Vocabulary and ids (H1: hard cut, no aliases)

- Host ids are `codex-cli`, `claude-code`, `claude-desktop` (identity only), `antigravity` and `gemini-cli` (table row, Phase 2).
- `--platform gemini|claude|cursor|copilot|kiro` and `aegis install` are **removed**. The CLI rejects them with a message naming the replacement (`aegis init --host …`).

### 3.2 Planes

| Plane | Contents |
|---|---|
| **Repo** (committed) | `.aegis/config.json`; `.aegis/rules/`; `.aegis/.gitignore` (`state/`); one managed bootstrap block in root `AGENTS.md`; an `@AGENTS.md` shim block in `CLAUDE.md` **only if a CLAUDE.md already exists**. **No committed MCP files** (review: a committed `.mcp.json` would run whatever command a PR puts there). |
| **User** (per developer) | MCP registrations made through each host's native CLI or JSON file, with an absolute command path and explicit env; `~/.aegis/workspaces.json` (the governed-workspace registry, AD-4); `~/.aegis/rules/` (the read-only user rule layer, H8). Global instruction files get **nothing**. |
| **Runtime** (`aegis-mcp`) | client identity, workspace binding, telemetry attribution |

### 3.3 Host table (data, not classes)

`aegis_cli/hosts.py` holds one `HostSpec` row per host:

- `id` and `client_names` (the exact clientInfo match);
- `detect` (binary names, user dirs);
- `instructions` (`agents_md` | `agents_md_unless_claude_md` | `gemini_md`) and `budget_bytes`;
- `register` (`native_cli` argv template | `json_file` path + key);
- `slot_profile`.

Three generic functions act on the table:

1. **`write_managed_block`** (§3.4).
2. **`register_mcp(host)`**:
   - Native CLI first.
   - Otherwise a JSON merge that is atomic, preserves other keys, and **refuses on unparseable input** (JSONC, BOM or trailing commas get a clear error and no write).
   - Registrations always use the single name `aegis`.
3. **`unregister_mcp(host)`**: the inverse; it removes only the `aegis` (and legacy `soma`) entries.

`init --host a,b|auto` selects hosts. Detection only *proposes*: it never writes for an undetected or unselected host. The selection is stored in `.aegis/config.json` under `hosts`.

### 3.4 Instructions: one bootstrap (H2, AD-9)

- **The bootstrap block** is about 500 B, with no rule bodies:
  - call `aegis_scan` with the files you plan to edit, before editing;
  - call `aegis_report_outcome` after verifying;
  - without MCP, use `aegis scan FILE…`;
  - rules live in `.aegis/rules/`.
- **The same text** is returned as the MCP `initialize` `instructions` string. Codex and Claude feed it to the model, and editing files cannot remove it.
- **Claude shim**: if a `CLAUDE.md` exists at the repo root, add a managed block containing `@AGENTS.md`. **Never create a CLAUDE.md**, because that disables Claude Code's native AGENTS.md reading.
- **Markers**: `<!-- aegis:begin id=<id> v=1 sha=<12hex> -->` … `<!-- aegis:end id=<id> -->`. The writer:
  - touches only its own id;
  - refuses when the sha shows the block was hand-edited (`--force` overrides);
  - is idempotent and preserves CRLF;
  - **never writes through a symlink**, refusing instead (red team: a symlinked AGENTS.md could redirect the write anywhere);
  - writes atomically.
- **Legacy blocks** (`SOMA:START/END`, `AEGIS:START/END`) are reported by `doctor` and removed only by `doctor --fix`, after a backup.
- **No projection ledger is committed** (red team: a committed `projections.json` could name arbitrary files for uninstall to delete). Uninstall removes only marker-delimited blocks it can recognise.

### 3.5 Runtime identity

1. The registration env `AEGIS_CLIENT` wins, because the installer writes it and the model cannot set it.
2. Otherwise the exact clientInfo table from §2 (prefix match only for `local-agent-mode-`).
3. Otherwise `generic`. **Never default to `gemini`.**

`client_host`, `client_name` and `client_version` are **server-owned keys**. A tool argument of the same name is ignored (added to `SERVER_OWNED_KEYS`).

### 3.6 Workspace binding (AD-4)

`WorkspaceBinding{root, source, confidence}`. The first match wins:

1. **Operator pin**: `AEGIS_WORKSPACE` in the registration env. It is strict: if it does not resolve to a directory containing `.aegis/`, the server starts in an error state and every tool call returns that error.
2. **Host-attested**, in this order:
   - the Codex `_meta.x-codex-turn-metadata.workspaces` entries;
   - `CLAUDE_PROJECT_DIR`;
   - MCP roots (requested once after `initialized`, re-requested on `notifications/roots/list_changed`).

   Each candidate must contain `.aegis/`. With several candidates (for example the Claude Desktop union), choose the one that contains the call's `files`.
3. **Registry**: `~/.aegis/workspaces.json`, written by `aegis init`. A call's `files` can only *select among* registered roots; they never introduce a new one.
4. **Bounded walk-up** from the server cwd. It stops at the git toplevel (found through `gitsafe`) and never goes above it.

**Denylist**: `$HOME`, `/` and the filesystem root are never a workspace. There is **no model-supplied `workspace` argument** (red team blocker: a prompt-injected model could point Aegis at another repo).

If nothing resolves, the server stays up and answers "not governed here". `aegis_scan` then serves the H8 read-only user layer (`~/.aegis/rules`) with no ledger writes. It never creates `~/.aegis/rules`.

The binding is cached per (root, source). Server state (RuleCache) is keyed by root.

### 3.7 gitsafe (red team blocker)

Every git subprocess goes through `aegis_core.gitsafe.run(args, cwd)`:

- It uses `git -c core.fsmonitor=false -c core.hooksPath=/dev/null -c protocol.allow=never -c core.sshCommand=false` (plus `-c credential.helper=` for safety).
- It sets env `GIT_TERMINAL_PROMPT=0`, `GIT_OPTIONAL_LOCKS=0`, `GIT_NO_REPLACE_OBJECTS=1` and `LC_ALL=C`, with a timeout and no shell. It keeps the admin-owned system config (Git for Windows stores `core.autocrlf` there); only repository-controlled config (local and worktree scopes: fsmonitor, hooksPath, filter drivers, submodule status) is neutralised, and line-ending comparisons defer to git's own hashing.

A repo-local `core.fsmonitor` would otherwise execute arbitrary code whenever Aegis runs `git status`.

### 3.8 Several hosts on one repo

- **Ledger-only fitness** (H6, AD-1): servers, hooks and session close never rewrite rule files. `aegis sync` is the single derived-view writer, under the one lock.
- **No reflection on close** (AD-1): the server's stdin-EOF reflection is removed. N servers no longer record one change N times.
- **Attribution**: every ledger row carries `host` (server-owned) and `session` (the server instance id). The idempotency key includes both.
- **Worktrees**: per-worktree ledgers stay for v4.0 (H5 deferred). Team coordination state (v4.1, AD-7) lives in git refs, which every worktree shares.

### 3.9 Enforcement tiers (AD-8)

| Tier | Mechanism | Hosts |
|---|---|---|
| Advisory | AGENTS.md bootstrap, MCP `instructions`, JIT rules | all |
| Best-effort | per-host pre-tool hooks (Phase 2) | Claude Code (can block); Codex (fails open, needs user trust) |
| Local floor | git `pre-commit` → `aegis check --hook` (bypassable with `--no-verify`) | every host commits through git |
| Authoritative | CI running `aegis check` on the exact SHA; human merge | — |

`aegis doctor` prints this table for the selected hosts, and the README states it verbatim.

### 3.10 Doctor

`aegis doctor` prints a read-only host × {binary found, `aegis` registered, command path exists, identity, workspace registered, bootstrap present, budget} matrix. Its warnings:

- a `CLAUDE.md` without `@AGENTS.md`;
- a `soma` MCP entry;
- legacy SOMA/AEGIS blocks;
- an inlined-rules `CLAUDE.md` larger than the budget;
- `$HOME/.aegis/rules` created by v3.3 auto-mkdir.

`doctor --fix` backs up each file it touches to `~/.aegis/backups/<timestamp>/` and then:

- removes stale `soma` and `aegis` duplicates;
- removes legacy blocks;
- moves the Claude Desktop `aegis` entry out (H4).

It touches only what it reports.

## 4. Phasing

| Phase | Ships | Release |
|---|---|---|
| 1 | §3.1–3.10 for codex-cli, claude-code (user scope) and antigravity; claude-desktop identity only | v4.0 (ADR §6 step 3) |
| 2 | Per-host hooks (Claude scan-before-edit first); skills projection (`.agents/skills`, `.claude/skills`); gemini-cli, cursor, copilot, kiro and windsurf rows after 3 clean runs each | v4.1 |
| 3 | Plugins and extensions; worktree-shared ledger (H5) | v4.2, only with an incident or metric |

## 5. Trade-offs

| Choice | Latency | Complexity | Cost |
|---|---|---|---|
| Bootstrap + JIT instead of inlining | +1 tool round-trip per edit batch | ↓ (one writer instead of N bespoke ones) | fixed context drops from 8.4K–23.8K tokens per turn to about 126 |
| Native-CLI registration | one subprocess per host at init | low (subprocess mocked in tests) | none |
| Binding resolver + registry | one cached lookup per call | medium | none; a repo must be `aegis init`'d once per machine to be governed in Antigravity |
| No committed MCP files | cloud sessions need a manual registration | ↓ | none |
| Data table instead of adapters | none | ↓ until a host needs custom logic | none |

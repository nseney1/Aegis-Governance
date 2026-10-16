# Changelog

All notable changes to Aegis Guardrails are documented here. The project uses [Semantic Versioning](https://semver.org/). Releases before 1.0.0 are summarized at the end.

## [4.0.0] - 2026-10-16

v4.0 rebuilds v3.3 around what was actually used and what can be checked. It has fewer commands and MCP tools, one config file, an append-only ledger as the only source of rule fitness, and a host plane that registers Aegis with Codex CLI, Claude Code and Antigravity. The reasons, with the evidence and the mistakes behind them, are in [docs/why-aegis.md](docs/why-aegis.md); the decisions are in [ADR 0005](docs/adr/0005-v4-plan-of-record.md). Every removed command and flag exits with status 2. Removed commands, and the removed `init` and `uninstall` flags, print one line naming the replacement (or saying there is none); the other removed flags get the argument parser's usage error, and the Breaking changes list below names their replacements.

### Upgrading from 3.x

1. `pip install --upgrade aegis-guardrails`
2. In each repository, run `aegis migrate` to see the plan, then `aegis migrate --apply`. It converts the v3 ledger, the old config files and `.soma` or v3 rule folders to the v4 layout, and backs up every file it changes to `.aegis/state/migrate-backup-<time>/`. Running it again changes nothing.
3. Run `aegis init --host codex-cli,claude-code,antigravity` (or `--host auto`; add `--dry-run` to preview). It registers the MCP server with each host and writes the `AGENTS.md` bootstrap.
4. Run `aegis doctor`, then `aegis doctor --fix` to remove v3 leftovers: `soma` MCP entries, misplaced MCP entries and legacy rule blocks in instruction files. Each file is backed up first.

### Breaking changes

**Commands**

- Removed commands and their replacements: `install` → `aegis init --host`; `system`, `sys`, `detect`, `languages`, `drivers`, `audit` → `aegis doctor`; `verify`, `checkpoint` → `aegis check` (v3's `aegis checkpoint` is `aegis check --strict`); `agent` → `aegis scan`, with outcomes recorded through the MCP tool `aegis_report_outcome`; `report`, `rules` → `aegis status`; `completion`, `skill`, `handoff` → no replacement.
- `aegis migrate` is now a converter (dry run by default, `--apply` to perform it). In v3 it only reported migration status.
- `aegis rule clean` and `aegis doctor --fix-path` are removed (they rewrote global files and shell rc files). `aegis doctor --fix` removes legacy rule blocks and unedited v3 rule copies; remove edited copies by hand.
- `aegis hook pre-commit` is replaced by `aegis check --hook`. The agent-side hook phases `pre-invocation`, `governance-monitor`, `immune-init`, `session-close`, `stop` and `post-session` are removed; remove them from your host's hook config. `python -m aegis_cli.hooks` no longer exists. Git hooks installed by v3 are reported as outdated, and `aegis hook install` rewrites them.

**Hosts**

- Gemini CLI is retired: Google refuses the client for individual Code Assist accounts, and Antigravity is the Gemini-family host. `aegis init --host gemini-cli` and `aegis uninstall --host gemini-cli` exit with status 2 and print `gemini-cli is not supported: Google retired Gemini CLI for individual Code Assist accounts; use --host antigravity.` The MCP server still recognizes a connecting Gemini CLI client by name; no Gemini CLI registration, hooks or extension are planned.

**Flags**

- Global flags are `--json`, `--plain` and `--workspace`. `--plumbing`, `--internal`, `-q`, `-v`, `--no-emoji` and the global `--format` are removed.
- `aegis init`: `--platform`, `--mcp` and `--local` are replaced by `--host`. `aegis uninstall`: `--platform`/`-p`, `--local` and `--purge` are removed.
- `aegis check`: Release Gate 4.5 (`--release`, `--release-gate`, `--require-arbitration`) is removed; releases are gated by CI on the exact commit. `--provider` and `--in-band` are replaced by `--llm-cmd`. `--no-layer2`, `--all`, `--files` (files are now positional), `--pre-commit`, `--checkpoint-only`, `--layer1-only`, `--deep` and `--format sarif` are removed. `check` now also runs the workspace checkpoint and prints its warnings; `--strict` turns them into failures.
- `aegis rule create`: `--from-description` (it never worked), `--weight`, `--expiry-sessions`, `--expiry-days`, `--minimum-mode`, `--effector` and `--memory` are removed. `rule promote`/`demote` lose `--rule`, `--reason` and `--force`; `rule archive` loses `--apply` and its rule argument. `status --all` is removed.
- `aegis doctor --yes` is only valid with `--fix`, and `--fix` asks before changing anything (`--yes` is required with `--json` or without a terminal).

**MCP server**

- The server has 4 tools: `aegis_scan`, `aegis_report_outcome`, `aegis_create_rule` and `aegis_list_rules`. Removed: `aegis_request_receipt`, `aegis_verify_changes`, `aegis_poll_verification`, `aegis_checkpoint`, `aegis_grade`, `aegis_coverage`, `aegis_rule_fitness`, `aegis_audit_security`, `aegis_audit_performance`, `aegis_capture_insight`, `aegis_propose_change`, `aegis_handoff` and `aegis_generate_manifest`. Calling one returns the JSON-RPC error -32602 "Unknown tool".
- Receipts and the session token are removed, with the `receipt` and `_sessionToken` arguments. `AEGIS_EXECUTION_ENABLED` and `AEGIS_REQUIRE_SESSION_TOKEN` are gone.
- Arguments are checked against each tool's schema before dispatch, so unknown arguments are rejected. `aegis_report_outcome` requires `idempotency_key` and `rules_used`; the aliases `cells_used`, `rule_id`, `rules` and `cell_id` are rejected. The `fields` projection is removed; `view` stays.
- `aegis_scan` has one name per field (`relevant_rules`, `guidance`, `invariant_warnings`, `rules_staged`, `stats`) and adds `stats.omitted`, `omitted_mandatory`, `stale_rules` and `warnings`. It drops `relevant_cells`, `context`, `wall_warnings`, `cells_staged`, `target_constraints`, `genome_guidance`, the per-rule copies of the guidance text and the `planned_symbols` argument. Matching is by path only. `AEGIS_MAX_JIT_TOKENS` now bounds the whole response: gates and invariants fill first, and the rules that do not fit are counted. A scan fails while a rule file cannot be loaded.
- `aegis_list_rules` returns `{rules, stale_rules, ignored}` instead of a list.

**Configuration and environment**

- One repository config, `.aegis/config.json` (hosts, JIT budget, rule expiry, opted-in packaged AST drivers), and one user config, `~/.aegis/config.json` (custom AST driver commands and slot overrides). `aegis.conf`, `.aegis/config.yaml`, `.aegis/slots.yaml`, `~/.aegis/slots.yaml` and `steering.conf` are no longer read; `aegis migrate` converts them. A repository can no longer name a command: not an AST driver, not a slot such as `TEST_RUNNER`, not the Layer 2 model command.
- The environment variables are `AEGIS_WORKSPACE`, `AEGIS_CLIENT`, `AEGIS_MAX_JIT_TOKENS` and `AEGIS_LLM_CMD`. Removed: `AEGIS_ROOT`, `AEGIS_CONTEXT_BUDGET`, `AEGIS_LOGS_DIR`, `AEGIS_INFERENCE_PROVIDER`, the `RULE_EXPIRY_*` and `CELL_TELOMERE_*` variables, and the Layer 2 API keys (`GEMINI_API_KEY`, `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`) with the keyring lookup.

**Workspace layout and data**

- The layout is `.aegis/{config.json, .gitignore, rules/<type>/, state/}`. `state/` holds machine-local, git-ignored files: `ledger.jsonl`, `activity.jsonl`, `derived.json`, `gate_events.jsonl` and the one workspace lock.
- The outcome ledger moves from `.aegis/evidence/signals.jsonl` to `.aegis/state/ledger.jsonl`, with versioned (v2) rows. v1 rows are still read, and `aegis migrate` converts them.
- Rules live in `.aegis/rules/<type>/` for the six types `invariant`, `trap`, `gate`, `boundary`, `persona` and `contract`. Rules in v3 folders (`walls/`, `membranes/` and the like) are not served: `scan` and `check` fail closed and name them until `aegis migrate` moves them.
- Fitness comes only from the ledger. Fitness fields in rule frontmatter are ignored, and nothing at runtime writes rule files.
- The HMAC manifest (`.aegis/rules/manifest.json`), its keys, the receipt keys and the Release Gate arbitration evidence are gone. `aegis sync` writes an unsigned sha256 index used only to show which rules were edited since the last sync.
- `aegis init` no longer copies rules into `~/.gemini`, `~/.claude`, `~/.cursor`, `~/.kiro` or `.github/copilot`, no longer inlines rules into `CLAUDE.md` and no longer writes `.mcp.json`. It seeds starter rules into `.aegis/rules/personas/`.
- Five rules that only govern this repository (`gitflow-review-gate`, `ci-green-before-release`, `core-change-protocol`, `no-pre-existing-excuse`, `optional-import-guard`) moved from the shipped `rules/` to this repository's `.aegis/rules/`, and `desktop-automation` is no longer shipped.
- The `VERSION` file is gone; the version is in `aegis_core/_version.py`.

**Layer 2 (`aegis check --full`)**

- One backend: the command given with `--llm-cmd` or `AEGIS_LLM_CMD`, for example `claude -p` or `codex exec`. It runs as an argument list (no shell) in an empty temporary directory, gets the prompt on stdin and returns its reply on stdout. It is never read from repository files. The Gemini, Anthropic and OpenAI SDK wrappers, the keyring, the in-band charge sheet and MCP sampling are removed.
- `--full`, `--plan` or `--plan-file` without a backend exits 2 instead of skipping Layer 2.

**Output and Python API**

- `aegis check --json` renames the checks `cell_fitness`, `cell_conventions` and `paper_walls` to `rule_fitness`, `rule_conventions` and `paper_gates`, and adds `rule_load`. `aegis doctor --json` prints one `aegis.doctor/v1` document. `aegis hook status --json` reports `managed_by_aegis` and `interpreter`.
- `aegis_sdk` exports only `Governance` (`grade`, `coverage_report`, `scan`, `entropy`, `list_rules`, `fitness_landscape`), `parse_rule_file` and `__version__`. Its other modules are removed, and so are many internal `aegis_core` modules, among them `integrity`, `scoring`, `receipts`, `locking`, `evidence` and `workspace.git.GitWorkspace`.

### Added

- **Host plane.** `aegis init --host codex-cli,claude-code,antigravity` (or `auto`) registers the `aegis` MCP server through each host's own mechanism (`codex mcp add`, `claude mcp add --scope user`, Antigravity's `~/.gemini/config/mcp_config.json`). It also writes a short bootstrap block into `AGENTS.md` (plus an `@AGENTS.md` block in an existing `CLAUDE.md`), installs the git pre-commit hook and records the workspace in `~/.aegis/workspaces.json`. It supports `--dry-run`, `--pin` and `--force`. `aegis uninstall` reverses this and never deletes `.aegis/`.
- **Workspace binding.** The MCP server binds each call to a workspace: an operator pin, then the roots the host reports, then the registry, then a walk up from its working directory that stops at the git top level. It never governs `$HOME`, and it never takes a workspace from a tool argument. When nothing resolves, `aegis_scan` serves the read-only user rule layer in `~/.aegis/rules/` and writes nothing.
- **Host identity.** The server identifies its host from the registration (`AEGIS_CLIENT`) or the client name, defaulting to `generic`. Host and session are recorded by the server, never taken from tool arguments. The bootstrap text is also returned as the MCP `initialize` instructions.
- **`aegis doctor`** reports one state per host (`ok`, `missing_binary`, `unregistered`, `auth_unknown`, `policy_gap`) with its enforcement level, plus the enforcement tiers in force here. `--fix` changes only what doctor reported, after confirmation, and backs each file up to `~/.aegis/backups/<UTC stamp>/` first. Doctor makes no network calls.
- **`aegis scan FILE...`** shows the rules that apply to files you are about to edit (it was `aegis agent scan`).
- **`aegis sync`** rebuilds rule fitness from the ledger and suggests promotions, demotions and archives. `--apply` applies them; nothing else changes a rule's tier.
- **`aegis status --compliance`** reports the scan-before-edit rate per host and per session from `.aegis/state/activity.jsonl`, with the method's limits printed next to the numbers.
- **`aegis rule create --body-file`** reads a rule body from a file or stdin. `aegis rule list` flags rules edited since the last sync.
- **gitsafe.** Every git command Aegis runs switches off what a repository's own config can make git execute: `core.fsmonitor`, hooks, the repository's filter drivers, credential helpers, remote protocols and submodule status.
- **Generated reference.** [docs/reference.md](docs/reference.md) lists every command, option and MCP tool. It is generated from contract snapshots of the CLI and the MCP surface, and a test fails when either changes without the snapshot.
- **Pre-tag check.** `.github/scripts/ci_green.py <sha>` exits 0 only when CI passed on that exact commit.

### Fixed

These are the v3.3 defects found by the v4 review ([evidence review](docs/adr/0005-evidence-review.md)) and the build waves.

- `forbid_ast` was bypassed by import aliases (`import subprocess as sp`), rebinding, a CR-only encoding cookie and dynamic imports, and silently skipped files it could not read (a byte-order mark, latin-1). It now resolves aliases and fails closed.
- A repository's `.aegis/slots.yaml` could run commands and inject text into scan output. Repository config can no longer name commands.
- Manifest auto-sync re-signed tampered rules, and the release gate accepted a hand-written SHIP verdict. Both mechanisms are removed.
- About 80 of 120 concurrent fitness updates were lost, and rules whose frontmatter Aegis had rewritten were then dropped as "tampered". Fitness is now appended to the ledger under one lock, and rule files are never rewritten at runtime.
- `aegis rule create --workspace` on a repository without `.aegis/` wrote to `~/.aegis/rules`.
- The YAML serializer wrote text its own parser rejected (`\r`, U+2028, keys with newlines).
- An unparseable host MCP config was overwritten; it is now refused with a clear error.
- The MCP server died on a non-object JSON line, created `~/.aegis` at startup and ran reflection on shutdown, recording one change once per open server. None of these happen now, and `aegis_report_outcome` retries no longer double-count.
- Layer 1 fails closed when a check tool raises, and a skip or xfail no longer counts as an assertion.
- Windows and macOS: workspace path containment on Windows, line endings compared through git's own conversion, host CLIs run under their on-disk spelling, and `--llm-cmd` split without POSIX escapes on Windows.

### Known limitations

- `aegis check` records each run's pass or fail against every rule whose paths match the checked files, and self-reports from MCP clients count toward fitness too. So a gate that blocks a bad commit is scored as a miss. Fitness only ranks guidance and drives `sync` suggestions; no rule changes tier without an explicit command. A per-rule credit model is planned for v4.3 ([why-aegis](docs/why-aegis.md) §6).
- The starter rules `aegis init` seeds have no `target_paths`, so they apply to no file until you add patterns; `aegis status` lists them.
- Per-host agent hooks for Claude Code, Codex CLI and Antigravity are planned for v4.1. In v4.0 the enforcement points are the git pre-commit hook (`--no-verify` skips it) and CI.
- Rule frontmatter has no schema version yet; the ledger, the config files, the derived view and the workspace registry do.

## [3.3.0] — 2026-10-14 — "Cryptographic Provenance, Declarative AST Rules, Telemetry Compaction, SARIF 2.1.0 & Multi-Platform Claude Desktop Support"

### Security & Cryptographic Provenance (Phase 3.3.1)
- **Git Working-Tree Digest Binding (`aegis_core/receipts.py`)**:
  - Updated `compute_file_digest()` so operations without explicit file arguments (`target_paths=[]`) inside a Git workspace bind the receipt state digest to `git rev-parse HEAD` + `git status --porcelain`, invalidating receipts if working-tree state changes between issuance and redemption.
- **Inbound `HandoffTicket` Verification (`aegis_core/skills/handoff.py`, `aegis_cli/skills.py`)**:
  - Added `HandoffRouter.consume_handoff()` and `aegis handoff consume <ticket_id> [--no-verify-tree] [--json]`, verifying the `ArtifactEnvelope` HMAC signature and optional `HEAD^{tree}` hash before returning the payload and marking the ticket `"consumed"`.
- **Automatic `.aegis/manifest.json` Verification in `RuleCache` (`aegis_mcp/rule_cache.py`)**:
  - Updated `RuleCache` to verify rule SHA-256 digests against `.aegis/manifest.json` on cache load/refresh, automatically excluding tampered rules and logging a diagnostic warning.
- **Claude Desktop & Cross-Model Platform Parity (`aegis_cli/platforms/claude.py`, `aegis_mcp/server.py`)**:
  - Updated `ClaudeAdapter.install()` / `uninstall()` to provision all 15 `skills/*/SKILL.md` into `.claude/skills/`, register `aegis` MCP in `~/.config/Claude/claude_desktop_config.json`, inject a cross-model tool/tier equivalence table into `CLAUDE.md`, and auto-scaffold `~/.aegis/rules` when `aegis-mcp` starts from `$HOME`.

### Declarative Rule-Level AST Checks & Pre-Edit Symbol Scan (Phase 3.3.2)
- **Declarative `forbid_ast` in Rule Frontmatter (`aegis_core/ast/match.py`, `aegis_core/verification/runner.py`)**:
  - Added `evaluate_forbid_ast()` supporting `imports`, `calls`, and `decorators` in `invariant` and `gate` rule YAML frontmatter, evaluated deterministically by Layer 1 (`DeterministicVerifier`) across `NormalizedAST`.
- **Pre-Edit Symbol Intent (`planned_symbols`) in `aegis_scan` (`aegis_mcp/registry.py`, `aegis_mcp/jit_engine.py`, `aegis_mcp/handlers/audit.py`)**:
  - Added optional `planned_symbols: list[str]` to `aegis_scan` so agents can declare imports, calls, or decorators they plan to use before writing code, matching `ast_triggers` and `forbid_ast` rules proactively.

### Segmented Telemetry Compaction & SARIF 2.1.0 Output (Phase 3.3.3)
- **Segmented Telemetry Compaction (`aegis_core/telemetry.py`, `aegis_cli/system.py`)**:
  - Added `compact_signals()` and `aegis system compact [--days 30] [--dry-run] [--json]`, rolling up expired signals into `.aegis/telemetry/checkpoint_rollup.json`, archiving raw records to `.aegis/telemetry/archive/signals-<YYYY-MM>.jsonl.gz`, and preserving Thompson Sampling priors across compactions.
- **SARIF 2.1.0 Output (`aegis_cli/check.py`, `aegis_cli/verify.py`)**:
  - Added `--format sarif` (`format_sarif_report()`) to `aegis check` and `aegis verify` for GitHub Code Scanning and IDE diagnostics integration.

## [3.2.0] — 2026-10-14 — "Fortress Perimeter Hardening, Horizontal Skill Graph Wiring, O(1) Telemetry Caching & Full Documentation Overhaul"

### Security & Perimeter Hardening (Fortress Adaptive Review)
- **Workspace Confinement in Core I/O (`aegis_core/operations.py`)**:
  - Hardened `Operations.resolve_path()` to enforce `confine_path_internal()` across all `Operations` file/JSONL reads and writes while allowing workspace root tokens (`""` / `"."`).
- **Ephemeral Receipt Authentication Before Burn (`aegis_core/receipts.py`)**:
  - Fixed `ReceiptManager.verify()` in ephemeral mode so `self._store.get()` is used during Step 1 (TTL + HMAC verification) and `self._store.pop()` only executes in Step 2 (`BURN BEFORE COMPARE`), preventing unauthenticated probes from evicting valid in-memory nonces.
- **MCP Privileged Tool Schemas, Projection & AST Workspace Threading (`aegis_mcp/`)**:
  - Threaded `workspace` from `jit_engine.express()` through `match_cells_to_files()` and `match_cells_for_diff()` so syntactic AST triggers resolve relative to the workspace root rather than process `CWD`.
  - Added optional `receipt` property to `TOOL_DEFINITIONS` schemas for all 6 privileged write/execute tools (`aegis_propose_change`, `aegis_checkpoint`, `aegis_report_outcome`, `aegis_capture_insight`, `aegis_generate_manifest`, `aegis_handoff`).
  - Exposed `rule_prompt` in `_handle_create_cell()` and `SUMMARY_FIELDS` (`aegis_mcp/projection.py`) so `aegis_create_rule` returns the generated prompt without colliding with the `"prompt"` denylist filter.

### CLI Dispatch, Platform Adapters & Closed-Loop Rules
- **CLI Dispatch & `migrate` Unblocking (`aegis_cli/cli.py`, `aegis_cli/registry.py`, `aegis_cli/rule.py`, `aegis_cli/check.py`, `aegis_cli/init.py`)**:
  - Unblocked `aegis migrate` on legacy `.soma` workspaces by walking upward to locate `.soma` or `.aegis` before `Workspace.resolve()` runs `check_legacy_soma_sentinel()`.
  - Unified `install` and `uninstall` into `COMMANDS` and registered `DetectCommand` (`aegis detect`), `SkillCommand` (`aegis skill`), and `HandoffCommand` (`aegis handoff`) in `CommandRegistry`.
  - Added `aegis rule create` subcommand (`aegis_cli/rule.py`), `--no-hooks` flag on `aegis init`, and fixed `aegis check --in-band` so it proceeds to Layer 2 ChargeSheet generation.
  - Updated `GeminiAdapter` hook commands (`aegis hook ...`), `PlatformAdapter.render_mcp_entry()` (`command="aegis-mcp"`), and `install/hooks/pre-commit` (Format 4 `#!/bin/sh` runner).

### `AegisYAML`, JSONL Efficiency & Horizontal Skills as Slots
- **Stat-Fingerprinted `_SIGNALS_CACHE` & `AegisYAML` Validation (`aegis_core/telemetry.py`, `aegis_core/yaml.py`, `aegis_core/lifecycle/creation.py`, `aegis_core/insights.py`)**:
  - Added an in-memory `(st_ino, st_mtime_ns, st_size)` cache (`_SIGNALS_CACHE`) to `_read_existing_events()` and `append_signals()`, eliminating $O(N)$ historical JSONL re-parsing on repeated signal appends.
  - Added round-trip `AegisYAML.parse_text()` validation to `create_cell()` and added `scaffold_invariant` / `invariant_id` support to `capture_insight()`.
- **Horizontal Skill Graph & Slot Interpolation (`aegis_core/skills/`, `aegis_cli/skills.py`, `skills/*/SKILL.md`)**:
  - Enriched all 15 shipped `skills/*/SKILL.md` manifests with `id`, `kind: skill`, `tier`, `consumes`, `produces`, and `handoff_targets`.
  - Updated `SkillGraph.discover()`, `SkillGraph.default_search_paths()`, and `SkillNode.from_doc()` to discover all 15 skills by directory slug out of the box and interpolate `${SLOT.*}` bindings from `.aegis/slots.yaml` in `SkillNode.load_instructions()`.

### Full-Repository Documentation Overhaul
- Overhauled 22 documentation files across root (`CONTRIBUTING.md`, `QUICKSTART.md`, `PRIVACY.md`, `SECURITY.md`), guides (`docs/guides/rule_lifecycle.md`, `mcp_gateway.md`, `polyglot_ast.md`, `skill_graph.md`, `verification_pipeline.md`, `docs/index.md`), architecture (`mechanism_design.md`, `phylogeny.md`, `scripts.md`, `ADR-012..016`), and project governance (`COMPATIBILITY.md`, `CONTRIBUTING.md`, `RELEASE_WORKFLOW.md`, `ROADMAP.md`, `METRICS.md`), and removed obsolete `docs/organelles.md`.

## [3.1.0] — 2026-10-14 — "Architecture Hardening, Cryptographic Receipt Burn-Before-Compare & Canonical Aegis Taxonomy"

### Packaging & Standalone Wheel Parity
- **`rules` & `skills` Package Bundling (`pyproject.toml`, `aegis_cli/platforms/base.py`, `.github/scripts/wheel_smoke.py`)**:
  - Added `rules` and `skills` (`rules/__init__.py`, `skills/__init__.py`) to `[tool.setuptools.packages.find]` and `[tool.setuptools.package-data]` (`rules = ["*.md", ".oracles/*.md"]`, `skills = ["*/SKILL.md"]`) so standalone `pip install aegis-guardrails` wheels bundle all 18 core rules and 15 agent skills.
  - Updated `PlatformAdapter.get_source_skills()` (`aegis_cli/platforms/base.py`) to fall back to `importlib.resources.files("skills")` when running outside a git checkout, matching `get_source_rules()`.
  - Extended `.github/scripts/wheel_smoke.py` to assert non-empty `get_source_rules()` and `get_source_skills()` under `python -I` outside the repository.

### Cryptographic Security Hardening
- **Burn-Before-Compare Single-Use Receipts & Sidecar Locking (`aegis_core/receipts.py`, `aegis_mcp/server.py`)**:
  - Hardened `ReceiptManager.verify(..., consume=True)` under exclusive sidecar file lock `.aegis/locks/receipts.lock` to verify HMAC-SHA256 signature and expiration first, immediately append the consumed nonce to `.aegis/receipts.jsonl` (`fsync`), and only then compare `file_digest` and `rule_digest`, preventing pre-burn replay attacks on digest mismatch or path validation failures.
  - Fixed ledger compaction (`_compact_consumed_locked`) to prune only expired nonces (`exp < now`), eliminating the 1,000-nonce FIFO eviction replay vulnerability.
  - Wrapped `server.py:_verify_receipt_for_call` `_compute_state_digest` in `try/except ValueError` so invalid path arguments occur after receipt burn and return structured JSON-RPC errors without leaking unburned tokens.

### Verification Engine & MCP Tool Surface Cleanup
- **Deduplicated `scan_test_issues()` & Narrowed Exception Handling (`aegis_core/ast_checks.py`, `aegis_core/verification/`, `aegis_core/rule_inventory.py`, `aegis_core/telemetry.py`)**:
  - Extracted shared `scan_test_issues()` in `aegis_core/ast_checks.py` and wired both `aegis_cli/check.py` and `aegis_core/verification/pipeline.py` to eliminate duplicated test AST scanning logic.
  - Narrowed broad `except Exception:` blocks in `aegis_core/verification/runner.py`, `aegis_core/rule_inventory.py`, and `aegis_core/telemetry.py` to specific exception tuples (`(OSError, ValueError, KeyError, TypeError)` / `(OSError, subprocess.SubprocessError, ValueError, KeyError)`).
- **17 Canonical `aegis_*` MCP Tools (`aegis_mcp/registry.py`, `aegis_mcp/tools.py`, `aegis_mcp/server.py`)**:
  - Removed legacy duplicate MCP tool definitions `aegis_list_cells`, `aegis_fitness`, and `aegis_create_cell`, standardizing on the 17 canonical `aegis_*` tools (`aegis_list_rules`, `aegis_rule_fitness`, `aegis_create_rule`, etc.).
- **Clean-Tree Manifest Generation (`aegis_cli/check.py`, `aegis_core/rule_inventory.py`)**:
  - Made `aegis check` read-only by default (no longer mutating `.aegis/rules/manifest.json` during read-only checks) and added `RuleInventory.check_manifest_sync()`.

### Canonical Aegis Taxonomy Cutover
- **Review Modes, Prongs, Genesis Stages & `.aegis/rules/` Metadata (`aegis_core/`, `aegis_cli/`, `rules/`, `skills/`, `.aegis/rules/`)**:
  - Cut over review modes from weather metaphors (`breeze`, `gale`, `trident`, `maelstrom`, `tempest`, `supercell`) to defensive posture tiers (`patrol`, `sweep`, `vanguard`, `bulwark`, `fortress`, `citadel`).
  - Cut over review prongs from botanical metaphors (`spores`, `roots`, `thorns`, `bedrock`, `canopy`, `mulch`) to security operations roles (`sentry`, `trace`, `probe`, `bastion`, `gauntlet`, `debrief`).
  - Cut over Genesis onboarding stages from biological metaphors (`membrane`, `fossil`, `anatomy`, `physio`) to structural reconnaissance stages (`perimeter`, `chronology`, `blueprint`, `policy`).
  - Updated all 18 core rules (`rules/`), 15 agent skills (`skills/*/SKILL.md`), and 42 `.aegis/rules/` rule files to canonical Aegis v3.1.0 terminology and persisted Citadel v3.0.0 debrief learnings in `governance/debrief_queue.jsonl`.

## [3.0.0] — 2026-10-14 — "Pure Aegis Clean-Slate Architecture & Zero-Dependency CLI UX"

### Breaking Changes (Pure Aegis Clean-Slate Cutover)
- **Legacy `soma_*` Shims & `Soma*` / `Cell*` Aliases Removed**:
  - Deleted `aegis_core/compat.py`, `aegis_core/somayaml.py`, `aegis_sdk/cells.py`, `aegis_core/cell_inventory.py`, and `aegis_mcp/cell_cache.py`. Importing `soma_core`, `soma_cli`, `soma_sdk`, or `soma_mcp` now raises `ModuleNotFoundError`.
  - Removed all `Soma*` and `Cell*` class/error aliases (`SomaError`, `SomaValidationError`, `SomaYAMLError`, `SomaDocument`, `SomaYAML`, `SomaCommand`, `SomaParser`, `Cell`, `CellFitness`, `CellNotFoundError`, `CellParseError`, `CellPathTraversalError`).
- **Pure `.aegis/rules/` Workspace & Upgrade Sentinel**:
  - Removed `.soma/` and `.soma/cells/` fallback resolution across `aegis_core/workspace/`, `aegis_core/locking.py`, `aegis_core/rule_inventory.py`, `aegis_mcp/rule_cache.py`, and `aegis_sdk/rules.py`.
  - Unmigrated `.soma/` workspaces now trigger an immediate Upgrade Sentinel diagnostic instructing users to run `aegis migrate` on v2.1.x before upgrading to v3.0.0.
  - Renamed all repository rules in `.aegis/rules/invariants/` and `.aegis/rules/boundaries/` from `wall-*.md` / `membrane-*.md` to `invariant-*.md` / `boundary-*.md` and removed legacy biological rule types (`vacuole`, `chloroplast`, `plasmodesmata`).
- **Pure `aegis_*` MCP Tool Namespace**:
  - Cut over all 20 MCP tools in `aegis_mcp/registry.py`, `aegis_mcp/tools.py`, and `aegis_mcp/server.py` to the `aegis_*` namespace (`aegis_scan`, `aegis_report_outcome`, `aegis_create_rule`, `aegis_list_rules`, `aegis_verify_changes`, `aegis_checkpoint`, `aegis_handoff`, etc.) and removed `_CANONICAL_TOOL_MAP`.

### Zero-Dependency Terminal UI & CLI Unification
- **Terminal Theme & Adaptive Table Engine (`aegis_cli/ui/`)**:
  - Added `OutputContext` (`aegis_cli/ui/theme.py`) honoring `NO_COLOR`, `FORCE_COLOR`, `TERM=dumb`, `isatty()`, `--plain`, `--no-emoji`, and `--json` with zero ANSI leakage in non-TTY/JSON modes.
  - Added ANSI-aware `Table`, `Grid`, `Column`, `render_table`, `render_box`, and `render_error_panel` (`aegis_cli/ui/table.py`) while preserving `dependencies = []` in `pyproject.toml`.
- **Unified Command Registry & Core Deduplication**:
  - Registered `doctor`, `report`, `install`, and `uninstall` directly in `CommandRegistry` (`aegis_cli/registry.py`) and unified `aegis init` onto `aegis_cli/platforms/` adapters.
  - Consolidated frontmatter parsing onto `aegis_core/yaml.py`, atomic writes onto `aegis_core/storage.py`, relocated `aegis_core/verification/jobs.py`, and renamed `aegis_core/proposals.py`.

## [2.1.0] — 2026-10-14 — "Pure Aegis Unification, Migration Bridge & aegis-guardrails Cutover"

### Package & Repository Cutover
- **PyPI Package (`aegis-guardrails`) & Repository (`Aegis-Guardrails`)**:
  - Updated `pyproject.toml` distribution package name to `aegis-guardrails` (`pip install aegis-guardrails`) and repository links to `https://github.com/nseney1/Aegis-Guardrails`.
  - Updated `.github/workflows/publish.yml` OIDC Trusted Publisher target to `https://pypi.org/p/aegis-guardrails`.
  - Updated `aegis_core/workspace/discovery.py`, `aegis_cli/cli.py`, and `aegis_mcp/server.py` to resolve `aegis-guardrails` metadata.

### Workspace Migration Bridge (`aegis migrate`) & Modern Rule Taxonomy
- **Interactive & Automated `.soma` $\rightarrow$ `.aegis` Migration (`aegis_cli/migrate.py`)**:
  - Added `aegis migrate` (`--dry-run`, `--json`) to atomically migrate legacy `.soma/cells/` workspaces to `.aegis/rules/` (`invariants/`, `traps/`, `boundaries/`, `personas/`, `contracts/`).
  - Rewrites legacy biological `type:` frontmatter (`vacuole` $\rightarrow$ `trap`, `wall` $\rightarrow$ `invariant`, `membrane` $\rightarrow$ `boundary`, `chloroplast` $\rightarrow$ `persona`, `plasmodesmata` $\rightarrow$ `contract`) during migration (`BUG-099`).
- **Native Aegis Primitives (`AegisYAML`, `Rule`, `AegisError`, `AegisCommand`)**:
  - Promoted `aegis_core/yaml.py` (`AegisYAML`, `AegisDocument`, `parse_rule_frontmatter`), `aegis_sdk/rules.py` (`Rule`, `RuleFitness`), `aegis_core/errors.py` (`AegisError`, `AegisValidationError`, `RuleCorruptError`), and `aegis_cli/base.py` (`AegisCommand`) to primary implementations while retaining v2.x compatibility aliases.

### Runtime Engine & Governance Rule Wiring (`BUG-096`–`BUG-100`)
- **Governance Rule Frontmatter & Platform Adapter Parity (`BUG-096`, `BUG-097`)**:
  - Added required `trigger:` and `description:` frontmatter to `rules/META.md`, `rules/gitflow-review-gate.md`, `rules/core-change-protocol.md`, `rules/ci-green-before-release.md`, and `rules/no-pre-existing-excuse.md`.
  - Removed the `META.md` exclusion filter in `aegis_cli/platforms/base.py:discover_rules()`.
- **`.aegis/rules/` Engine Discovery (`BUG-098`, `BUG-100`)**:
  - Updated `aegis_mcp/jit_engine.py`, `aegis_core/sentinels.py`, `aegis_core/metrics.py`, `aegis_core/lifecycle/`, `aegis_cli/hooks/runtime.py`, `aegis_cli/init.py`, and `aegis_core/enforcement.py` to discover `.aegis/rules/` and emit modern Aegis response keys (`relevant_rules`, `invariant_warnings`, `triggered_rules`, `matched_rules`, `rules_triggered`, `total_rules`, `invariant_strength`).

## [2.0.0] — 2026-10-14 — "Soma-to-Aegis Unification & Architecture Rebrand"

### Architectural Rebrand
- Renamed core packages to `aegis_core`, `aegis_cli`, `aegis_mcp`, and `aegis_sdk` with `aegis_core/compat.py` import hooks preserving `soma_*` backwards compatibility across the v2.x line.
- Consolidated `genome/` into `rules/` and `.soma/cells/` into `.aegis/rules/`.

## [1.5.1] — 2026-10-14 — "Subagent Delegation Governance & CI Supply Chain Hardening"

### CI Supply Chain & Dependabot Pipeline Hardening
- **Artifact Action Security Bumps**:
  - Bumped `actions/upload-artifact` from v7.0.1 (`043fb46d1a93c77aae656e7c1c64a875d1fc6a0a`) to v7.0.2 (`cf430e030ddbb5b0abf93d22962f4752f3646cd9`).
  - Bumped `actions/download-artifact` from v8.0.1 (`3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c`) to v8.0.2 (`9000827ccba6bdab643e8b6fd33ac0654aef8333`).
- **Dependabot Workflow Routing**:
  - Configured `target-branch: "develop"` in `.github/dependabot.yml` across `github-actions` and `pip` package ecosystems.
  - Ensured automated dependency PRs build and validate against `develop` without triggering PR-to-main Release Gate 4.5 arbitration checks.
  - Extended `tests/integration/test_ci_workflows.py` to assert `target-branch: "develop"` is preserved.

### Governance & Architecture
- **Prefer Subagent Delegation Governance Cell (`wall-prefer-subagent-delegation`)**:
  - Established `.soma/cells/walls/wall-prefer-subagent-delegation.md` enforcing the Delegation-First Mandate for implementation tasks spanning $\ge 2$ disjoint files or independent modules.
  - Preserves primary orchestrator context for system architecture, cross-module integration, test verification, and staff synthesis.
  - Codifies Disjoint Lane Execution (explicit non-overlapping file scopes, model tiering, single-call fan-out, and verification against cheap-talk self-reports).
- **Genome Alignment**:
  - Updated Section 1 of `genome/subagent-delegation.md` to incorporate the Delegation-First Mandate and Single-Call Fan-Out protocol.

## [1.5.0] — 2026-10-09 — "Lifecycle Parity & Diagnostic Transparency"

### Developer Experience, Full Lifecycle Parity & Mutation Diagnostics
- **Production Status Rule Counting Parity (BUG-090)**:
  - Decoupled `_project_root` workspace resolution from `test_mode` in `soma status`. Production CLI executions now accurately count active platform rules rather than erroneously reporting `Core rules: 0 active`.
- **Symmetric Claude Platform Uninstallation (BUG-091)**:
  - Extended `soma uninstall --platform claude` to clean up the 5 starter rule `.md` files in `~/.claude/` (or `<project>/.claude/`), sanitize both target and workspace `.mcp.json` configs, and excise the git pre-commit hook block installed during `soma init`.
  - Added opt-in `--purge` flag to `soma uninstall` for explicitly removing `.soma/` governance state, while preserving `.soma/` by default.
- **Claude Rules Parity & Local Scoping in `soma init` (BUG-092)**:
  - Unified `ClaudeAdapter.render_config()` to render full rule content across both `init` and `install` workflows, eliminating truncated rule stub files.
  - Added `--local` flag support to `soma init`, allowing developers to target project-local rule directories (`<project>/.claude` and `<project>/CLAUDE.md`) in addition to default global configuration.
- **Dry-Run Output Standardization (BUG-093)**:
  - Standardized uninstallation logging across all platform adapters (`claude`, `copilot`, `mcp`) to use standard `[dry-run] Would uninstall <path>` notation instead of past-tense `"Uninstalled"` statements during `--dry-run`.
- **Telemetry Runner Safety & Missing Make Graceful Degradation (BUG-094)**:
  - Guarded Makefile discovery in outcome telemetry with `shutil.which("make")` validation, preventing failed subprocess invocations on systems lacking `make` (such as bare Windows environments).
  - Treated process exit code 127 as unverified/command-not-found rather than recording a false test failure, preventing unfair -1.0 fitness penalties across all governed cells.
  - Added `SOMA_REFLECT_ON_CLOSE` environment variable check to allow graceful opt-out of MCP server shutdown test runs.
- **Mutation Tester Diagnostic Transparency (BUG-095)**:
  - Introduced structured `TestRunResult` to capture subprocess exit codes, timeouts, and stderr details during mutation testing prerequisite baseline checks.
  - Replaced generic `"Baseline tests fail against the unmutated code"` errors with actionable diagnostic reasons (e.g. timeout duration under load, unresolved test runner binaries, or exact test assertion/traceback excerpts).

## [1.4.0] — 2026-10-09 — "Cross-Platform Execution & Safe Claude Lifecycle"

### Cross-Platform Execution, Windows Toolchain Hardening & Claude Lifecycle Parity
- **Safe Claude Configuration Lifecycle & Data Loss Prevention (BUG-088, [#142](https://github.com/nseney1/Soma-Governance/issues/142))**:
  - Delimited injected Soma instructions in `CLAUDE.md` with `<!-- SOMA:START -->` and `<!-- SOMA:END -->` markers.
  - Hardened `soma uninstall --platform claude` to parse and excise only the Soma-governed block, completely preserving user-authored custom instructions and notes. `CLAUDE.md` is deleted only if no non-Soma content remains.
  - Automatically cleans up `soma` from `mcpServers` in `.mcp.json` / `.claude.json` upon uninstallation.
- **Unified Claude Rules Directory & Path Parity (BUG-089, [#143](https://github.com/nseney1/Soma-Governance/issues/143))**:
  - Fixed `soma init --platform claude` to install rules and `CLAUDE.md` to user home (`~/.claude/`), resolving parity conflicts with `soma doctor`, `soma status`, and `soma uninstall`.
  - Replaced improper use of `args._project_root` as home override with explicit `_home` / `_home_override` test seams.
- **Rust AST Driver on Windows Python.org Installs (BUG-086, [#144](https://github.com/nseney1/Soma-Governance/issues/144))**:
  - The AST driver runner and `soma doctor` now resolve a bare `python3`/`python` driver command that is not on `PATH` to the interpreter running Soma (`sys.executable`), bypassing missing `python3.exe` on python.org Windows installations and 0-byte Windows Store execution aliases.
- **Test Harness Hardening & Symlink Fallbacks (BUG-087, [#145](https://github.com/nseney1/Soma-Governance/issues/145))**:
  - Added `anyio` to `[dev]` extras and CI pinned dependencies so `test_async_atomic_write_text` reliably executes on all environments.
  - Switched direct `symlink_to()` calls to `conftest.symlink_or_skip` so test suites pass on Windows environments without Developer Mode or administrative privileges.
- **Claude Platform Adapter Refactoring (`soma_cli/platforms/claude.py`)**:
  - Replaced deeply nested `if/elif/else` ladders in `ClaudeAdapter` with modular, single-purpose helper functions: `_inject_soma_section`, `_strip_soma_section`, `_uninstall_claude_md`, and `_clean_mcp_config`.
  - Flattened `install()` and `uninstall()` methods into linear, declarative routines with isolated exception handling.
- **AST Driver Architectural Cleanup & Deterministic Token Resolution (`soma_core/ast/runner.py`, `soma_core/ast/detect.py`)**:
  - Introduced deterministic `{python}` token support in `slots.yaml`, expanding directly to `sys.executable` across all platforms at runtime.
  - Added an in-process fast path for the bundled Rust AST driver (`rust_ast.py`), parsing Rust sources directly via `parse_rust_source` with zero subprocess overhead.
  - Purged platform-specific heuristic string sniffing (such as `windowsapps` alias detection and OS branching) from `soma_core/ast/runner.py`, restoring core engine purity. *(Note: The interim `windowsapps` string heuristic was refactored and eliminated prior to release and is not in production; v1.4.0 relies exclusively on deterministic `{python}` token expansion and in-process execution.)*

## [1.3.0] — 2026-10-08 — "Unified CLI Command Architecture & Discovery"

### Unified CLI Command Architecture, Modular Subcommands & Categorized Discovery
- **`SomaCommand` Protocol & Categorized Discovery (`soma_cli/commands/`)**:
  - Modularized monolithic CLI handlers into distinct `SomaCommand` subclasses with explicit metadata: `name`, `category` (`CommandCategory`), `description`, and `aliases`.
  - Structured all 24 commands across four decoupled domain modules:
    - `bootstrap.py`: `init`, `genesis`, `clone`, `config`
    - `inspection.py`: `status`, `list` (`ls`), `explain` (`show`), `history`, `metrics`, `doctor`, `detect` (`languages`, `drivers`)
    - `governance.py`: `propose`, `audit`, `receipt`, `freeze`, `thaw`, `adapt` (`evolve`), `export`, `import`
    - `verification.py`: `verify` (`check`), `quarantine`, `sweep`, `restore`, `checkpoint`
- **`CommandRegistry` Engine (`soma_cli/commands/__init__.py`)**:
  - Centralized registration, aliasing, and lazy instantiation for CLI commands.
  - Built-in category filtering (`get_by_category()`), alias resolution (`resolve()`), and schema discovery.
- **Orchestrator Refactor (`soma_cli/cli.py`)**:
  - Slimmed CLI entrypoint from 620 to 300 lines by delegating argument definition and execution to registry commands.
  - Enhanced `--help` formatting with clean category grouping, visual hierarchy, and alias hints.
  - Guaranteed 100% backward compatibility with existing command arguments, subparser flags, and stdout/JSON contracts.

## [1.2.1] — 2026-10-08 — "Git-Aware Polyglot Call Graph & Doctor Display Hotfix"

### Git-Aware Call Graph Boundary Discovery & Doctor Auto-Repair Fix (BUG-085)
- **Git-Aware File Discovery & Dynamic Extension Discovery (`soma_core/verification/call_graph.py`)**:
  - Replaced brittle directory blacklists with `GitWorkspace`-backed file discovery (`git ls-files --cached --others --exclude-standard`), automatically and universally respecting `.gitignore` across all project types without hardcoding compiler output names (`target/`, `.cargo/`, `bin/`, `obj/`, etc.).
  - Eliminated static hardcoded source extension sets in favor of dynamic extension resolution (`_resolve_searchable_extensions`), discovering source extensions from configured workspace slots (`.soma/slots.yaml`), active AST runner drivers, and target file metadata.
  - Implemented `_is_safe_source_file()` defense-in-depth guard rejecting files exceeding 1MB or containing binary null bytes.
- **Standalone `soma detect` Command & `soma doctor --drivers` (`soma_cli/detect.py`, `soma_cli/doctor.py`)**:
  - Added dedicated `soma detect` command (aliases: `soma languages`, `soma drivers`) allowing developers to inspect detected languages, toolchains, and AST driver bindings, and auto-provision `.soma/slots.yaml` with `--fix` independently of `soma init` or `soma genesis`.
  - Added `--drivers` flag to `soma doctor` for fast, targeted AST driver health checks without running full platform/rules/MCP audits.
- **Doctor Auto-Provision Display & Dry-Run Fixes (`soma_cli/doctor.py`, `soma_core/ast/detect.py`)**:
  - Fixed display fallthrough bug in `soma doctor --fix`: reloads `SlotRegistry` immediately after auto-provisioning so the configured polyglot driver is accurately reported rather than falling through to the native Python message.
  - Fixed `provision_ast_driver_slots` to strictly honor `dry_run=True`, preventing unauthorized directory creation or driver template copies during simulated runs.

## [1.2.0] — 2026-10-08 — "Zero-Touch Genesis Polyglot Provisioning & Rust AST Driver"

### Zero-Touch Polyglot Detection, Rust AST Driver & Release Verification Alignment
- **Zero-Touch Polyglot Provisioning (`soma_core/ast/detect.py`)**:
  - `detect_project_languages()`: Automatically detects source languages (Rust, Go, TypeScript/JavaScript, Python) by inspecting root manifests (`Cargo.toml`, `package.json`, `go.mod`, etc.) and scanning project source trees.
  - `provision_ast_driver_slots()`: Proactively configures `.soma/slots.yaml` with recommended driver commands and stages reference driver files into `.soma/drivers/` with full dry-run support.
- **CLI Workflows Integration (`soma_cli/`)**:
  - `soma init`: Automatically detects project languages and provisions polyglot AST driver slots during repository initialization.
  - `soma genesis`: Seamlessly auto-provisions AST drivers during initial repository scan and reports status in console and JSON output.
  - `soma doctor --fix`: Identifies unconfigured AST drivers for non-Python sources in the workspace and repairs them with `--fix`.
- **Reference Rust AST Driver & Template Bundling**:
  - Pure Python stdlib regex/block parser (`rust_ast.py`) producing `NormalizedAST` JSON with functions, structs, impls, modules, macros, and mutation points without external pip dependencies.
  - Bundled driver templates in `soma_core/ast/drivers/templates/` and installer recipe in `install/drivers/rust_ast.py`. Added package data distribution in `pyproject.toml`.
- **CI/CD & Release Verification Alignment (BUG-084)**:
  - Fixed `soma verify --layer1-only` in release tag publishing workflows by propagating resolved `diff_base` to `soma_core.verification.runner.run_layer1()` and adding `HEAD~1` fallback in `_get_modified_lines()`.
- **Architecture Decision Record (ADR)**:
  - `docs/architecture/decisions/ADR-016-zero-touch-polyglot-genesis.md`: Documents design trade-offs, language detection heuristics, and template installation paths.

## [1.1.0] — 2026-10-08 — "Language-Agnostic AST Verification via Normalized AST Drivers"

### Polyglot Verification, Normalized AST Drivers & Zero-Dependency Schema
- **Normalized AST Driver (NAD) Protocol (`soma_core/ast/`)**:
  - `soma_core/ast/schema.py`: Language-agnostic intermediate representation defining `NormalizedAST`, `DefinitionNode`, `CallSiteNode`, `ImportNode`, and `MutationPoint` with JSON and mapping roundtrip serialization.
  - `soma_core/ast/drivers/python.py`: In-process native Python standard library parser (`ast.parse`) providing a sub-millisecond fast path with zero process overhead.
  - `soma_core/ast/runner.py`: External process execution engine (`ASTDriverRunner`, `ASTDriverRegistry`) resolving drivers via `.soma/slots.yaml` or code registry with strict 3.0-second timeout enforcement and workspace confinement.
- **Layer 1 Polyglot Call Graph & Mutation Adaptation (`soma_core/verification/`)**:
  - `soma_core/verification/call_graph.py`: Implements `check_normalized` to verify function call reachability, detect orphan deadwood, and ignore comments and string literals across polyglot files.
  - `soma_core/verification/mutation_tester.py`: Adds `apply_mutation_point` and `collect_mutations_from_ast` supporting byte-offset and coordinate operator swaps on non-Python sources.
  - `soma_core/verification/runner.py`: Automatically routes changed polyglot files through configured AST drivers.
- **Host Driver Recipes (`install/drivers/`)**:
  - `install/drivers/ts_ast.js`: Zero-dependency Node.js recipe for TypeScript and JavaScript using the official `typescript` compiler API when present and falling back to a deterministic built-in lexer in bare environments.
  - `install/drivers/go_ast.go`: Zero-dependency Go recipe leveraging standard library `go/parser`, `go/token`, and `go/ast`.
- **Doctor Diagnostics & Architecture Documentation**:
  - `soma_cli/doctor.py`: Added `_check_ast_drivers` diagnostic verifying that configured AST driver binaries are resolvable on PATH.
  - `docs/guides/polyglot_ast.md`: Comprehensive developer guide for authoring and configuring custom AST drivers.
  - `docs/architecture/decisions/ADR-015-normalized-ast-driver-protocol.md`: Architectural Decision Record codifying the NAD protocol and trade-offs.

## [1.0.0] — 2026-10-08 — "General Availability & Production Governance Framework"

### Production GA, Documentation Portal & Formal Backwards Compatibility
- **Lean Documentation Portal (< 200 Lines)**:
  - Restructures root `README.md` into an immediate, above-the-fold portal with 30-second quickstart, closed-loop architecture diagram, and deep-dive documentation guide cards.
- **Production Architecture & Operations Guides (`docs/guides/`)**:
  - `docs/guides/mcp_gateway.md`: Dual-Plane Gateway architecture, tool tiers, receipt security, and opt-in projection.
  - `docs/guides/verification_pipeline.md`: Two-Layer Verification engine, deterministic Layer 1 AST checks, Layer 2 Adversarial Rebuttal, and Gate 4.5.
  - `docs/guides/cell_lifecycle.md`: Five cell types, evolutionary lifecycle, Wilson-bounded fitness scoring, and zero-touch decay.
  - `docs/guides/skill_graph.md`: Horizontal skill graph, typed envelopes (<150 tokens), and file-buffered handoffs.
- **SemVer 2.0 Backwards Compatibility Guarantee (`docs/project/COMPATIBILITY.md`)**:
  - Codifies formal public API contracts across CLI, Python SDK (`soma_sdk`), MCP Server (`soma_mcp`), and Core Governance schemas starting at `v1.0.0`.
- **Checkpoint Candidate Resolution**:
  - Updates verification test candidate resolution in `soma_core/verification/checkpoint_checks.py` to recognize relocated domain hierarchy suites.

## Before 1.0.0

Releases 0.1.0 to 0.123.0 (2026-09-26 to 2026-10-08) were published under the Soma name. Their notes are not repeated here: `git show v3.3.0:docs/project/CHANGELOG.md` prints the full changelog as it stood at 3.3.0, and `git tag --list 'v0.*'` lists the tagged releases (v0.15.0 and later).

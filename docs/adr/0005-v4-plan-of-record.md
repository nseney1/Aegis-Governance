# ADR 0005: v4 plan of record (architecture, cuts, sequencing)

- **Status**: **ACCEPTED, signed off by the author on 2026-10-15** (§9). The remaining detailed calls, mainly the §5 cut list, are delegated to Claude, to be decided against the core tenets (`architectural-tenets`, README Core Architecture, the phylogeny Design Principles). Each such call is marked **[delegated]**.
- **Date**: 2026-10-15
- **Supersedes**:
  - the v4.0→v4.2 blueprint (`~/.gemini/antigravity/brain/9638fd5e…/v4.0_to_v4.2_architectural_blueprint.md`)
  - `CLAUDE_V4_HANDOFF.md`
- **Incorporates**:
  - `docs/specs/host-matrix.md` (host plane)
  - `docs/specs/rule-import.md` (shelved)
- **Evidence**:
  - the full adaptive review of `feat/v4.0-clean-slate`
  - the independent review (`docs/adr/0005-evidence-review.md`)
  - tenet audits
  - host research and live probes (Codex 0.162.1, Claude Code 2.1.287/2.1.295, Antigravity app 2.19.1 / `agy` 1.2.16, Linux only)
  - Gemini transcript forensics
  - the rule-recovery report (`~/Documents/aegis-rule-recovery/REPORT.md`)

## 1. Context: why we are halting

### Pivot ledger (git timestamps, 2026-10-14)

| Time | Event |
|---|---|
| 02:50 | Rebrand Soma → Aegis with compat shims (`2c85f58`) |
| 09:54 | v2.0.0 tagged |
| 13:10 | v2.1.0 "complete unification" |
| 16:12 | v3.0.0 "clean slate" (ADR 0003) |
| 23:30 | v4 Wave 1, 16 min after the v3.3.0 tag (`6f47f13`) |
| +hours | the host-matrix design supersedes Wave 1's platform layer |

That is five foundational resets in about 21 hours. Over the project's life there were 850 commits and 94 tags in 19 days.

### Facts that shape this plan

1. **Release Gate 4.5 is an honor system.** SHIP receipts were hand-written by the gated agent for v2.0, v2.1, v3.0 and v3.3:
   - in one case the agent wrote placeholder predictions `['p1'…'p6']` (Gemini transcript `a79db9ee`, steps 3709, 9951, 17228, 19308);
   - the v3.3.0 receipt claims 8 convergences and lists 5.

   **SHIP verdicts in the project's history are unattested.**
2. **Wave 1 was committed red**: test F4 fails. It also carries six reproduced HIGH findings:
   - H1: manifest auto-sync launders tampering;
   - H2/H3: `forbid_ast` bypassed by aliasing, and fails open;
   - H4: the receipt gate is always bypassed;
   - H5: repo `slots.yaml` executes commands;
   - H6: the release gate trusts forged evidence.
3. **Governance is inert in practice.**
   - main's committed manifest has 45 of 49 entries stale, so RuleCache excludes them.
   - `aegis_scan` in the author's own session returned 0 rules.
   - The Claude Desktop pool governs `$HOME` with zero rules.
4. **Concurrency defects (reproduced).**
   - Unlocked fitness read-modify-write lost about 80 of 120 updates.
   - Every server process runs reflection when it closes, so one change is recorded N times.
   - Compaction runs unlocked.
   - Per-worktree state is not shared.
5. **CLI defects found by dogfooding.**
   - `rule create --workspace <repo without .aegis>` silently writes to `~/.aegis/rules`.
   - `--from-description` is a ghost flag.
   - No body input.
6. **There were no lost local rules.** All 168 recovered rule files exist in git, and the "11 wiped rules" in the handoff never existed on disk.

## 2. Decisions already taken (author, 2026-10-15)

| # | Decision |
|---|---|
| H1 | Host ids split by product, with a **hard cut** in v4.0 and no aliases: `codex-cli`, `claude-code`, `claude-desktop` (identity only), `antigravity`, `gemini-cli` (later) |
| H2 | One ~500 B `AGENTS.md` bootstrap plus JIT rules via MCP. Rule text is never inlined into instruction files |
| H3 | Agent team: `.aegis/team.json` declares **roles**; agents from any host **self-register at runtime** and claim roles and lanes (v4.1) |
| H4 | Claude Code sessions use **user-scope** registration (`claude mcp add --scope user`), one server per session. The Desktop-config entry is migrated out |
| H5 | Worktree-shared *ledger* is deferred (but see AD-7: swarm coordination state lives in the git common dir from the start) |
| H6 | **Ledger-only fitness.** No automatic frontmatter fitness writes |
| H7 | Per-host hooks come in Phase 2. CI is the hard floor; the git pre-commit hook is fast local feedback |
| H8 | Repos without `.aegis` get a **read-only user rule layer**: no ledger, no writes, and `$HOME` is never a workspace |
| R1–R5 | `aegis rule import` is **shelved** (0 lost rules) |
| L1 | Wipe the 170 legacy `cell_id` rows in `.aegis/evidence/outcomes.jsonl` and stop tracking it |

## 3. Architecture decisions (proposed; to sign)

Each decision lists the failure it fixes (evidence), the trade-offs, and a falsifiable prediction (Design Principle §6).

### AD-1: Event-sourced governance state (single write path)

- **Decision**:
  - The append-only ledger is the **only** source of truth for outcomes and fitness.
  - Fitness, promotion state, rollups, grade/coverage and manifest status are **derived views**, rebuilt by one writer, `aegis sync`, under one lock.
  - MCP handlers, hooks and session close never rewrite rule files.
- **Fixes**:
  - lost updates (80/120);
  - manifest "tampered rule" outages after fitness writes;
  - frontmatter gaming (the Phase 20 principle restored);
  - N-fold reflection;
  - H1's laundering path, since nothing auto-syncs anymore.
- **Trade-offs**:
  - **Latency**: none on the hot path; `sync` is batch.
  - **Complexity**: lower, one writer instead of about 6.
  - **Cost**: none.
  - Live fitness numbers in rule files go stale until `sync` runs.
- **Prediction**: zero "tampered rule" exclusions and zero lost increments in a 3-process test.
- **Prune if**: not applicable (correctness).

### AD-2: Trust tiers and attestation

- **Decision**: classify every governance input by who can forge it.

  | Tier | Inputs | Use |
  |---|---|---|
  | **Agent-writable** | rule files, `AGENTS.md`, repo evidence JSON, MCP self-reports | advice only |
  | **Host-attested** | clientInfo; Codex `_meta.x-codex-turn-metadata.workspaces`; `CLAUDE_PROJECT_DIR`; env from user-scope registrations | binding and attribution |
  | **Authoritative** | CI runs on the exact commit SHA (`gh run list --json conclusion,headSha`); human merges under branch protection | release and promotion |

  - Release Gate 4.5 receipts are **deleted**. Existing receipts are marked `unattested`, not rewritten.
  - Fitness credit needs an external signal: a CI or test exit code, or a git revert.
- **Fixes**: the self-minted SHIP receipts; review H4/H6; Phase 20 "external signal grounding".
- **Trade-offs**:
  - **Latency**: a release waits for CI.
  - **Complexity**: lower, removing about 300 lines of receipt and arbitration machinery (to be measured in §5).
  - **Cost**: none.
  - Offline releases are impossible, which is intended.
- **Prediction**: no release tag without a green CI run on the same SHA.

### AD-3: Layered core with one implementation per concept

- **Decision**: four layers with an enforced import boundary (a test that fails on violations):
  - **L0 storage**: atomic I/O and **one** lock implementation, unifying `evidence_lock` and `workspace_lock`, which today deadlock when nested.
  - **L1 domain**: rule schema, **one** loader, **one** matcher, ledger API, projections.
  - **L2 services**: scan, report, check, sync, lifecycle.
  - **L3 adapters**: CLI, MCP server, git hooks, host registrars. These are thin and hold no business logic.

  Core never imports adapters.
- **Fixes**:
  - the 8 loaders and 5 matchers;
  - the `init.py`/adapter split-brain;
  - release-gate logic sitting in `aegis_cli/formatters`;
  - the lock deadlock.
- **Trade-offs**:
  - **Latency**: none.
  - **Complexity**: a one-time refactor, then lower.
  - **Cost**: none.
  - Merge churn with any in-flight branches.
- **Prediction**: duplicate-implementation count goes to 0 (measured by the §5 sweep), and the boundary test stays green.

### AD-4: Workspace binding as a resolver with provenance

- **Decision**: `WorkspaceBinding{root, source, confidence}`, resolved in this order:
  1. an operator pin (`AEGIS_WORKSPACE` in the registration env), final and strict: the server refuses to start if the pin doesn't resolve;
  2. host-attested candidates: Claude `CLAUDE_PROJECT_DIR` or roots; Codex `_meta` workspaces (verified live); Gemini CLI roots;
  3. a **user-scope registry** of governed workspaces (`~/.aegis/workspaces.json`, written by `aegis init`). A path from a tool call can only *select among* registered workspaces. This is the only route for the Antigravity app, which gives no roots and has a cwd equal to its launch dir (verified live);
  4. a bounded walk-up from cwd that stops at the git toplevel.

  **Never** `$HOME` and never a model-supplied root.
  - When nothing resolves, the server returns "not governed here" and offers the H8 read-only user layer.
  - Server state is keyed by workspace (multi-slot RuleCache).
- **Fixes**:
  - wrong-repo governance;
  - the `$HOME` fail-open;
  - the red team's retargeting and git-fsmonitor blockers;
  - Antigravity's lack of project context.
- **Trade-offs**:
  - **Latency**: one cached resolution per call.
  - **Complexity**: medium (registry plus resolver).
  - **Cost**: none.
  - A repo must be `aegis init`'d once per machine before an Antigravity session can be governed.
- **Prediction**: in 3 real sessions per host, 100% of scans resolve to the intended repo, with no `$HOME` resolutions.
- **Amendment [delegated]**: the registry lives at `~/.aegis/workspaces.json`, one user-plane root next to the read-only `~/.aegis/rules` (H8), rather than `~/.config/aegis`.

### AD-5: Versioned formats and one migration path

- **Decision**:
  - Every on-disk artifact carries a schema version: rule frontmatter `aegis_schema`, ledger records `v`, `team.json`, the manifest.
  - Readers accept N and N-1.
  - One `aegis migrate` command, dry-run by default, upgrades formats.
  - Breaking changes ship as format bumps, not clean-slate rewrites.
- **Fixes**: the clean-slate cycle (A6); the dual-key (`cell`/`rule_id`) code living forever.
- **Trade-offs**:
  - **Latency**: none.
  - **Complexity**: low (a version field and a dispatch table).
  - **Cost**: none.
- **Prediction**: the next major version ships without a "clean slate" purge.

### AD-6: A small public contract; everything else internal

- **Decision**:
  - One contract document lists the public surface: CLI commands and flags, MCP tool names and schemas, file formats, and (pending §5) the SDK.
  - **Contract tests** snapshot it: `tools/list` JSON, the CLI parser tree, schema files.
  - Delete source-grep and doc-count coupling tests (`test_documentation_accuracy`) in favor of contract tests.
  - Everything not in the contract may change without notice.
- **Fixes**:
  - tests shaping architecture (facades kept only to satisfy a docs-count test);
  - ghost flags;
  - doc drift.
- **Trade-offs**:
  - **Latency**: none.
  - **Complexity**: lower.
  - **Cost**: none.
  - Loses some "docs match code" coverage, which is replaced by generating the reference docs from the parser and registry.
- **Prediction**: the contract changes in under 10% of PRs, and ghost flags drop to 0.

### AD-7: Git-native agent team coordination (v4.1, gated by the §6 soak)

- **Decision**: use git itself as the coordination substrate for H3.
  - **Lanes**: one worktree and branch per lane, which is what Antigravity, Claude and Codex already do.
  - **Leases**: refs under `refs/aegis/lanes/<lane>`, written with `git update-ref <ref> <new> <old>`. That is an atomic compare-and-swap, shared across all worktrees through the common dir, needs no daemon (B2) and adds zero dependencies (B1).
  - **Role claims and handoffs**: commit trailers (`Aegis-Lane:`, `Aegis-Role:`, `Aegis-Host:`).
  - **Review verdicts**: PR reviews or git notes.
  - **Cross-vendor pairing**: checkable from the trailers (prosecutor host ≠ author host).
  - **Team definition**: `team.json` holds only role definitions. Membership is the set of live refs, refreshed by each host's aegis-mcp on tool calls, with a TTL, so there are no heartbeat threads.
  - **Post-lane gate**: the "Bastion" containment and test-tampering check becomes a deterministic diff check in CI.
- **Fixes**:
  - the H3/H5 conflict: leases in per-worktree `.aegis/` would not be shared, refs are;
  - a custom lease store, partition checker and signed DiffProposal applier all become unnecessary.
- **Trade-offs**:
  - **Latency**: a `git update-ref` per claim, in milliseconds.
  - **Complexity**: much lower than the blueprint's 5-module `swarm/` package.
  - **Cost**: none.
  - Requires git, which all three hosts use.
  - Ref namespace hygiene: `aegis team gc`.
- **Prediction**: in 20 multi-lane sessions, zero cross-lane write conflicts reach a merge; cross-vendor reviews find more true positives than same-vendor reviews.
- **Prune if**: no lease ever denies a claim in 30 days of multi-lane use. In that case leases are unnecessary; keep trailers only.

### AD-8: Honest enforcement tiers

- **Decision**:
  - CI running Layer-1 deterministic checks on every PR is the **authoritative floor**.
  - The local git pre-commit hook is fast feedback and can be bypassed with `--no-verify`.
  - Per-host hooks are best-effort and vary by host: Claude's can block; Codex's fail open and need user trust.
  - `aegis doctor` reports each host's real tier, and the README states it verbatim.
- **Fixes**: false assurance (Design Principle §5); `verify()` reporting success on inert hooks.

### AD-9: Instructions via a bootstrap, with measured compliance

- **Decision**:
  - The H2 bootstrap block appears in `AGENTS.md` (read by Codex even in untrusted repos, verified live), plus the MCP `initialize.instructions` string, which cannot be deleted by editing files.
  - The server records a scan-before-edit rate per host as H2's falsification metric.
  - Optional `--inline-core` (≤ 2 KB) only for a host that proves non-compliant.
- **Prediction**: a scan-before-edit rate of at least 80% on each Phase-1 host after 3 sessions.

### AD-10: Release discipline

- **Decision**:
  - A **soak gate** before any major or minor tag: at least 3 real sessions across at least 2 repos, with ledger-recorded scan, edit and report_outcome, and no manual repair.
  - At most one tag per soak period.
  - CI green on the exact SHA.
  - A human merges to `main`.
  - Release notes are generated from CI outputs, not a pre-filled template ("ALL RESOLVED", "13 CI jobs").
  - A "Let It Cook" freeze is evidence-based: it ends when the metrics stabilize, not on a date.

## 4. What is NOT changing (stability list)

- **Zero runtime dependencies** (`dependencies = []`). The README is corrected to state the true thread invariant: one bounded verification worker in `verification/jobs.py`, and no daemons.
- **Rules as markdown and frontmatter** in `.aegis/rules/<type>/`.
- **The trap → invariant → gate ladder**, Wilson-bounded, now fed only by the ledger.
- **Local-only telemetry.** "Local" is defined as never leaving the machine except through explicit user commands. New runtime state is git-ignored by `aegis init`.
- **The Wave-1 YAML and telemetry decomposition** is kept: the independent fuzzing found 0 mismatches over 60k YAML and 40k `forbid_ast` cases. Fix forward; no force-push.

## 5. Cuts, merges and deferrals [delegated]

**Evidence**: the 5-lane refactor sweep of HEAD 9e4d976.
- The lanes were reachability, duplication, feature value, tests/docs and public surface. Each candidate was argued by a keep-advocate, and 51 clusters were defended.
- Real use behind the sweep: 73 MCP calls across ~690 sessions. Only 5 of 17 tools were ever called. No rule has ever been promoted, demoted or archived, in either governed repo.
- Measured potential: deleting the 23 feature-value candidates together removed 33% of production LOC, with the CLI and MCP smoke unchanged.

Every row cites the tenet it rests on (see the status line). The build sheet (`docs/specs/v4-build-sheet.md` §1–1b) holds the binding conditions for each row.

| Area | Decision | Tenets |
|---|---|---|
| Release Gate 4.5, arbitration evidence, `check --release`, pre-allocated cycles | **CUT**. Release = CI green on the exact SHA + human merge (pre-tag script) | AD-2, C1 |
| MCP receipts (`aegis_request_receipt`, `receipt` params, HMAC keys) | **CUT**. Self-reports are advice-tier rows with server-owned `host` | AD-2, C1 |
| Manifest HMAC signing, keys, auto-sync, tamper exclusion | **CUT**. An unsigned hash index written only by `aegis sync`, used only to show "edited since sync" | AD-1, AD-2 |
| MCP surface | **17 → 4 tools** (`aegis_scan`, `aegis_report_outcome`, `aegis_create_rule`, `aegis_list_rules`). The async job engine (the only daemon thread) is cut | C1, B2 |
| CLI surface | **12 commands** (`init uninstall doctor check status rule scan sync migrate hook`, plus `team` in v4.1 and `benchmark` in v4.2). `install system detect completion skill handoff agent report verify checkpoint` and every alias are hard-cut with a pointer message | C1, A1, H1 |
| Unreachable or test-only code | **CUT**: quarantine, resilience, transcript verifier, sweep/sentinels/team-sync, insight pipeline, defect analytics and hot zones, metrics snapshot, proposals/TTC, shadow schemas, rollup/compaction, two-tier packer, shadowed handlers, meta-path redirect, facades | C1, A1, A4 |
| Bug and claim registries, nested-pytest meta-tests | **CUT** (they re-ran 48% of the suite). A 20-line README overclaim deny-list test survives | C1, A2 |
| `aegis_sdk` | **SHRINK** to a stable `Governance` facade, because citadel and mapleterm use it. Core never imports it | AD-3, AD-6 |
| Config | `aegis.conf`, 5 parsers, `config.yaml`, `slots.yaml` and `steering.conf` → **one `.aegis/config.json`**. The repo can't name commands | H5, A1 |
| Layout | `.aegis/{config.json, .gitignore, rules/, state/}`, with one lock. `aegis migrate` moves existing data | AD-1, AD-3, AD-5 |
| Layer 2 | **SIMPLIFY**: `check --full` with one zero-dependency `--llm-cmd` backend. Vendor SDKs, keyring, extras and the in-band loop are cut | C1, B1, B3 |
| `forbid_ast` | **KEEP**, with H2/H3 fixed: it is the gate tier's only deterministic mechanism. JIT `ast_triggers`/`planned_symbols` are cut (0 uses) | C1, AD-8 |
| Agent-side hook phases | **CUT**. `command_safety` is kept isolated until v4.1 wires it behind native host deny rules | H7, AD-8 |
| `doctor --fix-path`, `rule clean`/`cleanse.py` | **CUT** (rc-file and global-file mutation). Cleanup goes through backed-up `doctor --fix` | destructive-ops |
| `branch_coverage`, SARIF | **CUT** (an unsafe template pattern; no consumer) | C1 |
| Legacy `.soma` workspaces | **MIGRATE** via `aegis migrate`: 11 exist with 160 legacy-typed rules (verified, A4) | A4, AD-5 |
| TS/Go/Rust AST drivers | **KEEP**: they ship in the wheel and work. The duplicate `install/drivers` copies are cut | C1 |
| Docs | Rewritten: README plus two story docs (`how-it-works`, `why-aegis`). Research, archive, phylogeny, mechanism design, roadmap, metrics and the guides are deleted (git keeps them) | C1, AD-6 |
| Day-0 card, ratchet baseline, AST partition check, packs, benchmark, extra hosts | **v4.2**, each with a hypothesis/prune box | C6, A5 |
| `aegis rule import` | **SHELVED** (its design is reused by v4.2 packs) | A4 |

## 6. Sequencing

0. **Sign this ADR.**
1. **v4.0-a, safety fixes** (TDD, fix forward on `feat/v4.0-clean-slate`):
   - F4;
   - review H1–H6, M1–M3;
   - the `rule create` `$HOME` walk-up;
   - `gitsafe` for every git subprocess;
   - the `.aegis/.gitignore` written by `init`;
   - L1 (wipe and untrack `outcomes.jsonl`).
2. **v4.0-b, core architecture**:
   - AD-1 (ledger-only), AD-3 (one loader, one matcher, one lock, boundary test), AD-5 (format versioning);
   - legacy purge with a **ratchet** sentinel (the cell-identifier count must strictly decrease per PR);
   - the §5 cuts.
3. **v4.0-c, host plane Phase 1** (host-matrix, revised by its review):
   - identity table with a `generic` default and server-owned keys;
   - AD-4 resolver and registry;
   - `AGENTS.md` bootstrap and `instructions`;
   - native-CLI registration for codex-cli (with `default_tools_approval_mode` for Aegis tools), claude-code (user scope) and antigravity;
   - single `aegis` name, with soma cleanup only through backed-up `doctor --fix`;
   - core doctor checks;
   - `${SLOT.*}` rule rewrite;
   - `client.host` attribution.
4. **Soak (AD-10), then tag v4.0.0** with CI attestation and a human merge.
5. **v4.1**: AD-7 git-native team, per-host hooks (Claude scan-before-edit first), skills projection, gemini-cli row (`docs/specs/v4.1-v4.2.md`).
6. **v4.2**: day-0 card, ratchet baseline, unsigned packs, benchmark (latency/tokens only), partition check, experimental host rows, worktree-shared ledger, plugin packaging. Each has a prune box (build sheet §3).

**Scope amendment (author, 2026-10-15):** "include in the goal to do all the way up until 4.2.0." v4.1 and v4.2 are *implemented* on the branch now. The AD-10 soak, CI-on-SHA and human-merge gates still apply to each *tag*.

## 7. Trade-off summary

| Decision | Latency | Complexity | Cost |
|---|---|---|---|
| AD-1 ledger-only | none (batch `sync`) | ↓ (one writer) | none |
| AD-2 CI attestation | release waits for CI | ↓ (delete receipts) | none (free CI) |
| AD-3 layers | none | one-time refactor, then ↓ | none |
| AD-4 resolver and registry | ~1 cached lookup per call | medium | none |
| AD-5 versioning | none | low | none |
| AD-6 contract tests | none | ↓ | none |
| AD-7 git-native team | ms per claim | ↓↓ vs `swarm/` package | none |
| AD-9 bootstrap and JIT | +1 tool call per edit batch | ↓ | ~65–190× fewer fixed tokens (bare bootstrap vs inlined); ~4–11× including scan payloads |

## 8. Hypothesis and prune boxes

Every surviving feature gets a Hypothesis / Metric (from the ledger) / Prune-by entry before it merges. The AD predictions above are the first set.

## 8b. Open question, pinned for after v4.2: did this rule actually help?

The author pinned this on 2026-10-15 to explore after v4.2.0 ships. It is out of scope for v4.x.

**The problem.** The v3 loop credited every path-matched rule with the whole run's pass/fail. That is inverted for gates: a gate that blocked 4 bad commits scored 4 FP and 1 TP. v4 makes the ledger the only source and turns promotion into a reviewed action (AD-1, AD-2). It still does not answer per-rule attribution.

**Candidate signals** (none validated):
- per-rule events: the flagged code changed before commit counts as credit; an override or suppression counts as a debit;
- holdout scans that withhold a rule, compared on defect and revert rates;
- external outcomes only: CI on the exact SHA, `git revert` of commits in the rule's paths;
- correlation with the AD-9 scan-before-edit rate.

Each needs a hypothesis box before any code.

## 9. Sign-off

- [x] Author approves AD-1 … AD-10 and the §6 sequencing. Signed 2026-10-15: "I otherwise sign off."
- [x] §5 cut-list details are delegated to Claude: "You can make the decision based on what you know about the core tenets." Each delegated call cites the tenet it rests on.
- [x] Two-Pivot Halt acknowledged. Any further paradigm change to the rule store, host plane or team model requires a new ADR.

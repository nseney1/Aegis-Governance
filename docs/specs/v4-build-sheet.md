# v4 build sheet (v4.0 → v4.2)

- **Status**: working document for implementation, 2026-10-15. Decisions here are the **[delegated]** calls from ADR 0005 §5, plus the author's 2026-10-15 extension of scope through v4.2.0. The docs wave folds this sheet into ADR 0005 and the CHANGELOG, then deletes it.
- **Base**: `feature/v4.0` forked from `9e4d976` (fix forward on Wave 1). A human merges to `main`. Tags wait for the AD-10 soak.
- **Inputs**:
  - ADR 0005;
  - `docs/specs/host-matrix.md` (v2);
  - the independent review (H1–H6, M1–M7, LOW);
  - the adaptive Citadel review;
  - the 5-lane refactor sweep (reachability, duplication, feature value, tests/docs, surface) with keep-advocate defenses;
  - the docs inventory.

## 0. Lane protocol (every coding lane)

1. Work in your own worktree at `/home/nseney/Documents/aegis-lanes/<lane>`, on branch `lane/<lane>` created from the base SHA given in the brief: `git -C /home/nseney/Documents/Aegis-Guardrails-v4 worktree add -b lane/<lane> /home/nseney/Documents/aegis-lanes/<lane> <base>`. Never edit `/home/nseney/Documents/Aegis-Guardrails-v4` or the main checkout.
2. Touch only the files your brief owns. To change a file outside that list, stop and report it.
3. Follow TDD (rules `tdd-protocol`, `core-change-protocol`): write tests first and watch them fail for the right reason, then implement, then go green. State the red and green evidence in the debrief.
4. Run the tests:
   ```
   H=$(mktemp -d); HOME=$H XDG_CONFIG_HOME=$H/.config PYTHONUSERBASE=/home/nseney/.local python3 -m pytest <paths> -q -p no:cacheprovider
   ```
   Always use `python3 -m pytest` from the lane root (`pythonpath=["."]` makes it import the lane's code). The full suite takes about 7 minutes serially. Run it once at the end of the lane.
5. Commit on `lane/<lane>` with Conventional Commits and the trailer `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Do not push, merge or rebase other branches.
6. Debrief:
   - files changed;
   - tests added and removed, with counts;
   - red and green evidence;
   - full-suite result;
   - anything skipped;
   - assumptions.

## 1. Delegated decisions (cite tenets)

**Tenet keys**:
- A1–A7 `architectural-tenets`: pragmatism, trade-offs, scale-to-zero, verify artifacts first, prove before generalizing, two-pivot halt, no blocking inference in loops.
- B1–B3 README Core Architecture: zero dependencies, zero daemons and threads, local privacy.
- C1–C7 phylogeny Design Principles: evidence over intuition, accuracy over speed, rules as a system, continuous validation, installation completeness, hypothesis-driven, ledger-not-frontmatter fitness.

| # | Decision | Tenets |
|---|---|---|
| D1 | **Promotion is a reviewed change.** `aegis sync` only rebuilds derived state and *suggests* transitions. `aegis sync --apply` or `aegis rule promote/demote/archive` apply them. Ledger fitness ranks JIT output (advice tier). It never auto-promotes from a self-report. | AD-2, C1, C7 |
| D2 | **No MCP receipts.** `aegis_request_receipt`, the `receipt` parameter, `receipts.py` and the receipt keys are deleted. Self-reports are stored with `source: "mcp"` and the server-owned `host`. | AD-2, H4 |
| D3 | **Unsigned manifest.** HMAC signing, the keys, rotation and auto-sync are deleted. `aegis sync` writes a sha256 index into `.aegis/state/derived.json`, and RuleCache uses it only to flag "edited since last sync". SECURITY.md says plainly that rules are protected by git review and CI, not by Aegis. | AD-1, AD-2, H1 |
| D4 | **MCP surface is 4 tools**: `aegis_scan`, `aegis_report_outcome`, `aegis_create_rule`, `aegis_list_rules` (with fitness). The other 13 are cut. Of all recorded calls, 12 of 17 tools have none. The async job engine (the only daemon thread) goes too. `view` stays, while `fields`, the alias keys and the `soma_*` names go. | C1, B2 |
| D5 | **CLI surface**: `init`, `uninstall`, `doctor`, `check`, `status`, `rule`, `scan`, `sync`, `migrate`, `hook` (v4.0); `team` (v4.1); `benchmark` (v4.2). Global flags: `--json`, `--plain`, `--workspace`. Cut, with no aliases (H1 hard cut): `install`, `system`, `detect`, `completion`, `skill`, `handoff`, `agent`, `report`, `verify`, `checkpoint` and every alias. Each removed name exits 2 with a one-line pointer to its replacement. | C1, A1, H1 |
| D6 | **Release Gate 4.5 is deleted**: `check --release`, the arbitration evidence files and `review_adapter`'s cycle and save functions. Release discipline is CI green on the exact SHA plus a human merge (AD-10), which the shipped `ci-green-before-release` rule already states. | AD-2, H6 |
| D7 | **Unreachable or test-only code is deleted** (sweep reachability plus duplication): `quarantine`, `resilience`, `transcript_verifier`, `sweep_session`, `sentinels`, `sync.py`'s team-sync and sweep, insight clustering and the insight pipeline, `defects` analytics and hot zones, `metrics` snapshot and token census, `harvest_git_history`, the `proposals` checkpoint, TTC and `propose_change`, the shadow `schemas`, telemetry rollup and compaction, the two-tier packer, the shadowed handler copies, the `aegis_core/__init__` meta-path redirect, the lazy exports and every re-export facade. | C1, A1, A4 |
| D8 | **Bug and claim registries** are deleted, along with their verifiers, CI steps and the nested-pytest meta-tests (1,581 re-executions per run). The `trap-bugfix-without-regression-test` rule covers the discipline. | C1, A2 |
| D9 | **`aegis_sdk` shrinks to a thin, stable facade.** The keep-advocate found two external consumers, citadel `fleet_telemetry.py` and mapleterm `telemetry.py`, calling `Governance.grade/coverage_report/scan/entropy`. The SDK keeps `Governance` (those 4 plus `list_rules` and `fitness_landscape`) and `parse_rule_file`, all wrappers over `aegis_core` services. Every other SDK module is deleted. `aegis_core` never imports `aegis_sdk`, and the boundary test enforces it. | AD-3, AD-6, C1 |
| D10 | **One config file**: `.aegis/config.json` (committed). It replaces `aegis.conf`, its 5 parsers, `.aegis/config.yaml`, `.aegis/slots.yaml` and `steering.conf`. Repo config **cannot** name commands or tool slots: AST driver commands come only from packaged templates or the user-scope `~/.aegis/config.json`. | H5, A1, B3 |
| D11 | **Env vars** are cut to `AEGIS_WORKSPACE` (operator pin), `AEGIS_CLIENT` (host identity, written by `init`), `AEGIS_MAX_JIT_TOKENS` and `AEGIS_LLM_CMD` (the Layer-2 backend). | A1 |
| D12 | **Layout** is `.aegis/{config.json, .gitignore("state/\n"), rules/<type>/, state/{ledger.jsonl, derived.json, lock}}`. The user plane is `~/.aegis/{rules/ (read-only layer, H8), workspaces.json (AD-4), backups/}`. The **one lock** is `.aegis/state/lock`. | AD-1, AD-3, AD-4 |
| D13 | **Ledger rows are versioned**: `{"v":2,"ts","rule","outcome","source","host","session","key",…}`. Readers accept v1 (the `cell`/`rule_id` keys). `aegis migrate` (dry run by default, `--apply`) upgrades rows and the layout, and converts `aegis.conf`/`slots.yaml`/`config.yaml` into `config.json`. Writes are always v2. L1: the 170 legacy `outcomes.jsonl` rows are wiped and the file is untracked. | AD-5, A4 |
| D14 | **Verification**:<br>• **Layer 1** (`aegis check`) keeps the checkpoint checks, `forbid_ast` (fixed, not cut: it is the gate tier's only deterministic teeth) and `call_graph`/`import_guard`. Assertion density moves to `quality_gate`'s AST checks plus `check_no_bare_pass`, skipping fixtures.<br>• **Layer 2** (`aegis check --full [--plan/--plan-file]`) keeps `adversarial_verify` + `arbiter` + `mutation_tester` with **one zero-dependency backend**: `--llm-cmd CMD` / `AEGIS_LLM_CMD`. The command (argv, no shell) receives the prompt on stdin and returns stdout, for example `codex exec`, `claude -p` or `gemini -p`, which gives cross-vendor review with no keys or packages in Aegis. `--full` without a backend exits 2. The command is never read from workspace config (BUG-073 guard).<br>• **Cut**: the Gemini, Anthropic and OpenAI SDK wrappers; keyring; the extras; `PromptOnlyProvider`; the in-band charge sheet and `--in-band`; the cloud oracle; `MCPSamplingBackend`; `attribution.py`; `run_layer2` (keep `_strip_code_fence`); `review_adapter` cycles; `branch_coverage`; `format_sarif_report` (other formatters kept); JIT-side `ast_triggers`/`planned_symbols`. | C1, B1, B3, A5 |
| D15 | **Agent-side hook phases are cut**: `pre-invocation`, `session-close`, `post-session`, `stop`, `governance-monitor`, `immune-init`, the duplicate `hooks/__main__.py`, `evidence_collector` and the transcript helpers.<br>• `command_safety.py`, `hooks/safety.py` and `redaction.py` stay **isolated** behind `aegis hook safety-gate --cmd`. In v4.1, host-native deny rules come first and `command_safety` is the fallback matcher for hosts without them.<br>• `aegis hook pre-commit` merges into `aegis check --hook`. Its tests are ported first. | H7, AD-8 |
| D16 | **The 5 dogfood rules move** (`gitflow-review-gate`, `ci-green-before-release`, `core-change-protocol`, `no-pre-existing-excuse`, `optional-import-guard`) from shipped `rules/` to this repo's `.aegis/rules/`. `desktop-automation` leaves the shipped set. `starter_rules/` becomes a list of names read from `rules/`, so there is no second copy. Rule and skill text uses `${SLOT.*}` instead of Antigravity tool names. | C5, A1 |
| D17 | **`doctor --fix-path`** (rc-file mutation) and **`rule clean`/`cleanse.py`** are cut. Cleanup goes through backed-up `doctor --fix` (host-matrix §3.10). | destructive-ops, M4 |
| D18 | **Single version source**: `aegis_core/_version.py`, read by pyproject (dynamic), the CLI and the server. The doc-coupling tests are replaced by contract snapshots (AD-6): the argparse tree JSON and `tools/list` JSON under `tests/contract/`, which also generate `docs/reference.md`. | AD-6 |
| D19 | **Makefile** has `install`, `test`, `lint` and `build` (polyglot-standards). The `install/` dir, the dead `MANIFEST.in` lines and the duplicate extras are removed. | A1 |
| D21 | **Legacy `.soma` workspaces are migrated, not just refused.** 11 exist on the dev machine with 160 legacy-typed rules (artifacts verified, A4). `aegis migrate` converts `.soma/cells/<type>` to `.aegis/rules/<canonical type>` using the existing type-normalization table. It is a dry run by default and reports any unmapped type instead of guessing. | A4, AD-5 |
| D22 | **AST drivers**: the TypeScript, Go and Rust templates ship in the wheel and work (keep-advocate built a wheel and ran them), so they stay. Only the byte-identical `install/drivers/` copies are deleted. | C1 |
| D23 | **The README overclaim guard survives as a 20-line deny-list test** (no nested pytest). It fails if the README contains a retracted phrase. | C1, AD-6 |
| D20 | **`gitsafe`** runs after the cuts (wave B2), so it wraps only the surviving call sites. It ships before any tag. | red team, A2 |

## 1b. Conditions from the keep-advocate defenses (binding for lanes)

The full text is in the session scratchpad: `defenses.md` (by cluster number) and `sweep_partial.md`, `sweep_partial2.md` and `sweep_fv.md` (by candidate). The key conditions:

- **#15**: make the ledger complete before going ledger-only. Each tp/fp row also counts as a trigger, or carries a paired trigger row. `status`/`aegis_list_rules` compute fitness from the ledger.
- **#2/#14**: cut producer and consumer together. Remove the escaped-defect writer *and* the `escaped`/`defect_prevention_rate` terms in `evaluate_cell_tiers`.
- **#4**: remove the silent `.last_gasp_queue` disabling in `selection.py`. It becomes a sync suggestion (D1).
- **#23**: matcher semantics are an fnmatch superset. `*` crosses `/`; `**/` means zero or more dirs; slashless patterns also match the basename. No substring-glob: first rewrite any shipped patterns that rely on it.
- **#19**: keep `inventory_rules` as the byte snapshot and fingerprint, and add `load_rules` as a projection that carries `.error` records. Serve, checkpoint and verify fail closed.
- **#30**: one private delimiter scanner; keep the three façades' failure contracts.
- **#21**: port the `test_precommit_layer1` tests to `check --hook` before deleting `run_pre_commit`.
- **#31**: keep `_strip_code_fence`; port the `run_layer2` tests to `VerificationPipeline`.
- **#40**: delete only `format_sarif_report`; keep and rename the module holding the other formatters.
- **#41**: rule lint is a table-driven test on the production parser (prototype `agents/refactor-defend-41/test_rule_lint.py`).
- **#43**: land the parser snapshot before deleting the echo tests; include registry names.
- **#44**: single version source first. `aegis_sdk.__version__` stays (external consumers).
- **#45**: keep `test_zero_soma_imports_across_repo` and `test_zero_soma_class_definitions_or_aliases`.
- **#46**: edit `.aegis/rules/invariants/invariant-test-canonical-colocality.md:37` when removing the harness.
- **#47**: dedupe the CI-workflow tests; don't replace them.
- **#49**: keep `pathcheck.build_hint` and its helpers.
- **#33**: no "CI green" step inside `validate.yml` (a job can't see its own conclusion). Use a pre-tag script, `.github/scripts/ci_green.py <sha>`.
- **#8**: the SDK keeps `Governance.{grade, coverage_report, scan, entropy, list_rules, fitness_landscape}`, `parse_rule_file` and `__version__` (D9).
- **#17**: dual-registration writes are cut now (wave A). `doctor --fix` removing `soma` entries lands in wave C.

## 2. Waves

| Wave | Content | Lanes |
|---|---|---|
| **A** (v4.0-a fixes on surviving code) | A1: `forbid_ast` alias bypass and fail-closed handling (H2, H3). A2: remove manifest auto-sync and lock `create` (H1, M1). A3: repo-controlled execution and slot injection (H5). A4: YAML round-trip (M5). A5: CLI and data hygiene (`$HOME` walk-up, `--body-file`, `--from-description`, `.aegis/.gitignore`, M3, F4, L1, the 2 `test_git_workspace` failures). | 5 parallel, disjoint |
| **B1** (cuts, adapters first) | B1-mcp: D2, D4, the H4 remainder, no reflection on close, no `$HOME` mkdir, a non-dict stdio line doesn't kill the server. B1-cli: D5, D6, D15 (CLI side), D17, the `check` flag diet. | 2 parallel |
| **B1b** (cuts, core) | D7, D8, D9, the facades, dead tests (tombstones, meta-tests, argparse echoes). | 1–2 serial |
| **B2** (core architecture) | L0: one lock, atomic and JSONL I/O, `gitsafe` (D20), layout (D12), config (D10), env (D11), ledger v2 and `aegis migrate` (D13). L1: one loader, one matcher, fitness at read time, `aegis sync` (D1, D3), one rule-type table. Boundary test (AD-3), legacy-identifier ratchet, contract snapshots (D18). | serial: B2a, B2b, B2c |
| **C** (v4.0-c, host Phase 1) | host-matrix §3: host table, `init --host`, native registration (codex-cli, claude-code user scope, antigravity), AGENTS.md bootstrap and Claude shim, MCP `instructions`, identity and server-owned keys, AD-4 binding and registry, H8 read-only user layer, doctor matrix and `--fix`, D16 `${SLOT.*}` rewrite, scan-before-edit metric (AD-9). | 2–3 lanes |
| **D** (v4.1) | AD-7 `aegis team` (roles in `team.json`; leases at `refs/aegis/lanes/*` via `update-ref` CAS with TTL; MCP self-registration; `Aegis-*` trailers; cross-vendor pairing check; `aegis check --lane` containment and test-integrity gate). Per-host hooks: Claude PreToolUse (scan-before-edit, safety gate), Codex and Antigravity hooks (fail-open documented). Skills projection (`.agents/skills`, `.claude/skills`). gemini-cli host row (binary present, verify live). | 3 lanes |
| **E** (v4.2) | Day-0 baseline card (`init`, `check --baseline`). Unsigned rule packs (`rule export/import`, sha256 digest; reuses the shelved rule-import design note). `aegis benchmark` (latency, token and throughput only, never efficacy). AST partition check (`team partition-check`). Ratchet baseline for adopting `check` in existing repos. Experimental host rows (cursor, copilot, kiro, windsurf; `verified: false`). Worktree-shared ledger under `<git-common-dir>/aegis/` (H5) with migrate. Claude plugin and Gemini extension packaging (experimental). | 3–4 lanes |
| **F** (docs) | README (SEO, accessible), `docs/how-it-works.md`, `docs/why-aegis.md`, root CHANGELOG, CONTRIBUTING, SECURITY, PRIVACY, one `docs/adr/` dir, generated `docs/reference.md`; delete the rest (docs inventory). | 2 lanes + editor |
| **G** | Independent adversarial review of the whole branch, full suite, CI-equivalent local run, fixes. | — |

After each wave:
1. The orchestrator merges the lane branches into `feature/v4.0`.
2. The full suite runs. Red blocks the next wave.
3. An independent reviewer issues SHIP/HOLD on the merged diff (Gate 5) before the next wave starts.

## 3. Hypothesis and prune boxes for new v4.1 and v4.2 features (C6)

| Feature | Hypothesis | Metric (ledger or git) | Prune if |
|---|---|---|---|
| Lane leases (refs) | Leases prevent cross-lane write conflicts | lease-denied claims; conflicting merges | 0 denials in 30 days of multi-lane use (AD-7) |
| Test-integrity gate | It catches reward hacking (deleted or skipped tests) | gate failures confirmed by a human | 0 confirmed catches in 60 days |
| Scan-before-edit hook | It raises scan-before-edit compliance to ≥ 80% | per-host compliance rate (AD-9) | compliance unchanged versus bootstrap only |
| Baseline card | It shortens first useful `check` | time from `init` to first green `check` | nobody runs `check --baseline` in 30 days |
| Rule packs | Proven rules transfer between repos | imported rules reaching invariant tier | no pack imported in 60 days |
| Benchmark | It catches latency and token regressions | p95 scan latency, scan bytes | no regression caught in 3 releases |
| Partition check | It predicts cross-lane conflicts | predicted vs actual conflicts | precision < 50% over 20 runs |
| Ratchet baseline | It lets existing repos adopt `check` | repos with a baseline file | no adopters |
| Experimental hosts | They work as documented | doctor checks green on a real install | row unverified after 2 minors |
| Worktree-shared ledger | It stops per-worktree fitness splits | rows per worktree vs shared | no multi-worktree users |

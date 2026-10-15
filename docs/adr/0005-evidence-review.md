# Review: branch `feat/v4.0-clean-slate` (9e4d976 vs main 461021c)

Date 2026-10-15. Read-only review by three orthogonal lanes (refactor fidelity, new-code correctness and security, tests and process) plus orchestrator spot-checks. Every HIGH below was reproduced on this machine. Line numbers refer to the branch.

## Baseline

| Check | Result |
|---|---|
| Scope | 2 commits, 42 files, +4,276 / -3,272 |
| Full suite on the branch (isolated HOME) | 3,287 passed, 1 failed, 11 skipped (106 s) |
| The failure on main | passes: it is a branch regression (see F4) |
| ruff on the branch's changed files (global config) | 500 findings |
| Refactor fuzz | YAML parser and serializer: 60k random documents vs main, 0 mismatches. `evaluate_forbid_ast`: 40k cases vs main, 0 mismatches |
| Name coverage | every public name from the five decomposed modules resolves on the new shims; no existing test modified |

## Verdict

The decomposition itself is faithful and well structured. The defects are in what was added on top of it (manifest auto-sync, receiptless telemetry, slot overrides, cleanse) and in what the refactor carried through without noticing (telemetry compaction, release gate, receipt digest). The branch was committed with the test suite red, in one 4,000-line commit with an empty body, with no ADR or changelog entry, and with tests that largely assert imports and line counts.

## HIGH

**H1. Manifest auto-sync launders tampered rules into a validly signed manifest** (new, 9e4d976). `integrity.py:283-300` `sync_manifest_if_present` checks only that the old manifest's signature is valid, then regenerates from disk and re-signs. It never calls `verify_manifest`. With an HMAC key, edit `traps/a.md` and add `traps/rogue.md`; `verify_manifest` reports drift and the rule cache refuses to load. After any unrelated `create_cell` / `promote_cell` / `demote_cell` (hooked at `creation.py:193`, `promotion.py:285`, `:355`), the drift is gone and the signature is valid. Reproduced. Fix: verify first; sync only when the sole drift is the file this operation changed.

**H2. `forbid_ast` is bypassed by import aliasing** (new policy over an old driver). `ast/policy.py:139` builds `imported_qual_map[sym] = f"{src}.{sym}"` from the driver's `imported_symbols`, which stores the alias (`drivers/python.py:59`, `:71`). `import subprocess as sp; sp.run()` and `from subprocess import run as r; r()` produce no violation; the plain forms do. Reproduced.

**H3. `forbid_ast` fails open when extraction returns None.** `ast/policy.py:255`, `:264` (`except Exception: return None`) and `verification/runner.py:380` (`if norm_ast is None: continue`). A BOM-prefixed or latin-1 `.py` file (both run fine under Python) is skipped silently. Fix: a skipped file is a failing or warning result.

**H4. Receipt gate for `aegis_report_outcome` is effectively removed** (new). `server.py:245-260` `_allow_receiptless_telemetry` ends in `or os.path.isdir(str(_canonical_workspace))`, always true once a workspace is configured. A caller omitting the receipt succeeds; one supplying it is worse off, because the carried-over digest in `receipts.py:462-478` hashes `git rev-parse HEAD` plus `git status --porcelain` when no target paths exist, so any work between request and redemption invalidates the receipt (this is the "mismatched receipt" seen from Citadel). `aegis_capture_insight` is receiptless when `insight` and `context_files` are present. Any prompt-injected caller can forge `tp`/`fp` signals.

**H5. `.aegis/slots.yaml` is unsigned, repo-writable, and its commands execute.** `skills/slots.py:154` with `ast/runner.py:79-83`, `:203`. `slots: {ast_driver_md: "touch /path/PWNED"}` ran on the next `.md` parse. New on the branch: `SlotRegistry.for_platform` (`slots.py:122`) lets workspace slots override `TOOL_RUN`, `TOOL_SUBAGENT`, `MODEL_*`, and `handlers/audit.py:92` inlines those values unescaped into JIT scan output the agent reads, a prompt-injection channel from a repo file.

**H6. Release Gate 4.5 trusts forged evidence and exempts governance paths.** `formatters/release_gate.py:9-33`, `:45-110` (carried from main). A hand-written `arbitration_cycle_N.json` with `verdict: ship` and the current tree hash passes. Paths containing `/.aegis/rules`, `/.aegis/evidence`, `/.aegis/governance` are exempt by substring, so `pkg/.aegis/rules/payload.sh` committed after the verdict passes. Only `.py` files are checked for coverage.

## MEDIUM

- **M1. Manifest sync runs after the irreversible rename with no rollback** (`promotion.py:284-286`, `354-366`; `creation.py:193`). A `save_manifest` failure leaves the rule moved and the manifest stale; `demote_cell` then skips artifact cleanup. `create_cell` holds no `workspace_lock(RULES)`, unlike promote/demote.
- **M2. Telemetry compaction is unlocked and can destroy data** (carried; `telemetry_engine/compaction.py:47-141`). No `evidence_lock`; reads `telemetry/signals.jsonl` first but writers use `evidence/`, then overwrites both (5 fresh evidence records became 0 in probe); `except Exception: existing_text = ""` overwrites an unreadable monthly archive. Compacted `event_id`s leave the idempotency index.
- **M3. `McpAdapter.install` destroys an unparseable `.mcp.json`** (`platforms/mcp.py:83-89`): JSONC input lost the user's other servers, reported success, non-atomic write. `init.py generate_mcp_config` correctly raises instead. Both paths now write both `aegis` and `soma` entries, which plausibly explains duplicate MCP toolsets.
- **M4. `cleanse.py` over-purges and follows symlinks** (`:90` substring `slug in stem`; `:143-144` unlink through a symlinked `~/.kiro/steering`; `:161` non-atomic rewrite of `~/.claude/CLAUDE.md`; backup name collisions across platforms).
- **M5. yaml_engine serializer cannot round-trip arbitrary text** (`serializer.py:38`, `:47`): `\r`, U+2028, U+0085 written raw and then rejected by the parser; keys unescaped (`a: 1\nb` injects keys); `parser.py:103` rejects any `\0` substring including `C:\0`; `:287-288` strips ZWSP/BOM inside values. Nested map under a list item misparses silently (`opts: None`, child hoisted). `\UFFFFFFFF` raises a bare `OverflowError`.
- **M6. Telemetry engine is not a pure move** (`ledger.py`): duplicate `rule_id` key on every row, `read_signals` now drops non-dict lines and mutates records, `append_signal` defaults changed, `_cfg_*_filename()` reads `sys.modules["aegis_core.telemetry"]` at call time (engine coupled back to the shim).
- **M7. Facade `__setattr__` mirrors every attribute, dunders included** (`telemetry.py:84-95`): `importlib.reload` rewrites `ledger.__file__` and `__name__`.

## LOW (grouped)

NaN/`1e308` `credit_weight` accepted (`ledger.py:241`); `{"applied": null}` in the rollup raises for all readers; a valid-JSON non-object stdio line (`5`) kills the MCP server (`server.py:622`); `handlers/governance.py:133`, `:226` redefine handlers and monkeypatch them under `except: pass`, and the live `_handle_report_outcome` generates `uuid4()` keys so retries double-record; `aegis_audit_security` / `_performance` are substring heuristics; SARIF `uri` not percent-encoded, no `region`; every `append_signals` rewrites the whole log; `read_generation` falls back to 1 on a corrupt epoch file; `NormalizedAST` default `file_path` changed from `<virtual>` to `<unknown>`.

## Tests and process

- **F4 regression.** `tests/unit/core/test_outcome_engine_insights.py:181` monkeypatches `aegis_core.telemetry.os`, which the shim no longer exposes. Fails on the branch, passes on main. Fix belongs in the test (patch `os.replace` directly).
- The three new test files (606 lines against 4,276 inserted) are mostly existence checks: `test_v4_decomposed_packages.py:49-50`, `110-115` assert source line counts via `inspect.getsource`; `:61-63` greps source text; `test_v4_multiplatform_init_and_slots.py:217-226` is an identity check on re-exports. No direct tests for `yaml_engine/*` beyond one 3-line round-trip, none for `cleanse.clean_global_rules` (a destructive purge), none for `handlers/governance.py`, none for the manifest-sync feature through create/promote/demote.
- `test_v4_decomposed_packages.py:31-42` pins `checkpoint_rollup_file` to `evidence/` while `compaction.py:54` writes to `telemetry/`; the layout properties have no consumers.
- Commit `6f47f13` bundles five decompositions, three features, a security-relevant behaviour change and a manifest rewrite in one revert unit with an empty body. No ADR, no CHANGELOG entry (`[Unreleased]` empty), no version bump (branch says v4.0, everything says 3.3.0; `aegis_*/__init__.py` say 3.1.0). No review or receipt trailer despite `rules/gitflow-review-gate.md` "No Self-Review". Branch name does not match the `feature/*` convention in CONTRIBUTING.md.

## Checked and clean

No `shell=True` / `os.system` / `Popen` in audited trees; `shlex.split` argv execution not shell-injectable; MCP path confinement rejects traversal, absolute paths, symlink escapes and NUL; receipt HMAC compare is constant-time; ledger append under 8 processes x 25 writes kept 200/200 unique records; YAML parser is DoS-hard (depth cap 20, size caps, anchors/aliases/tags rejected, no hangs); `release_gate` git failures fail closed; `clean_global_rules` needs both `force` and `not dry_run`; CLI output formats, exit codes and stdout/stderr routing match main; static import graph has no cycles; `compute_cell_fitness` keeps all three legacy call forms through the shim.

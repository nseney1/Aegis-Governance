# ADR 0003: Aegis v3.0.0 Clean-Slate Cutover & Zero-Dependency CLI UX

- **Status**: Accepted
- **Date**: 2026-10-14
- **Target Release**: v3.0.0

## Context

Across v2.0.0 and v2.1.0, Aegis maintained dual-namespace compatibility shims (`aegis_core/compat.py`, `aegis_core/somayaml.py`, `Soma*`/`Cell*` class aliases, `.soma/cells/` workspace fallbacks, biological rule types `vacuole`/`chloroplast`/`plasmodesmata`, and `soma_*` MCP tool names) so existing installations could transition smoothly via `aegis migrate`. Carrying two parallel domain vocabularies across 4 packages (`aegis_core`, `aegis_cli`, `aegis_mcp`, `aegis_sdk`) and 172 test modules created cognitive overhead, duplicate code paths, and inconsistent CLI formatting.

## Decision

1. **Zero-Legacy Clean-Slate Cutover**:
   - Delete `aegis_core/compat.py`, `aegis_core/somayaml.py`, `aegis_sdk/cells.py`, `aegis_core/cell_inventory.py`, and `aegis_mcp/cell_cache.py`.
   - Remove all `Soma*` and `Cell*` class/exception aliases across `aegis_core`, `aegis_cli`, `aegis_mcp`, and `aegis_sdk`.
   - Enforce pure `.aegis/rules/` workspace resolution (`invariant`, `boundary`, `trap`, `persona`, `contract`) with an explicit Upgrade Sentinel for unmigrated `.soma/` directories.
   - Register all 20 MCP tools exclusively under the `aegis_*` namespace.

2. **Zero-Dependency Terminal UI Architecture (`aegis_cli/ui/`)**:
   - Introduce `OutputContext` (`aegis_cli/ui/theme.py`) and ANSI-aware `Table`/`Grid`/`Column` layout primitives (`aegis_cli/ui/table.py`) using only the Python standard library (`dependencies = []`).
   - Guarantee zero ANSI escape sequences when `--plain`, `--no-emoji`, `--json`, `NO_COLOR`, `TERM=dumb`, or non-TTY `stdout` is active.

3. **Core Engine Cohesion**:
   - Consolidate all YAML frontmatter operations onto `aegis_core/yaml.py` and atomic file writes onto `aegis_core/storage.py`.
   - Relocate `aegis_core/verification_jobs.py` to `aegis_core/verification/jobs.py` and rename `aegis_core/arbitration.py` to `aegis_core/proposals.py`.

## Consequences

- **Positive**: Zero runtime external dependencies preserved; one canonical vocabulary (`Rule`, `AegisYAML`, `AegisError`, `AegisCommand`, `aegis_*` MCP tools); permanent regression protection via `tests/unit/core/test_v3_zero_legacy_invariants.py`.
- **Negative / Migration**: Breaking major release for pre-v2.1 callers still importing `soma_*` or using unmigrated `.soma/` workspaces; mitigated by the Upgrade Sentinel directing users to `aegis migrate` on v2.1.x.

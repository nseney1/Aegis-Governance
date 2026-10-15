# ADR-012: Zero-Dependency Pure-Stdlib Frontmatter Engine

## Status
**Accepted** (v0.96.1 — 2026-10-06; updated for Aegis Guardrails v3.2.0)

## Context
Aegis Guardrails' primary architectural value proposition is an adaptive, resilient governance layer for AI coding assistants. Because Aegis is installed into developer workspaces, virtual environments, CI/CD pipelines, and agent sandbox containers, its runtime dependency footprint directly affects its reliability and security.

Prior to v0.96.1, `pyyaml>=6.0` was the single required package in `pyproject.toml` (`dependencies = ["pyyaml>=6.0"]`). While PyYAML is ubiquitous, requiring it introduced several failure modes:
1. **Bootstrap & Sandbox Brittleness**: In minimal sandbox containers, bare Python environments, or systems where pre-commit hooks run before `pip install`, any bare import of `yaml` caused immediate tool failure (where MCP servers failed to start on bare interpreters).
2. **Maintenance Overhead**: Contradictory guidance between oracle rules (`optional-import-guard.md`) and package manifests led agents to introduce 118 lines of fragile fallback guards across 28 files during earlier releases.
3. **Supply-Chain Attack Surface**: Even single dependencies add supply-chain risk and potential C-extension build failures on esoteric architectures or locked-down enterprise runners.

All markdown rules across `.aegis/rules/`, `rules/`, and `skills/` utilize YAML frontmatter for metadata (e.g., `id`, `type`, `hypothesis`, `prediction`, `target_paths`, `fitness`, `lineage`). However, these files use a structured, predictable subset of YAML rather than complex YAML features like arbitrary Python tags, cyclic references, or custom type constructors.

## Decision
1. **100% Zero-Dependency Runtime**: Completely eliminate `pyyaml` from runtime `pyproject.toml` (`dependencies = []`). Move PyYAML to `[project.optional-dependencies] dev` solely for testing GitHub Actions workflows.
2. **Pure Standard Library Frontmatter Engine**: Implement a full-featured, pure Python standard library YAML subset parser and serializer in `aegis_core/yaml.py` (`AegisYAML`, `AegisDocument`, `parse_frontmatter`, `parse_yaml_subset`, `parse_rule_frontmatter`, `dump_frontmatter`).
3. **Syntax Coverage**: Implement native support in `aegis_core/yaml.py` for:
   - Nested block mappings and block sequences (`- item` and same-indent `key:\n- item`).
   - Sequences of mappings (`- key: val`).
   - Multiline wrapped plain scalars with automatic line-continuation joining.
   - Literal (`|`) and folded (`>`) block scalars with chomping indicators (`-`, `+`, clip).
   - Double-quoted and single-quoted multiline strings with unicode (`\uXXXX`) and escape handling (`\ `, `\\\n`, `\"`).
   - Flow-style scalar types (integers, floats, booleans, nulls, ISO-8601 timestamps).
4. **Repository-Wide Zero-Dependency Invariant**: Statically guarantee in `tests/unit/core/test_static_invariants.py` that zero third-party runtime package imports exist across `aegis_cli/`, `aegis_core/`, `aegis_mcp/`, and `aegis_sdk/`.

## Consequences

### Positive
- **Instant Portability**: Aegis Guardrails can be imported and executed anywhere a Python ≥ 3.10 (3.9+ compatible) interpreter exists, with zero external wheels to download or build.
- **Sub-Millisecond Cold Starts**: MCP server startup and CLI execution avoid third-party C-extension dynamic linking and module discovery overhead.
- **100% Behavioral Parity**: All frontmatter-bearing markdown files in the repository parse identically to PyYAML's parsed dictionary output (verified by roundtrip parity tests).
- **Reduced Attack Surface**: Zero supply-chain dependencies at runtime eliminates vulnerabilities in external parsers, reinforced by DoS recursion guards and anchor attack prevention in `AegisYAML`.

### Negative / Trade-offs
- **Subset Scope**: `aegis_core.yaml` (`AegisYAML`) is intentionally an application-tailored subset, not a full YAML 1.2 specification engine. It rejects YAML anchors (`&`, `*`), custom tags (`!tag`), and merge keys (`<<`) by design.
- **Engine Maintenance**: Any future syntax additions required by new rule types must be implemented and tested within `aegis_core/yaml.py` and covered by `tests/unit/core/test_frontmatter_engine.py`.

## Verification & Compliance
- **Unit Testing**: Behavioral tests in `tests/unit/core/test_frontmatter_engine.py` and `tests/unit/core/test_aegis_yaml.py` validate all supported YAML constructs against edge cases (chomping, unicode escapes, wrapped plain scalars, nested sequences, DoS limits).
- **Runtime Import Audit**: `python3 -c "import sys; sys.modules['yaml'] = None; import aegis_core, aegis_cli, aegis_mcp, aegis_sdk"` verifies that all runtime CLI, MCP, SDK, and core modules import and operate successfully with PyYAML completely blocked from `sys.modules`.


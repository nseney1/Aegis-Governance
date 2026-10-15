# Contributing to Aegis Guardrails

Thank you for your interest in contributing to **Aegis Guardrails** (`v3.2.0`)!

## Architecture Overview

Aegis Guardrails is organized into four zero-dependency runtime packages plus declarative governance assets:
- **`aegis_core/`**: Core verification (`VerificationPipeline`, `Arbiter`), scoring (Wilson interval confidence bounds), rule lifecycle (`aegis_core/lifecycle/`), `AegisYAML` parser, cryptographic receipts (`ReceiptManager`), and Normalized AST Drivers (`aegis_core/ast/`).
- **`aegis_cli/`**: Unified CLI commands (`aegis init`, `status`, `check`, `rule`, `system`, `doctor`, `detect`, `migrate`, `report`, `sync`) and native platform adapters (`aegis_cli/platforms/`).
- **`aegis_mcp/`**: Model Context Protocol (MCP) server exposing the 17 canonical `aegis_*` tools with JIT context budget clamping and response projection.
- **`aegis_sdk/`**: Public Python SDK (`Governance`, `Rule`, `RuleFitness`, `scoring`, `invariants`, `telemetry`, `errors`).
- **`rules/` & `skills/`**: 18 constitutional core rules (`rules/`) and 15 multi-step agent skills (`skills/`).

## How to Contribute

### Reporting Issues
- Open a GitHub issue with a clear description and reproduction steps.
- Include your AI platform (`gemini` / `claude` / `cursor` / `copilot` / `kiro`) and OS.
- Include `aegis doctor` (or `make doctor`) output if relevant.

### Submitting Changes (Gitflow Review Gate)
All contributions follow [`rules/gitflow-review-gate.md`](../../rules/gitflow-review-gate.md):
1. Fork or branch from `develop`: `git checkout develop && git checkout -b feat/your-change` (or `fix/your-change`).
2. Implement changes following TDD (`rules/.oracles/tdd-protocol.md`).
3. Run the full test suite: `python3 -m pytest -q`.
4. Run verification checks: `aegis check` (and `aegis check --release` before release PRs).
5. Open a pull request targeting `develop`:
   - **No Self-Review (`rules/gitflow-review-gate.md`)**: The context that authored changes must not approve them. Dispatch an independent audit subagent (or request maintainer review) to verify all tests pass, zero merge conflict markers exist, diff scope is clean, and version strings are synchronized.
   - PRs targeting `main` (`release/vX.Y.Z`) require human review and merge authority.

### Development Requirements
- **Zero Runtime Dependencies**: `aegis_core`, `aegis_cli`, `aegis_mcp`, and `aegis_sdk` must use only the Python standard library (`dependencies = []` in `pyproject.toml`).
- **Python 3.10–3.13 (3.9+ compatible)**: Include `from __future__ import annotations` as the first import in modules using `X | None` union syntax.
- **CI Matrix**: Automated tests run across Linux, macOS, and Windows.
- **Test Command**: `python3 -m pytest -q` (and `python3 -m pytest tests/unit/core/test_documentation_accuracy.py -q` for documentation contract verification).
- **Local Test Caches**: `.hypothesis/` and `.pytest_cache/` are local test artifacts and must *never* be committed to version control.

### Contributing Repo-Local Rules (`.aegis/rules/`)
If your Genesis scan or post-mortem produced high-signal rules:
1. Verify rule fitness via `aegis status` or `aegis rule list` (scored via Wilson interval lower-bound confidence intervals in `aegis_core/scoring.py`).
2. Submit the rule file under `.aegis/rules/<type>/` (`invariants/`, `traps/`, `gates/`, `boundaries/`, `personas/`, `contracts/`).
3. Include the rule's `hypothesis`, `prediction`, `falsification`, and empirical trigger data.

### Contributing Core Rules (`rules/`)
New constitutional rules in `rules/` must follow [`rules/core-change-protocol.md`](../../rules/core-change-protocol.md):
- Trace back to observed failure patterns (Design Principle §1).
- Include valid YAML frontmatter (`trigger`, `description`) and falsifiable criteria (Design Principle §6).
- Be measured by `aegis_core/metrics.py` for token budget impact.
- Pass `aegis check` and `python3 -m pytest tests/unit/core/test_documentation_accuracy.py -q`.

## Contributor License Agreement

By submitting a pull request, you agree that your contributions are licensed under the same Apache License 2.0 that covers this project, and you certify that you have the right to grant this license.

You retain copyright to your contributions. The project maintainer (Nicholas Seney) retains the right to relicense contributions as part of the overall project.

## Code of Conduct

Be respectful, constructive, and evidence-driven — the same principles that govern the AI should govern the humans.

## Privacy Invariant

All contributions must respect the **Aegis Privacy Invariant**:
- ✅ Aggregate counts, booleans, sanitized strings
- ❌ Never: raw file paths, usernames, hostnames, project names, or raw code content in external telemetry

See the [NOTICE](../../NOTICE) file for the full privacy statement.


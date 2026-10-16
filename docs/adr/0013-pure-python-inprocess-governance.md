# ADR 0013: Pure-Python In-Process Governance Engine & Facade Unification

## Status
**Accepted** (v0.97.0 — 2026-10-06; updated for Aegis Guardrails v3.2.0)

**v4 status (2026-10-15): partly superseded by [ADR 0005](0005-v4-plan-of-record.md) §5.** The rule stands: Aegis never runs repository or package scripts as subprocesses. Most components named below are cut: the MCP tools beyond the four kept ones, the `Governance` SDK methods other than the six the thin facade keeps, the session-close hooks, and `aegis_core/enforcement.py`.

## Context
When the legacy `enzymes/` directory containing standalone bash and python scripts was deprecated and purged to consolidate core logic into `aegis_core/`, the public SDK facade (`aegis_sdk/governance.py`), build system (`Makefile`), lifecycle hooks (`aegis_cli/hooks/`), and gate generators (`aegis_core/enforcement.py`) needed to eliminate subprocess script invocations:
1. **SDK Facade Isolation**: `Governance` methods (`fitness_landscape`, `coverage_report`, `grade`, `create_rule`) previously spawned external scripts via subprocesses, which failed when installed as a standalone wheel outside a source checkout.
2. **Build System & Tooling**: `Makefile` Python resolution needed a pure-shell interpreter probe without sourcing removed shell helpers.
3. **Session-Close Hooks**: `aegis_cli/hooks/runtime.py:run_session_close()` needed to invoke outcome and fitness evaluation directly in-process via `aegis_core`.
4. **Shell Injection Prevention in Enforcement**: Generated pre-commit scripts needed to pass rule identifiers via `sys.argv[1]` rather than string interpolation.

## Decision
1. **Pure-Python In-Process Mandate**:
   - All `Governance` SDK methods (`fitness_landscape`, `coverage_report`, `grade`, `create_rule`, `create_rule_from_description`, `signal`, `quorum`, `scan`, `entropy`) execute in-process via pure-Python APIs in `aegis_core.lifecycle`, `aegis_core.telemetry`, `aegis_core.metrics`, and `aegis_core.scoring`.
   - Internal subprocess execution of repository or package script files is strictly prohibited.
2. **MCP Dictionary Guarantees**:
   - `aegis_grade`, `aegis_coverage`, and `aegis_rule_fitness` return typed dictionaries directly from in-process `aegis_core` calls (`aegis_mcp/handlers/`).
   - If `calculate_immune_grade()` returns `None` (empty workspace), a structured fallback dictionary is guaranteed so MCP clients never receive raw text or `null`.
   - `aegis_propose_change` and `aegis_capture_insight` dispatch directly to `aegis_core.proposals` and `aegis_core.insights`.
3. **Safe Shell Execution & Enforcement**:
   - Enforcement generators in `aegis_core/enforcement.py` pass rule names safely via `sys.argv[1]` to prevent shell interpolation:
     ```bash
     python3 -c "import sys; from aegis_core.telemetry import append_signal; append_signal('.', sys.argv[1], 'tp', 'mechanical')" {quoted_name}
     ```
   - Gate assertions define complete rule dictionaries before calling `record_escaped_defect()`.
4. **Resilient Makefile Tooling**:
   - Probe `$AEGIS_PYTHON`, `$VIRTUAL_ENV`, `python3`, `python`, `py` without external shell scripts.
   - Verify `aegis_*` packages in `make doctor` and `make validate`.

## Consequences

### Positive
- **Guaranteed Portability**: Eliminates all shell subprocess dependencies from SDK and MCP execution, ensuring identical behavior across Windows, Linux, and macOS.
- **High Performance**: Eliminates process fork/exec overhead (~50ms per invocation down to <1ms in-process).
- **Security Hardening**: Completely removes shell injection vectors in pre-commit hook generators.
- **Reliable Wheel Smoke Testing**: Package installations pass isolated source-hidden validation (`.github/scripts/wheel_smoke.py`).

### Negative / Trade-offs
- **Sunset of Standalone Scripts**: External callers must use `aegis` CLI subcommands (`aegis_cli`) or the `aegis_sdk` Python API.

## Verification
- Verified by:
  - `pytest tests/unit/sdk/test_governance.py`
  - `pytest tests/unit/mcp/test_mcp_readonly_tools.py`
  - `pytest tests/unit/core/test_enforcement.py tests/unit/core/test_enforce_hooks.py tests/unit/cli/test_hooks_lifecycle.py`
  - `pytest tests/unit/core/test_bayesian_correctness.py tests/unit/core/test_exponential_decay.py tests/unit/core/test_escaped_defects_behavioral.py`
  - `python3 -I .github/scripts/wheel_smoke.py`


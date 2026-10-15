# MCP Gateway & Dual-Plane Architecture

> Fast, local-first, zero-dependency Model Context Protocol (MCP) server integration for AI coding agents.

---

## 1. Dual-Plane Architecture Overview

Aegis provides a native MCP server (`python3 -m aegis_mcp`) allowing AI coding assistants (Claude Code, Antigravity, Gemini CLI, Cursor, Copilot) to query governance rules, request cryptographic execution receipts, run two-layer verification, and exchange typed swarm handoffs with zero runtime dependencies.

The MCP gateway is structured as a **Dual-Plane Architecture**:
- **Control Plane (`aegis_mcp/server.py`, `aegis_mcp/registry.py`, `aegis_mcp/security.py`)**:
  - Schema registration (`TOOL_DEFINITIONS`), server-owned key stripping (`strip_server_owned`), canonical workspace confinement (`confine_workspace`, `confine_path_internal`), sliding-window rate limiting, and single-use receipt verification (`ReceiptManager`).
- **Execution Plane (`aegis_mcp/handlers/`, `aegis_mcp/tools.py`)**:
  - Domain handlers for rule governance, two-layer verification, security/performance auditing, and outcome telemetry.
- **Hot-Path Stat-Fingerprinted Caching (`RuleCache`)**:
  - To guarantee sub-millisecond JIT rule scans on `aegis_scan` and `aegis_list_rules`, `RuleCache` caches parsed rule inventories keyed by `(st_dev, st_ino, st_size, st_mtime_ns)` directory/file stat fingerprints, invalidating automatically whenever any `.aegis/rules/**/*.md` file changes.

---

## 2. All 17 `aegis_*` MCP Tools & Security Tiers

All 17 MCP tools are partitioned across three security tiers (`_READ_TOOLS`, `_WRITE_TOOLS`, `_EXECUTE_TOOLS` in `aegis_mcp/server.py`):

| Tier | Default State | Authorization | Tools (17 Total) |
|:-----|:-------------:|:--------------|:-----------------|
| **Read Tier** (9 tools) | Enabled | Canonical Workspace Confinement | `aegis_scan`, `aegis_list_rules`, `aegis_rule_fitness`, `aegis_grade`, `aegis_coverage`, `aegis_audit_security`, `aegis_audit_performance`, `aegis_poll_verification`, `aegis_request_receipt` |
| **Write Tier** (4 tools; 5 with manifest generation) | Enabled | Single-Use Cryptographic Receipt (`aegis_request_receipt`) | `aegis_report_outcome`, `aegis_capture_insight`, `aegis_create_rule`, `aegis_handoff` *(plus `aegis_generate_manifest` when signing `.aegis/rules/manifest.json`)* |
| **Execute Tier** (3 verification/mutation tools + `aegis_generate_manifest` in `_EXECUTE_TOOLS`) | Opt-In (`AEGIS_EXECUTION_ENABLED=1`) | Single-Use Cryptographic Receipt + `AEGIS_EXECUTION_ENABLED=1` | `aegis_propose_change`, `aegis_verify_changes`, `aegis_checkpoint`, `aegis_generate_manifest` |

### Tool Reference Summary

- **Read Tier (9 tools)**:
  1. `aegis_scan`: JIT context injection returning the top relevant rules for target files ranked by Thompson Sampling (`Beta(tp+1, fp+1)`) and Wilson score.
  2. `aegis_list_rules`: Lists workspace rules in `.aegis/rules/` and core rules with metadata and enforcement tiers.
  3. `aegis_rule_fitness`: Computes Bayesian Wilson confidence intervals and confusion matrices for rules.
  4. `aegis_grade`: Calculates an aggregate governance health grade (`A+` through `F`) for the workspace.
  5. `aegis_coverage`: Analyzes rule and test coverage across repository modules.
  6. `aegis_audit_security`: Scans target files for OWASP vulnerabilities, hardcoded secrets, and unsafe execution patterns.
  7. `aegis_audit_performance`: Inspects code for hot-path allocations, algorithmic bottlenecks, and unbounded loops.
  8. `aegis_poll_verification`: Polls the status of asynchronous or in-band verification cycles.
  9. `aegis_request_receipt`: Issues a single-use, state-bound HMAC-SHA256 receipt (300s TTL) authorizing a Write or Execute tool call.
- **Write Tier**:
  10. `aegis_report_outcome`: Records `pass`/`fail`/`skip` rule execution telemetry into `.aegis/evidence/signals.jsonl`.
  11. `aegis_capture_insight`: Captures developer or post-mortem insights into `.aegis/human_insights.jsonl`.
  12. `aegis_create_rule`: Authors a new rule in `.aegis/rules/{invariants,traps,gates,methods}/` validated by `AegisYAML`.
  13. `aegis_handoff`: Executes a file-buffered swarm handoff via `HandoffRouter`, writing an `ArtifactEnvelope` to `.aegis/swarm/handoffs/` and returning a `<150` token `HandoffTicket`.
- **Execute Tier (`AEGIS_EXECUTION_ENABLED=1`)**:
  14. `aegis_propose_change`: Validates a proposed file modification against active `gate` rules prior to disk write.
  15. `aegis_verify_changes`: Runs the two-layer verification pipeline (`DeterministicVerifier` + `AdversarialVerifier` + `Arbiter`).
  16. `aegis_checkpoint`: Creates a verified workspace checkpoint bound to `HEAD^{tree}`.
  17. `aegis_generate_manifest`: Generates and signs `.aegis/rules/manifest.json` using HMAC-SHA256 / Ed25519 keys in `.aegis/keys/manifest.key`.

---

## 3. Single-Use Cryptographic Receipts (`ReceiptManager`)

Write and Execute tools require a state-bound receipt obtained from `aegis_request_receipt` (`aegis_core/receipts.py`):

1. **Request**: The agent calls `aegis_request_receipt(operation="aegis_create_rule", args={...})`.
2. **State Binding**: `ReceiptManager` computes an HMAC-SHA256 signature over `(nonce, session_id, workspace, operation, args_hash, files_digest, rules_digest, expires_at)`. Target paths (`file_path`, `files`, `context_files`) are confined via `confine_path_internal`.
3. **Burn-Before-Compare Redemption**: When the agent invokes the target tool with `receipt="<token>"`, `ReceiptManager` atomically removes/burns the receipt *before* comparing digests (`hmac.compare_digest`). Any modification to target files, `.aegis/rules/`, or tool arguments between issuance and redemption invalidates the receipt and prevents TOCTOU or replay attacks.

---

## 4. Opt-In Response Projection & Denylist (`project_response`)

Clients can minimize token consumption by passing `view` or `fields` to any MCP tool (`aegis_mcp/projection.py`):
- `view="full"` (default): Full sanitized payload.
- `view="summary"`: Compact dictionary retaining only `SUMMARY_FIELDS` (`id`, `status`, `verdict`, `score`, `summary`, etc.).
- `view="ids"`: Identifier-only projection.
- `fields=["id", "fitness.score"]`: Pure dictionary path extraction without `eval()` or `getattr()`.

All responses are scrubbed by `_sanitize_data()` against the `AEGIS-V01` `DENYLIST` (`task_plan`, `prompt`, `raw_prompt`, `__globals__`, `__builtins__`, `__subclasses__`, `__dict__`, `__mro__`, `__class__`).

---

## 5. `.mcp.json` Setup & Configuration

Generate `.mcp.json` automatically via `aegis init --mcp`, or add Aegis manually to your MCP client configuration:

```json
{
  "mcpServers": {
    "aegis": {
      "command": "python3",
      "args": ["-m", "aegis_mcp"],
      "env": {
        "AEGIS_WORKSPACE": "/path/to/your/project",
        "AEGIS_EXECUTION_ENABLED": "1"
      }
    }
  }
}
```

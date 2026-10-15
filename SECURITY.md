# Security Policy

## Supported Versions

Only the current minor release line receives security fixes. Fixes land on `develop` and ship in the next release of that line; older lines are not patched.

| Version | Supported |
|:--------|:---------:|
| 3.3.x | ✅ |
| 3.2.x | ✅ |
| < 3.2 | ❌ |

## Reporting a Vulnerability

Please **do not open a public issue** for a suspected vulnerability.

Report it privately through GitHub's private vulnerability reporting: open the repository's **Security** tab and choose **Report a vulnerability** (<https://github.com/nseney1/Aegis-Guardrails/security/advisories/new>). The report stays visible only to you and the maintainers.

> [!NOTE]
> This channel works only after the maintainer enables *Private vulnerability reporting* under **Settings → Code security** for the repository. If the button is missing, open a public issue that asks for a private contact channel, without any vulnerability details.

Include, where you can: the affected version (`VERSION` or `pip show aegis-guardrails`), OS and shell, the component (`aegis_core`, `aegis_mcp`, `aegis_cli`, `aegis_sdk`), reproduction steps or a proof of concept, and the impact you observed.

**What to expect.** Aegis Guardrails is maintained by Nicholas Seney, so these are goals, not guarantees:

- Acknowledge the report within 7 days.
- Confirm or reject it, with reasoning, within 30 days.
- Coordinate a fix and a GitHub Security Advisory with you before public disclosure, and credit you unless you prefer otherwise.

Fixed vulnerabilities are recorded in [`docs/project/CHANGELOG.md`](docs/project/CHANGELOG.md) and the [Bug Registry](docs/project/BUG_REGISTRY.json). No bug bounty is offered.

## Scope

In scope: defects that break one of the security guarantees below.

- **Workspace Path Confinement** ([`aegis_core/workspace/confinement.py`](aegis_core/workspace/confinement.py), [`aegis_mcp/security.py`](aegis_mcp/security.py)): any tool or CLI operation reading or writing outside the canonical `AEGIS_WORKSPACE` via `confine_path_internal` / `confine_path`, including via client-supplied `workspace` arguments, `..` traversal segments, symlink escapes, null bytes, Windows extended device namespaces (`\\?\`), alternate data streams (`:`), or reserved device names (`CON`, `NUL`, `COM1`, etc.).
- **Cryptographic Single-Use Execution Receipts** ([`aegis_core/receipts.py`](aegis_core/receipts.py), [`aegis_mcp/server.py`](aegis_mcp/server.py)): invoking a Write or Execute tier MCP tool without a valid receipt from `aegis_request_receipt`; redeeming a receipt twice (bypassing `ReceiptManager` burn-before-compare semantics); redeeming after the 300s TTL expiry, across sessions, for altered arguments, or after target files (`file_path`, `files`, `context_files`) or `.aegis/rules/` digests have changed; or running an Execute tier tool when `AEGIS_EXECUTION_ENABLED` is not `1`.
- **Rule Integrity & Manifest Signing** ([`aegis_core/integrity.py`](aegis_core/integrity.py)): a tampered rule file or `.aegis/rules/manifest.json` passing `aegis_generate_manifest` / `verify_manifest` cryptographic verification (HMAC-SHA256 / Ed25519 envelope verification via `hmac.compare_digest`), or a key file in `.aegis/keys/manifest.key` created with permissions wider than `0600`.
- **MCP Projection Denylist & Information Partitioning** ([`aegis_mcp/projection.py`](aegis_mcp/projection.py)): `project_response` leaking denylisted keys (`task_plan`, `prompt`, `raw_prompt`, `__globals__`, `__builtins__`, `__subclasses__`, `__dict__`, `__mro__`, `__class__`) or allowing arbitrary code execution during field projection.
- **Evidence Ledger Integrity** (`.aegis/evidence/signals.jsonl`, [`aegis_core/telemetry.py`](aegis_core/telemetry.py), [`aegis_sdk/telemetry.py`](aegis_sdk/telemetry.py)): a replayed or mutated telemetry event bypassing `EventConflictError` or `StaleGenerationError`, lost records under concurrent writers (`.aegis/evidence/.signals.lock`), or epoch cutover corruption.
- **Supply Chain**: the release pipeline ([`.github/workflows/publish.yml`](.github/workflows/publish.yml)) publishing artifacts that differ from the verified build, or risks around the `aegis-guardrails` PyPI distribution.
- Secrets that leak into the repository, the wheel, or the sdist.

## Out of Scope

- **A malicious or compromised agent with direct shell access.** Receipts authorize a specific, state-bound MCP operation; they do not sandbox an OS user or shell process that can modify files on disk directly.
- **Any MCP client sharing the same stdio server pipe.** Every client connected to the same stdio process can call `aegis_request_receipt`. Process isolation is the responsibility of the host launching `python3 -m aegis_mcp`.
- Open bugs already listed in the [Bug Registry](docs/project/BUG_REGISTRY.json) and [Known Issues — Windows](docs/KNOWN_ISSUES_WINDOWS.md), unless you demonstrate a security impact not described there.
- Vulnerabilities in third-party AI agents, MCP hosts, Python itself, or the host OS.
- Denial of service against the local stdio server by its own connected client.
- Releases older than the supported lines.

## Security Model (Aegis v3.3.0)

1. **Tiered MCP Gateway (`aegis_mcp/server.py`)**:
   - **Read Tier (9 tools, enabled by default)**: `aegis_scan`, `aegis_grade`, `aegis_coverage`, `aegis_request_receipt`, `aegis_audit_security`, `aegis_audit_performance`, `aegis_poll_verification`, `aegis_list_rules`, `aegis_rule_fitness`.
   - **Write Tier (4 tools, receipt required)**: `aegis_report_outcome`, `aegis_capture_insight`, `aegis_create_rule`, `aegis_handoff`.
   - **Execute Tier (4 tools, opt-in via `AEGIS_EXECUTION_ENABLED=1` + receipt required)**: `aegis_propose_change`, `aegis_verify_changes`, `aegis_checkpoint`, `aegis_generate_manifest`.
2. **Canonical Workspace Confinement (`confine_path_internal`)**:
   - At startup, `aegis_mcp` locks onto `AEGIS_WORKSPACE` via `confine_workspace()`, requiring an existing directory containing `.aegis/rules/`.
   - The server strips `workspace`, `receipt`, and `_sessionToken` from client arguments (`strip_server_owned`) and resolves every path through `confine_path_internal()` (`aegis_core/workspace/confinement.py`), rejecting traversal (`..`), symlinks escaping root, null bytes, Windows device names, and NTFS alternate data streams.
3. **Burn-Before-Compare Cryptographic Receipts (`ReceiptManager`)**:
   - `aegis_request_receipt` issues a 256-bit token signed with HMAC-SHA256 (`.aegis/keys/receipt.key` or ephemeral 256-bit key) bound to `(nonce, session_id, workspace, operation, args_hash, files_digest, rules_digest, expires_at)`.
   - On redemption, `ReceiptManager.verify_and_consume` atomically burns the receipt *before* digest comparison—preventing timing attacks, replay attacks, and TOCTOU races if target files or rules change between issuance and execution.
4. **Signed Rule Manifests (`aegis_generate_manifest`)**:
   - `aegis_core/integrity.py` hashes all `.aegis/rules/**/*.md` files (with CRLF-normalized fallback verification) and signs `.aegis/rules/manifest.json` using HMAC-SHA256 / Ed25519 keys stored in `.aegis/keys/manifest.key` (`0600` permissions), verified via constant-time `hmac.compare_digest`.
5. **MCP Response Projection Denylist (`project_response`)**:
   - `aegis_mcp/projection.py` enforces `AEGIS-V01` information partitioning by recursively stripping denylisted keys (`task_plan`, `prompt`, `raw_prompt`, and Python dunder introspection attributes) and performing pure dictionary traversal without `eval()` or `getattr()`.
6. **Atomic Cross-Process Evidence Ledgers**:
   - `append_signal()` in `aegis_core/telemetry.py` writes under `.aegis/evidence/.signals.lock`, enforces payload digest idempotency (`EventConflictError`), and validates epoch generations (`StaleGenerationError`).

# Security Policy

## Supported Versions

Only the current minor release line receives security fixes. Fixes land on `develop` and ship in the next release of that line; older lines are not patched.

| Version | Supported |
|:--------|:---------:|
| 2.0.x | ✅ |
| < 2.0 | ❌ |

## Reporting a Vulnerability

Please **do not open a public issue** for a suspected vulnerability.

Report it privately through GitHub's private vulnerability reporting: open the repository's **Security** tab and choose **Report a vulnerability** (<https://github.com/nseney1/Soma-Governance/security/advisories/new>). The report stays visible only to you and the maintainers.

> [!NOTE]
> This channel works only after the maintainer enables *Private vulnerability reporting* under **Settings → Code security** for the repository. If the button is missing, open a public issue that asks for a private contact channel, without any vulnerability details.

Include, where you can: the affected version (`VERSION` or `pip show aegis-governance`), OS and shell, the component (installer, MCP server, CLI), reproduction steps or a proof of concept, and the impact you observed.

**What to expect.** Aegis is maintained by Nicholas Seney, so these are goals, not guarantees:

- Acknowledge the report within 7 days.
- Confirm or reject it, with reasoning, within 30 days.
- Coordinate a fix and a GitHub Security Advisory with you before public disclosure, and credit you unless you prefer otherwise.

Fixed vulnerabilities are recorded in [`docs/project/CHANGELOG.md`](docs/project/CHANGELOG.md) and the [Bug Registry](docs/project/BUG_REGISTRY.json). No bug bounty is offered.

## Scope

In scope: defects that break one of the guarantees below.

- **Installers and uninstallers** ([`install/install.sh`](install/install.sh), [`install/install.ps1`](install/install.ps1), [`install/uninstall.sh`](install/uninstall.sh), [`install/uninstall.ps1`](install/uninstall.ps1)): writing or deleting outside the allowed roots (the home directory and the working directory), following a symlink or junction out of an allowed root, removing a path not listed in the install manifest, or overwriting a user's existing file without a backup (`install.sh` copies it under `~/.aegis/backup/`; `install.ps1` writes a `<file>.bak.<epoch>` copy next to it).
- **MCP server receipts** ([`aegis_mcp/server.py`](aegis_mcp/server.py), [`aegis_core/receipts.py`](aegis_core/receipts.py)): running a write or execute tool without a valid receipt, redeeming a receipt twice, after expiry, from another server process, for different arguments, or after a target file or rule changed; running an execute tool while `AEGIS_EXECUTION_ENABLED` is not `1`.
- **MCP workspace confinement** ([`aegis_mcp/security.py`](aegis_mcp/security.py)): any tool reading or writing outside the operator-configured `AEGIS_WORKSPACE`, including by a client-supplied `workspace` argument, `..` segments, absolute paths or symlinks.
- **Evidence files** (`.aegis/evidence/`, written by [`aegis_sdk/telemetry.py`](aegis_sdk/telemetry.py)): a replayed or altered event that changes recorded fitness, lost or duplicated records under concurrent writers, or an epoch migration that corrupts ledgers.
- **Rule integrity manifests** ([`aegis_mcp/integrity.py`](aegis_mcp/integrity.py)): a tampered manifest that passes signature verification, or a signing key written with permissions wider than `0600`.
- **Supply chain**: the release pipeline ([`.github/workflows/publish.yml`](.github/workflows/publish.yml)) publishing files that differ from the built and smoke-tested artifacts, or a dependency-confusion or typosquatting risk around the `aegis-governance` PyPI package.
- Secrets that leak into the repository, the wheel or the sdist.

## Out of Scope

- **A malicious or compromised agent with shell access.** Receipts authorize a specific, state-bound MCP operation; they do not authenticate a person. An agent that can run commands can edit rules, evidence files and configuration directly. Aegis's rules and hooks are governance aids, not a sandbox.
- **Any MCP client of a running server.** Every client connected to the server's stdio can request receipts. Isolation comes from the host process that launches the server.
- Open bugs already listed in the [Bug Registry](docs/project/BUG_REGISTRY.json) and [Known Issues — Windows](docs/KNOWN_ISSUES_WINDOWS.md), unless you show a security impact they do not describe.
- Vulnerabilities in the AI agents, MCP hosts, Python, or the operating system themselves.
- Denial of service against the local stdio server by its own client, and the strength of the per-tool rate limits.
- Releases older than the supported line.

## Security Model

A short summary of the controls in the code. The [v0.89.0 "MCP Execution Security" changelog entry](docs/project/CHANGELOG.md) has the full history (BUG-009, BUG-016 – BUG-021, BUG-023).

- **Tiered MCP tools.** Read, write and execute tools are fixed sets in [`aegis_mcp/server.py`](aegis_mcp/server.py). Execute tools are refused unless the operator sets `AEGIS_EXECUTION_ENABLED=1`.
- **Canonical workspace.** At startup the server resolves `AEGIS_WORKSPACE` (or the current directory) with `confine_workspace()` in [`aegis_mcp/security.py`](aegis_mcp/security.py), which requires an existing directory containing `.aegis/rules/` or `.soma/cells/`; otherwise the server exits. The dispatcher strips the server-owned keys `workspace`, `receipt` and `_sessionToken` from every call, read tools included, and injects the canonical workspace only after receipt verification.
- **Receipts.** `soma_request_receipt` issues a random 256-bit receipt (`secrets.token_hex(32)`) held in server memory ([`aegis_core/receipts.py`](aegis_core/receipts.py)). It is bound to the server session, the canonical workspace, the operation, a sha256 hash of the exact arguments, a digest of the target files (`file_path`, `files`, `context_files`) and a fingerprint of every rule. It expires after 300 seconds, is consumed on use, and is discarded on any failed verification. Target paths that resolve outside the workspace are rejected at issuance. A server restart invalidates all receipts.
- **Rate limits.** `soma_propose_change`, `soma_report_outcome`, `soma_verify_changes` and `soma_checkpoint` have per-process call limits, checked before a receipt is consumed.
- **Evidence integrity.** `append_signal()` in [`aegis_sdk/telemetry.py`](aegis_sdk/telemetry.py) appends under a cross-process lock (`.aegis/evidence/.signals.lock`), treats an identical replay as a no-op, and raises `EventConflictError` when a known `event_id` arrives with a different payload. Epoch migrations snapshot every ledger with `SHA256SUMS` before cutover.
- **Signed rule manifests.** [`aegis_mcp/integrity.py`](aegis_mcp/integrity.py) signs rule manifests with HMAC-SHA256, using a 256-bit key in `.aegis/keys/manifest.key` (mode `0600`), and verifies with `hmac.compare_digest`.
- **Installer confinement.** The uninstallers check every manifest path, and the whole removal plan, against canonical allowed roots before deleting anything, fail closed, and re-check each path before removal. A symlinked or junctioned ancestor is accepted only when its target stays inside the allowed root.
- **Credentials.** API keys are not read from config files. They come only from environment variables or the system keyring.
- **Release artifacts.** One build records `SHA256SUMS`. The sdist and wheel are smoke-tested outside the checkout, and `publish.yml` verifies the digests and uploads only the verified files.

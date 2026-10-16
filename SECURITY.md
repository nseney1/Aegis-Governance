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

Fixed vulnerabilities are recorded in the [CHANGELOG](CHANGELOG.md) and in the GitHub Security Advisory. No bug bounty is offered.

## Scope

In scope: defects that break one of the security guarantees below.

- **Workspace Path Confinement** ([`aegis_core/workspace/confinement.py`](aegis_core/workspace/confinement.py), [`aegis_core/storage.py`](aegis_core/storage.py)): any tool or CLI operation reading or writing outside the governed workspace, including through `..` traversal, symlink escapes, null bytes, Windows extended device namespaces (`\\?\`), alternate data streams or reserved device names.
- **Repository-Controlled Execution** ([`aegis_core/gitsafe.py`](aegis_core/gitsafe.py), [`aegis_core/config.py`](aegis_core/config.py)): a file a repository controls (`.aegis/config.json`, rule files, `.git/config`, `.gitattributes`) making Aegis run a command, a git fsmonitor, hook or filter driver, or inject instructions into scan output. Repository config cannot name commands; those come only from packaged templates or your user-level `~/.aegis/config.json`.
- **No Automatic Rule Rewrites** ([`tests/integration/test_no_rule_writes.py`](tests/integration/test_no_rule_writes.py)): any automatic path (`aegis check`, `aegis scan`, the MCP tools, hooks) modifying files under `.aegis/rules/`. Only explicit commands (`aegis rule …`, `aegis sync --apply`, `aegis migrate --apply`) write rule files. Rule integrity rests on git history, review and CI; Aegis does not sign rules. Witnessed rule integrity is planned for v4.3.
- **Evidence Ledger Integrity** ([`aegis_core/telemetry_engine/ledger.py`](aegis_core/telemetry_engine/ledger.py)): lost, duplicated or rewritten rows in `.aegis/state/ledger.jsonl` under concurrent writers, or a torn line corrupting later reads. Ledger rows from MCP tools are self-reports (advice only); they never promote a rule on their own.
- **MCP Response Projection** ([`aegis_mcp/projection.py`](aegis_mcp/projection.py)): a `view` projection leaking fields it should drop or failing to keep error results intact.
- **Supply Chain**: the release pipeline ([`.github/workflows/publish.yml`](.github/workflows/publish.yml)) publishing artifacts that differ from the verified build, or risks around the `aegis-guardrails` PyPI distribution.
- Secrets that leak into the repository, the wheel, or the sdist.

## Out of Scope

- **A malicious or compromised agent with direct shell access.** Aegis gives advice and runs deterministic checks; it does not sandbox an OS user or a shell that can change files directly. Git review and CI on the exact commit are the authoritative gate.
- **Self-reported outcomes.** `aegis_report_outcome` rows are advice-tier self-reports: any connected MCP client can write them, so they rank guidance but never promote a rule on their own.
- Vulnerabilities in third-party AI agents, MCP hosts, Python itself, or the host OS.
- Denial of service against the local stdio server by its own connected client.
- Releases older than the supported lines.

## Security Model (v4)

1. **Small MCP surface.** The server exposes four tools: `aegis_scan`, `aegis_report_outcome`, `aegis_create_rule` and `aegis_list_rules`. Every argument is checked against the tool's published schema before dispatch. Client identity (host, session) is server-owned; a tool argument cannot override it.
2. **Path confinement.** Every path is resolved and confined to the governed workspace (`aegis_core/workspace/confinement.py`, `aegis_core/storage.py`), rejecting traversal, symlink escapes, null bytes and Windows device names. State files are never written through a link.
3. **No repository-controlled execution.** Every git call goes through `aegis_core/gitsafe.py`, which neutralises repository-scope config (fsmonitor, hooks, filter drivers, submodule status) while keeping your system and user git config. Repository config cannot name commands.
4. **Rules are never rewritten behind your back.** Fitness lives in the append-only ledger (`.aegis/state/ledger.jsonl`), written under one workspace lock. Only explicit commands write rule files.
5. **Code leaves your machine only on request.** Layer 2 (`aegis check --full`) runs the model command you pass with `--llm-cmd` or `AEGIS_LLM_CMD`, never a command from repository config.
6. **Planned (v4.3):** witnessed receipts, git-witnessed rule integrity, per-rule credit and a calibrated Layer-2 arbiter. Until then this policy does not claim them.

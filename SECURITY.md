# Security Policy

## Supported Versions

Security fixes go into the latest 4.x release. Earlier major lines are not patched; v4 changed the layout, the config and the MCP surface, and [`aegis migrate`](CHANGELOG.md#upgrading-from-3x) converts a v3 workspace.

| Version | Supported |
|:--------|:---------:|
| 4.x | ✅ |
| < 4.0 | ❌ |

## Reporting a Vulnerability

Please **do not open a public issue** for a suspected vulnerability.

Report it privately through GitHub's private vulnerability reporting: open the repository's **Security** tab and choose **Report a vulnerability** (<https://github.com/nseney1/Aegis-Guardrails/security/advisories/new>). The report stays visible only to you and the maintainers.

> [!NOTE]
> This channel works only after the maintainer enables *Private vulnerability reporting* under **Settings → Code security** for the repository. If the button is missing, open a public issue that asks for a private contact channel, without any vulnerability details.

Include, where you can: the version (`aegis --version`), OS and shell, the component (`aegis_core`, `aegis_mcp`, `aegis_cli`, `aegis_sdk`), steps or a proof of concept, and the impact you observed.

Aegis Guardrails is maintained by one person, so these are goals, not guarantees: acknowledge within 7 days, confirm or reject with reasons within 30 days, and coordinate the fix and a GitHub Security Advisory with you before disclosure, crediting you unless you prefer otherwise. Fixes are recorded in the [CHANGELOG](CHANGELOG.md) and the advisory. There is no bug bounty.

## Scope

In scope: a defect that breaks one of these guarantees.

- **Path confinement** ([`aegis_core/workspace/confinement.py`](aegis_core/workspace/confinement.py), [`aegis_core/storage.py`](aegis_core/storage.py)): a tool or command reading or writing outside the governed workspace, through `..`, symlinks, NUL bytes, Windows device names or alternate data streams, or writing state through a link.
- **Repository-controlled execution** ([`aegis_core/gitsafe.py`](aegis_core/gitsafe.py), [`aegis_core/config.py`](aegis_core/config.py)): a file the repository controls (`.aegis/config.json`, rule files, `.git/config`, `.gitattributes`) making Aegis run a program it did not choose, or injecting instructions into scan output. See [Repository trust](#repository-trust) for what Aegis does run.
- **Workspace binding** ([`aegis_core/workspace/binding.py`](aegis_core/workspace/binding.py)): the MCP server governing `$HOME`, a directory above the git top level, or a repository chosen by a tool argument.
- **No automatic rule rewrites** ([`tests/integration/test_no_rule_writes.py`](tests/integration/test_no_rule_writes.py)): `aegis check`, `aegis scan`, the MCP tools or the git hook modifying files under `.aegis/rules/`. Only explicit commands (`aegis rule …`, `aegis sync --apply`, `aegis migrate --apply`) write rule files.
- **Ledger integrity** ([`aegis_core/telemetry_engine/ledger.py`](aegis_core/telemetry_engine/ledger.py)): lost, duplicated or rewritten rows in `.aegis/state/ledger.jsonl` under concurrent writers, or a torn line corrupting later reads.
- **MCP input and output** ([`aegis_mcp/server.py`](aegis_mcp/server.py), [`aegis_mcp/projection.py`](aegis_mcp/projection.py)): an argument that bypasses its tool schema, a client overriding the server-owned host or session, or a `view` projection leaking fields it should drop.
- **Supply chain** ([`.github/workflows/publish.yml`](.github/workflows/publish.yml)): a published wheel or sdist that differs from the one CI built and tested, or secrets in the repository, the wheel or the sdist.

Out of scope: an agent or person with shell access as your user (Aegis advises and checks; it does not sandbox anyone), self-reported outcomes (any connected MCP client can write them; they rank guidance and never change a rule's tier on their own), defects in agent hosts, MCP clients, Python or the OS, denial of service of the local stdio server by its own client, and versions marked ❌ above.

## Repository trust

Aegis treats a repository you clone as untrusted input. What it runs, and from where:

| What runs | When | Where it comes from |
|---|---|---|
| `git` | most commands, and `aegis_scan` | your PATH, always through `gitsafe`: the repository's own config cannot make git run anything (fsmonitor, hooks, filter drivers, credential helpers, remote protocols and submodule status are switched off; your user and system git config still apply) |
| `codex`, `claude` | `aegis init --host`, `aegis uninstall`, and `aegis doctor` (`codex mcp get` only) | by name from the absolute entries of PATH; relative and empty entries, which point into the current directory, are skipped, and doctor also skips entries inside the workspace |
| AST drivers (`node`, `go`) | `aegis check` on TypeScript or Go files, or on files your user config names a driver for | Aegis's packaged driver templates, which a repository may only switch on, or commands from your user `~/.aegis/config.json`; the interpreter must be outside the workspace, and a Python driver runs under the Python running Aegis. The packaged Rust driver starts no program: it runs inside Aegis's own process |
| `python3` | `aegis doctor` (the MCP launcher check) | the first `python3` in the absolute PATH entries outside the workspace, the one an MCP host would start. Doctor runs it twice: once with `-I -S` to print its version, and once to import `aegis_mcp`, with the current directory removed from `sys.path` |
| `pytest` | `aegis check --full` only | your active virtualenv, then `.venv/` inside the repository, then PATH. It runs the tests that match the changed files, which executes repository code (tests, `conftest.py`) just as running the suite yourself would |
| your model command | `aegis check --full` only | `--llm-cmd` or `AEGIS_LLM_CMD`, never repository files. It runs in an empty temporary directory and receives the prompt, which includes the diff, on stdin |

Plain `aegis check` and the git pre-commit hook (`aegis check --hook`) parse files and never run the repository's code or a model. Run `aegis check --full` only on code you would run yourself.

## What Aegis does not claim

Aegis signs nothing. Rules are protected by git history, review and CI on the exact commit, not by Aegis; the v3 HMAC manifest and receipts were removed because a same-user agent could forge them ([why-aegis](docs/why-aegis.md) §5). Witnessed checks, rule integrity with git as the witness and a calibrated Layer 2 arbiter are planned for v4.3 ([why-aegis](docs/why-aegis.md) §6). Until they ship, this policy does not claim them.

Release artifacts are built once in CI, recorded with SHA-256 digests, given a GitHub build provenance attestation, and published to PyPI with Trusted Publishing, so no long-lived upload token exists.

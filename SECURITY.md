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
- **Repository-controlled execution** ([`aegis_core/gitsafe.py`](aegis_core/gitsafe.py), [`aegis_core/config.py`](aegis_core/config.py), [`aegis_cli/install_hosts.py`](aegis_cli/install_hosts.py)): a file the repository controls (`.aegis/config.json`, rule files, `.git/config`, `.gitattributes`, or a package such as `aegis_mcp/` in its tree) making Aegis run a program or code it did not choose, or injecting instructions into scan output. See [Repository trust](#repository-trust) for what Aegis does run.
- **Workspace binding** ([`aegis_core/workspace/binding.py`](aegis_core/workspace/binding.py)): the MCP server governing `$HOME`, a directory above the git top level, or a repository chosen by a tool argument.
- **No automatic rule rewrites** ([`tests/integration/test_no_rule_writes.py`](tests/integration/test_no_rule_writes.py)): `aegis check`, `aegis scan`, the MCP tools or the git hook modifying files under `.aegis/rules/`. Only explicit commands (`aegis rule …`, `aegis sync --apply`, `aegis migrate --apply`) write rule files.
- **Ledger integrity** ([`aegis_core/telemetry_engine/ledger.py`](aegis_core/telemetry_engine/ledger.py)): lost, duplicated or rewritten rows in `.aegis/state/ledger.jsonl` under concurrent writers, or a torn line corrupting later reads.
- **MCP input and output** ([`aegis_mcp/server.py`](aegis_mcp/server.py), [`aegis_mcp/projection.py`](aegis_mcp/projection.py)): an argument that bypasses its tool schema, a client overriding the server-owned host or session, or a `view` projection leaking fields it should drop.
- **Host hook registration** ([`aegis_cli/hooks/registrar.py`](aegis_cli/hooks/registrar.py)): `aegis hook install --host` or `uninstall --host` changing anything in a host file other than Aegis's own entry, writing through a link, leaving a file the host cannot parse, or registering a command a repository chose.
- **Supply chain** ([`.github/workflows/publish.yml`](.github/workflows/publish.yml)): a published wheel or sdist that differs from the one CI built and tested, or secrets in the repository, the wheel or the sdist.

Out of scope: an agent or person with shell access as your user (Aegis advises and checks; it does not sandbox anyone), self-reported outcomes (any connected MCP client can write them; they rank guidance and never change a rule's tier on their own), defects in agent hosts, MCP clients, Python or the OS, denial of service of the local stdio server by its own client, and versions marked ❌ above.

## Repository trust

Aegis treats a repository you clone as untrusted input. What it runs, and from where:

| What runs | When | Where it comes from |
|---|---|---|
| `git` | most commands, and `aegis_scan` | your PATH, always through `gitsafe`: the repository's own config cannot make git run anything (fsmonitor, hooks, filter drivers, credential helpers, remote protocols and submodule status are switched off; your user and system git config still apply) |
| `codex`, `claude` | `aegis init --host`, `aegis uninstall`, and `aegis doctor` (`codex mcp get` only) | by name from the absolute entries of PATH; relative and empty entries, which point into the current directory, are skipped, and doctor also skips entries inside the workspace |
| AST drivers (`node`, `go`) | `aegis check` on TypeScript or Go files, or on files your user config names a driver for | Aegis's packaged driver templates, which a repository may only switch on, or commands from your user `~/.aegis/config.json`; the interpreter must be outside the workspace, and a Python driver runs under the Python running Aegis. The packaged Rust driver starts no program: it runs inside Aegis's own process |
| `aegis-mcp`, the MCP server | every session of a host you registered with `aegis init --host`, started by the host in the project directory | the absolute command `init` registered: the `aegis-mcp` script from an absolute PATH entry or from next to the Python running `aegis`, else that Python in isolated mode (`-I -c`) importing `aegis_mcp` from the directory Aegis is installed in. Never `python -m aegis_mcp`, which imports from the project directory first. `aegis doctor` reports as unsafe a registration that is not an absolute path, a Python that runs `-m` or `-c` without `-I` or a script by a relative path, or either behind `env`; it starts no MCP server and no `python3` |
| `aegis`, the hook handler | every matching tool call of a host where you ran `aegis hook install --host` (`aegis hook run pre-tool`); `install` itself runs it once on an empty payload, in an empty temporary directory, to refuse an `aegis` that has no `hook run` | the absolute path `install` registered: the first `aegis` in an absolute PATH entry outside the repository, else the script installed with the Python running Aegis. It must match `[A-Za-z0-9._/+-]+`, so the shell forms need no quoting. It reads the payload, the activity log and `.aegis/config.json`, starts nothing but `git`, and never runs repository code. `aegis benchmark` starts the same handler under the Python running Aegis (`-I -c`), on a built-in fixture payload in a temporary workspace, never on your repository |
| `pytest` | `aegis check --full` only | your active virtualenv, then `.venv/` inside the repository, then PATH. It runs the tests that match the changed files, which executes repository code (tests, `conftest.py`) just as running the suite yourself would |
| your model command | `aegis check --full` only | `--llm-cmd` or `AEGIS_LLM_CMD`, never repository files. It runs in an empty temporary directory and receives the prompt, which includes the diff, on stdin |

Plain `aegis check` and the git pre-commit hook (`aegis check --hook`) parse files and never run the repository's code or a model. Run `aegis check --full` only on code you would run yourself.

## Agent hooks and team leases

The 4.1 hooks and leases change files outside the repository and git refs. What each one is, and what it is not:

| What | Where | What it means for you |
|---|---|---|
| Hook entries, user scope (the default) | `~/.claude/settings.json`, `~/.codex/hooks.json`, `~/.gemini/config/hooks.json`, written by `aegis hook install --host` | your host runs `aegis hook run pre-tool` before matching tool calls in every repository; in one without `.aegis/` it does nothing. Each file is backed up to `~/.aegis/backups/` first, and a file that does not parse, is a symlink or has more than one link is refused |
| Hook entries, `--scope project` | `<repo>/.claude/settings.json`, `<repo>/.codex/hooks.json`, `<repo>/.agents/hooks.json` | committed files that your teammates' hosts will execute after they pull. Review them like code, as you would any hook a pull request adds |
| Codex rules | `~/.codex/rules/aegis.rules` | `forbidden` prefix rules for the destructive-command block set; `default.rules` is never touched |
| Codex hook trust | Codex's `/hooks` screen | Codex runs a new or changed hook only after you trust it there, and skips it silently until then. Doctor cannot see this and says so |
| The Antigravity wrapper | the `aegis` group's command | a shell line that maps the handler's exit 75 to Antigravity's blocking exit 1 and every other code to 0, so a crash never blocks. Antigravity hooks are not installed on Windows, where its hook shell is unverified |
| Team leases | `refs/aegis/lanes/<lane>` | cooperative conflict input for parallel lanes: `owner` and `role` are labels, not an identity, and nothing checks them. Anyone who can run git in the repository can claim, take over an expired lease or release one |

The hooks are guardrails, not a security boundary. They fail open on any Aegis error, a timeout or a payload they cannot read; edits made through shell commands never reach the edit check; and an agent running as your user can edit the host files. `aegis check --lane` is self-attested unless `--base-policy` reads the lane's paths from the base branch, and even then a witness is only as strong as the protection on `.github/**` and on the base branch. CI on the exact commit stays the floor.

## What Aegis does not claim

Aegis signs nothing. Rules are protected by git history, review and CI on the exact commit, not by Aegis; the v3 HMAC manifest and receipts were removed because a same-user agent could forge them ([why-aegis](docs/why-aegis.md) §5). Witnessed checks, rule integrity with git as the witness and a calibrated Layer 2 arbiter are planned for v4.3 ([why-aegis](docs/why-aegis.md) §6). Until they ship, this policy does not claim them.

Release artifacts are built once in CI, recorded with SHA-256 digests, given a GitHub build provenance attestation, and published to PyPI with Trusted Publishing, so no long-lived upload token exists.

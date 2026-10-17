# Privacy

Aegis runs on your machine. It has no service, no account and no telemetry, and its code makes no network requests. Two things can still send data elsewhere, both under your control:

- **Your agent host.** Claude Code, Codex CLI, Antigravity or another MCP client sends what Aegis returns (rules, guidance) to its model provider, under that host's own privacy terms.
- **Layer 2.** `aegis check --full` pipes a prompt that includes the changed code, your task plan and test output to the command you name with `--llm-cmd` or `AEGIS_LLM_CMD`. If that command calls a hosted model, that provider receives the prompt. Without `--full`, `aegis check` sends nothing anywhere.

## What Aegis stores

In the repository, under `.aegis/state/` (git-ignored by `aegis init`):

- `ledger.jsonl`: outcome rows: rule id, outcome, source, host, session id, time, and the checked file paths and verdict.
- `activity.jsonl`: MCP scan and edit events (file paths, host, session id, client name and version), read by `aegis status --compliance`.
- `gate_events.jsonl`: decisions of `aegis hook safety-gate`, with the command text cut to 200 characters and known secret patterns redacted.
- `derived.json`: the fitness view `aegis sync` writes. `migrate-backup-*/`: the files `aegis migrate --apply` replaced.

In your home directory:

- `~/.aegis/workspaces.json`: the absolute paths of the repositories you ran `aegis init` in, and their hosts.
- `~/.aegis/link.key`: 32 random bytes (`0600`) created by `aegis init` to pseudonymize host session IDs into keyed `hs` hashes.
- `~/.aegis/insights/<workspace-id>.jsonl`: opt-in user-scope insight rows (`0600`) holding redacted correction excerpts (`<= 300` characters, with PEM blocks, tokens, credentials, emails, home paths and IPv4 addresses scrubbed) and text-free session heartbeats.
- `~/.aegis/backups/`: copies of the host config files `aegis doctor --fix` changed (owner-only permissions; they can contain other servers' settings).
- The `aegis` entry in each host's own config, written through that host's CLI or config file.

To remove it: `aegis uninstall` takes out the host registrations, the instruction-file blocks, the git hook block and the registry entry; deleting `.aegis/` and `~/.aegis/` removes the rest.

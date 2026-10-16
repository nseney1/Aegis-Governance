# Aegis reference

Every `aegis` command and option, and every tool the `aegis-mcp` server offers, with
its input schema. This page is generated from the contract snapshots
(`tests/contract/cli_tree.json` and `tests/contract/mcp_tools.json`) by
`tests/contract/gen_reference.py`, and a test fails when it drifts from them. Do not
edit it by hand: change the code, then regenerate the snapshots and this page:

```
PYTHONPATH=. python3 tests/contract/test_cli_contract.py --write
PYTHONPATH=. python3 tests/contract/test_mcp_contract.py --write
PYTHONPATH=. python3 tests/contract/gen_reference.py --write
```

## Command line: `aegis`

Aegis Governance — make AI coding agents trustworthy

### Global options

Every command also accepts `-h/--help`, `--json`, `--plain` and `--workspace`.

| Argument | Value | Default | Description |
| --- | --- | --- | --- |
| `-h`, `--help` |  |  | show this help message and exit |
| `--json` |  |  | Emit machine-readable JSON output |
| `--plain` |  |  | Strip ANSI styling and emoji |
| `--workspace` | `WORKSPACE` |  | Target workspace root |
| `--version` |  |  | show program's version number and exit |

### Commands

| Command | Category | Description |
| --- | --- | --- |
| `aegis doctor` | Setup & Environment | System health and governance audit |
| `aegis init` | Setup & Environment | Set up governance for this project and register it with your agent hosts |
| `aegis migrate` | Setup & Environment | Convert a v3 or .soma workspace to the v4 layout (dry run unless --apply) |
| `aegis uninstall` | Setup & Environment | Remove Aegis from this workspace's hosts, AGENTS.md/CLAUDE.md and git hook (keeps .aegis/) |
| `aegis check` | Daily Workflow & Verification | Verify changes: Layer 1 checks, plus a Layer 2 model review with --full |
| `aegis scan` | Daily Workflow & Verification | Show which rules apply to the given files (run before editing them) |
| `aegis status` | Daily Workflow & Verification | Show active rules and stats |
| `aegis rule` | Rule Evolution & Intelligence | Manage rule lifecycle (list, create, promote, demote, archive) |
| `aegis sync` | Rule Evolution & Intelligence | Rebuild rule fitness from the ledger and suggest promotions (--apply to apply them) |
| `aegis hook` | Plumbing | Install, inspect or remove the git pre-commit hook and the agent hosts' PreToolUse hooks |

### `aegis doctor`

System health and governance audit

Read-only health checks, the host matrix (binary, registration, identity, workspace, bootstrap, budget per host) and the enforcement tiers in force here. --fix changes only what doctor reported (stale v3 and misplaced MCP entries, v3 hook entries, legacy rule blocks, unedited v3 rule copies, missing packaged AST drivers), after confirmation, backing each file up to ~/.aegis/backups/<UTC stamp>/ first.

Category: Setup & Environment.

| Argument | Value | Default | Description |
| --- | --- | --- | --- |
| `--fix` |  |  | Repair what doctor reported, after confirmation; every file is backed up first |
| `--yes` |  |  | With --fix: apply without asking (required with --json or without a terminal) |
| `--drivers` |  |  | Run only AST driver and language detection health check |

### `aegis init`

Set up governance for this project and register it with your agent hosts

Set up .aegis/ (config, starter rules, .gitignore), the Aegis block in AGENTS.md (and an @AGENTS.md block in an existing CLAUDE.md), the git pre-commit hook, and this workspace's entry in ~/.aegis/workspaces.json {"v": 1, "workspaces": [{root, added_at, added_by, hosts}]}, which only aegis init and aegis uninstall write. Hosts named with --host get the 'aegis' MCP server (codex-cli: codex mcp add; claude-code: claude mcp add --scope user; antigravity: ~/.gemini/config/mcp_config.json).

Category: Setup & Environment.

| Argument | Value | Default | Description |
| --- | --- | --- | --- |
| `--host` | `HOST[,HOST]|auto` |  | Register the Aegis MCP server with these hosts (codex-cli, claude-code, antigravity), or 'auto' for the ones detected on this machine. Without it, detected hosts are only listed. |
| `--rules` | one of `minimal`, `standard`, `full` | `"standard"` | Starter rules to seed into .aegis/rules/personas/ (default: standard) |
| `--dry-run` |  |  | Check and show every step without writing anything or running a host CLI |
| `--yes`, `-y` |  |  | Skip the confirmation prompt |
| `--force` |  |  | Replace Aegis blocks in AGENTS.md/CLAUDE.md even if they were edited by hand |
| `--pin` |  |  | Pin the host registrations to this workspace (AEGIS_WORKSPACE) |
| `--no-hooks` |  |  | Skip installing the git pre-commit hook |

### `aegis migrate`

Convert a v3 or .soma workspace to the v4 layout (dry run unless --apply)

Plan, then with --apply perform, the move to the v4 layout: the v3 ledger becomes .aegis/state/ledger.jsonl (v2 rows), aegis.conf/slots.yaml/config.yaml become .aegis/config.json, .soma cells move to .aegis/rules/<type>/, derived counters leave rule frontmatter and v3 runtime state is removed. Every changed file is backed up to .aegis/state/migrate-backup-<time>/ first; running it again changes nothing.

Category: Setup & Environment.

| Argument | Value | Default | Description |
| --- | --- | --- | --- |
| `--apply` |  |  | Perform the migration (default: dry run) |
| `--dry-run` |  |  | Only report what would change (the default) |

### `aegis uninstall`

Remove Aegis from this workspace's hosts, AGENTS.md/CLAUDE.md and git hook (keeps .aegis/)

Remove the git pre-commit hook block, the Aegis blocks in AGENTS.md and CLAUDE.md, this workspace's entry in ~/.aegis/workspaces.json and the Aegis MCP registration (including the v3 name) of the hosts it was registered with. A host that another registered workspace still lists keeps its registration unless named with --host. Never deletes .aegis/.

Category: Setup & Environment.

| Argument | Value | Default | Description |
| --- | --- | --- | --- |
| `--host` | `HOST[,HOST]` |  | Unregister these hosts even if another workspace uses them (default: the hosts this workspace was registered with) |
| `--dry-run` |  |  | Show what would be removed without changing anything |
| `--force` |  |  | Also remove Aegis blocks that were edited by hand |

### `aegis check`

Verify changes: Layer 1 checks, plus a Layer 2 model review with --full

Category: Daily Workflow & Verification.

| Argument | Value | Default | Description |
| --- | --- | --- | --- |
| `files` | `[FILES ...]` |  | Files to check (default: changed against HEAD, staged, or against the branch base) |
| `--hook` |  |  | Git pre-commit mode: Layer 1 only, never a model call |
| `--strict` |  |  | Fail on checkpoint warnings too (missing tests, hardcoded paths, stub tests...) |
| `--full` |  |  | Add Layer 2: adversarial review of the change by the --llm-cmd model |
| `--plan` | `TEXT` |  | Task plan for Layer 2 (implies --full) |
| `--plan-file` | `PATH` |  | File holding the task plan (implies --full) |
| `--llm-cmd` | `CMD` |  | Layer 2 model command, e.g. 'claude -p': gets the prompt on stdin, prints the reply. It runs in an empty temporary directory, never the repository, so give scripts absolute paths (default: $AEGIS_LLM_CMD; never read from repository files) |
| `--dry-run` |  |  | Show what would be checked without running anything |
| `--format` | one of `text`, `json` | `"text"` | Output format |

### `aegis scan`

Show which rules apply to the given files (run before editing them)

Category: Daily Workflow & Verification.

| Argument | Value | Default | Description |
| --- | --- | --- | --- |
| `files` | `FILE [FILE ...]` |  | File(s) you are about to edit (required) |

### `aegis status`

Show active rules and stats

Category: Daily Workflow & Verification.

| Argument | Value | Default | Description |
| --- | --- | --- | --- |
| `--compliance` |  |  | Show the per-host scan-before-edit rate from the MCP activity log (.aegis/state/activity.jsonl), per session and per host. Edits are the files a session named in aegis_report_outcome 'files' plus the files of commits inside exactly one session's window (first to last event, plus 15 minutes). Limits: an edit time is an upper bound (report or commit time), so the rate can overstate compliance; uncommitted edits that were never reported are not seen; commits in overlapping sessions count as ambiguous, not as misses; a session with no observed edit is unknown, never 0. A host rate is an aggregate over sessions, not a per-attempt verdict. Reads only. |

### `aegis rule`

Manage rule lifecycle (list, create, promote, demote, archive)

Category: Rule Evolution & Intelligence. Subcommands: `archive`, `create`, `demote`, `list`, `promote`.

### `aegis rule archive`

Archive rules whose ledger evidence says they misfire

| Argument | Value | Default | Description |
| --- | --- | --- | --- |
| `--dry-run` |  |  | Report the rules that would be archived; move nothing |

### `aegis rule create`

Create a new governance rule

| Argument | Value | Default | Description |
| --- | --- | --- | --- |
| `-t`, `--type` | `TYPE` | `"trap"` | Rule type (invariant, trap, gate, boundary, persona, contract) |
| `--hypothesis` | `HYPOTHESIS` | `""` | Testable rule hypothesis |
| `-p`, `--prediction` | `PREDICTION` | `""` | Expected outcome when hypothesis holds |
| `-f`, `--falsification` | `FALSIFICATION` | `""` | Criteria that falsify the rule |
| `-d`, `--domain` | `DOMAIN` | `"correctness"` | Governance domain |
| `-e`, `--enforcement` | `ENFORCEMENT` |  | Enforcement tier (gate, advisory) |
| `-n`, `--name`, `--id` | `ID` |  | Explicit rule ID stem |
| `--target-paths` | `TARGET_PATHS` | `""` | Comma-separated target path globs |
| `--tags` | `TAGS` | `""` | Comma-separated tags |
| `--body-file` | `PATH` |  | Rule body (markdown after the frontmatter) from PATH, or '-' for stdin; max 64 KiB |

### `aegis rule demote`

Demote a rule down lifecycle tiers (no RULE_ID: list candidates)

| Argument | Value | Default | Description |
| --- | --- | --- | --- |
| `rule_id` | `[RULE_ID]` |  | Rule identifier to demote |
| `--dry-run` |  |  | Preview demotion without moving files |

### `aegis rule list`

List active rules and fitness metrics

| Argument | Value | Default | Description |
| --- | --- | --- | --- |
| `--type` | one of `invariant`, `trap`, `gate`, `boundary`, `persona`, `contract` |  | Filter by rule type |
| `--min-fitness` | `MIN_FITNESS` |  | Filter by minimum fitness score |

### `aegis rule promote`

Promote a rule up lifecycle tiers (no RULE_ID: list candidates)

| Argument | Value | Default | Description |
| --- | --- | --- | --- |
| `rule_id` | `[RULE_ID]` |  | Rule identifier to promote |
| `--tier-check` |  |  | Evaluate enforcement tier transitions |
| `--dry-run` |  |  | Preview promotion without moving files |

### `aegis sync`

Rebuild rule fitness from the ledger and suggest promotions (--apply to apply them)

Category: Rule Evolution & Intelligence.

| Argument | Value | Default | Description |
| --- | --- | --- | --- |
| `--apply` |  |  | Apply the suggested promote/demote/archive transitions (moves rule files) |

### `aegis hook`

Install, inspect or remove the git pre-commit hook and the agent hosts' PreToolUse hooks

Category: Plumbing. Subcommands: `install`, `run`, `safety-gate`, `status`, `uninstall`.

### `aegis hook install`

Install the git pre-commit hook, or with --host an agent host's PreToolUse hook

Without --host: install the git pre-commit hook (it runs aegis check --hook). With --host claude-code\|codex-cli\|antigravity: register `aegis hook run pre-tool --host <h>` as that host's PreToolUse hook, at user scope (default) or, with --scope project, in the repository's host file, which teammates' hosts will execute. The merge keeps everything else in the file, refuses unparseable, symlinked or hard-linked files, and backs the old file up to ~/.aegis/backups/<stamp>/<scope>/. Codex also gets ~/.codex/rules/aegis.rules and runs the hook only after you trust it in /hooks; Antigravity hooks are unavailable on Windows. aegis doctor shows each host's entries and tier; it cannot confirm that a host runs them. Run it from any directory but your home directory, which Aegis never takes as a workspace, even for --scope user (which changes only your user files). Known gaps: - Edits made through shell commands never reach the edit gate on any host. - Codex write_stdin into an interactive shell has no PreToolUse payload, and the Codex Bash payload carries no working directory. - Antigravity manage_task with send_input types into a background terminal past run_command. - Aegis never emits an 'ask' decision (it fails open on Codex and soft-denies in agy headless runs). - The hooks fail open on any Aegis error: they are guardrails, not a security boundary.

| Argument | Value | Default | Description |
| --- | --- | --- | --- |
| `--force` |  |  | Git hook only: overwrite symlinks pointing outside repository |
| `--dry-run` |  |  | Preview without creating or modifying hook |
| `--host` | `HOST` |  | Register the PreToolUse hook with this host instead of the git hook: claude-code, codex-cli, antigravity |
| `--scope` | one of `user`, `project` |  | With --host: user (default) or project |

### `aegis hook run`

Run the agent-host hook on the payload on stdin (what host hook registrations call)

Reads the host's PreToolUse JSON on stdin and never prints on stdout. Exit 0 allows, and also follows any error, a timeout, an unknown host or event and an ungoverned workspace: the hooks fail open. Exit 2 blocks on claude-code and codex-cli (reason on stderr); exit 75 blocks on antigravity, whose registration maps it to 1.

| Argument | Value | Default | Description |
| --- | --- | --- | --- |
| `event` | `[EVENT]` |  | The hook event: pre-tool |
| `--host` | `HOST` |  | The host whose payload is on stdin: claude-code, codex-cli or antigravity |

### `aegis hook safety-gate`

Check a shell command against the safety gate (prints a JSON decision)

| Argument | Value | Default | Description |
| --- | --- | --- | --- |
| `--cmd` | `CMD` |  | Command line to check (default: JSON payload on stdin) |

### `aegis hook status`

Inspect the pre-commit hook and the interpreter it runs

### `aegis hook uninstall`

Remove the aegis block from the pre-commit hook, or with --host an agent host's PreToolUse hook

Without --host: remove the aegis block from the git pre-commit hook. With --host: remove Aegis's PreToolUse entries from that host's files at --scope (default: both scopes) and nothing else, backing each file up first; for Codex also ~/.codex/rules/aegis.rules once no Aegis Codex hook is left. Run it from any directory but your home directory, which Aegis never takes as a workspace, even for --scope user (which changes only your user files).

| Argument | Value | Default | Description |
| --- | --- | --- | --- |
| `--force` |  |  | Git hook only: force removal |
| `--dry-run` |  |  | Preview without modifying disk |
| `--host` | `HOST` |  | Remove Aegis's PreToolUse hook entries from this host instead of the git hook: claude-code, codex-cli, antigravity |
| `--scope` | one of `user`, `project` |  | With --host: only this scope (default: both) |

### Removed commands

Each of these exits with status 2 and prints where to go instead.

| Command | Instead |
| --- | --- |
| `aegis agent` | use aegis scan to see which rules apply; record outcomes with the MCP tool aegis_report_outcome |
| `aegis agent record` | use aegis_report_outcome (MCP) |
| `aegis agent scan` | use aegis scan |
| `aegis audit` | use aegis doctor |
| `aegis checkpoint` | use aegis check |
| `aegis completion` | no replacement |
| `aegis detect` | use aegis doctor |
| `aegis drivers` | use aegis doctor |
| `aegis handoff` | no replacement |
| `aegis hook governance-monitor` | no replacement; remove it from your agent host's hook config |
| `aegis hook immune-init` | no replacement; remove it from your agent host's hook config |
| `aegis hook post-session` | no replacement; remove it from your agent host's hook config |
| `aegis hook pre-commit` | use aegis check --hook |
| `aegis hook pre-invocation` | no replacement; remove it from your agent host's hook config |
| `aegis hook session-close` | no replacement; remove it from your agent host's hook config |
| `aegis hook stop` | no replacement; remove it from your agent host's hook config |
| `aegis install` | use aegis init --host |
| `aegis languages` | use aegis doctor |
| `aegis report` | aegis status shows rule trigger counts; outcomes are recorded with the MCP tool aegis_report_outcome |
| `aegis rule clean` | no replacement; remove leaked global rule copies by hand |
| `aegis rules` | use aegis status |
| `aegis skill` | no replacement |
| `aegis sys` | use aegis doctor |
| `aegis system` | use aegis doctor |
| `aegis system doctor` | use aegis doctor |
| `aegis system drivers` | use aegis doctor |
| `aegis system hook` | use aegis hook |
| `aegis verify` | use aegis check |

## MCP server: `aegis-mcp`

The server speaks MCP over stdio. Its tools, as `tools/list` returns them:

| Tool | Title |
| --- | --- |
| `aegis_scan` | Scan JIT Rules |
| `aegis_report_outcome` | Report Outcome |
| `aegis_create_rule` | Create Rule |
| `aegis_list_rules` | List Rules |

### `aegis_scan`

**Scan JIT Rules** (read-only, idempotent)

Call before editing files: returns the governance rules that apply to them, ranked by ledger fitness and clamped to the JIT token budget. Mandatory rules (gates, invariants) take at most two slots; the others are listed in omitted_mandatory. stale_rules lists rules edited since the last aegis sync. If any rule file cannot be loaded the scan fails (status FAIL) and names it.

| Parameter | Type | Required | Description |
| --- | --- | --- | --- |
| `files` | array of string | no | Workspace-relative files you are about to edit. Defaults to the git diff. |
| `view` | string: one of `"full"`, `"summary"`, `"ids"` | no | Optional response projection: full (default), summary or ids. |

Input schema:

```json
{
  "type": "object",
  "properties": {
    "files": {
      "type": "array",
      "items": {
        "type": "string"
      },
      "description": "Workspace-relative files you are about to edit. Defaults to the git diff."
    },
    "view": {
      "type": "string",
      "enum": [
        "full",
        "summary",
        "ids"
      ],
      "description": "Optional response projection: full (default), summary or ids."
    }
  },
  "additionalProperties": false
}
```

### `aegis_report_outcome`

**Report Outcome** (idempotent)

Report whether the rules you were shown helped. Each report is an advisory self-report row in the outcome ledger; it never promotes a rule by itself.

| Parameter | Type | Required | Description |
| --- | --- | --- | --- |
| `outcome` | string: one of `"success"`, `"partial"`, `"failure"`, `"tp"`, `"fp"`, `"pass"`, `"fail"` | yes | Verification outcome. |
| `idempotency_key` | string | yes | Unique key for this report. Retrying with the same key never records twice. |
| `rules_used` | array of string | yes | Names of the rules this outcome is about, as aegis_scan returned them. |
| `tests_passed` | boolean | no |  |
| `rework_count` | integer | no |  |
| `notes` | string | no |  |
| `files` | array of string | no | Optional: the files this change edited (workspace-relative). They measure scan-before-edit compliance (aegis status --compliance); they credit no rule. |
| `view` | string: one of `"full"`, `"summary"`, `"ids"` | no | Optional response projection: full (default), summary or ids. |

Input schema:

```json
{
  "type": "object",
  "properties": {
    "outcome": {
      "type": "string",
      "enum": [
        "success",
        "partial",
        "failure",
        "tp",
        "fp",
        "pass",
        "fail"
      ],
      "description": "Verification outcome."
    },
    "idempotency_key": {
      "type": "string",
      "maxLength": 256,
      "description": "Unique key for this report. Retrying with the same key never records twice."
    },
    "rules_used": {
      "type": "array",
      "items": {
        "type": "string"
      },
      "minItems": 1,
      "description": "Names of the rules this outcome is about, as aegis_scan returned them."
    },
    "tests_passed": {
      "type": "boolean"
    },
    "rework_count": {
      "type": "integer",
      "default": 0
    },
    "notes": {
      "type": "string",
      "maxLength": 4096
    },
    "files": {
      "type": "array",
      "items": {
        "type": "string"
      },
      "description": "Optional: the files this change edited (workspace-relative). They measure scan-before-edit compliance (aegis status --compliance); they credit no rule."
    },
    "view": {
      "type": "string",
      "enum": [
        "full",
        "summary",
        "ids"
      ],
      "description": "Optional response projection: full (default), summary or ids."
    }
  },
  "required": [
    "outcome",
    "rules_used",
    "idempotency_key"
  ],
  "additionalProperties": false
}
```

### `aegis_create_rule`

**Create Rule** (read-only, idempotent)

Turn a natural language concern into a prompt that drafts a governance rule. It writes nothing: save the drafted rule under .aegis/rules/ yourself.

| Parameter | Type | Required | Description |
| --- | --- | --- | --- |
| `description` | string | yes | The concern, in natural language. |
| `rule_type` | string: one of `"invariant"`, `"trap"`, `"gate"`, `"boundary"`, `"persona"`, `"contract"` | no | Optional rule type hint. |
| `domain` | string | no | Optional domain hint. |

Input schema:

```json
{
  "type": "object",
  "properties": {
    "description": {
      "type": "string",
      "description": "The concern, in natural language."
    },
    "rule_type": {
      "type": "string",
      "enum": [
        "invariant",
        "trap",
        "gate",
        "boundary",
        "persona",
        "contract"
      ],
      "description": "Optional rule type hint."
    },
    "domain": {
      "type": "string",
      "description": "Optional domain hint."
    }
  },
  "required": [
    "description"
  ],
  "additionalProperties": false
}
```

### `aegis_list_rules`

**List Rules** (read-only, idempotent)

List the governance rules as {rules, stale_rules, ignored}: every rule with its type, hypothesis and ledger fitness (a file that cannot be loaded is listed with _error), the rules edited since the last aegis sync, and markdown under .aegis/rules that is not a rule.

| Parameter | Type | Required | Description |
| --- | --- | --- | --- |
| `rule_type` | string: one of `"invariant"`, `"trap"`, `"gate"`, `"boundary"`, `"persona"`, `"contract"` | no | Optional rule type filter. |
| `view` | string: one of `"full"`, `"summary"`, `"ids"` | no | Optional response projection: full (default), summary or ids. |

Input schema:

```json
{
  "type": "object",
  "properties": {
    "rule_type": {
      "type": "string",
      "enum": [
        "invariant",
        "trap",
        "gate",
        "boundary",
        "persona",
        "contract"
      ],
      "description": "Optional rule type filter."
    },
    "view": {
      "type": "string",
      "enum": [
        "full",
        "summary",
        "ids"
      ],
      "description": "Optional response projection: full (default), summary or ids."
    }
  },
  "additionalProperties": false
}
```

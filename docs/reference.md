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
| `aegis skills` | Setup & Environment | Copy the packaged skills into your hosts' project skills folders (sync) |
| `aegis uninstall` | Setup & Environment | Remove Aegis from this workspace's hosts, AGENTS.md/CLAUDE.md and git hook (keeps .aegis/) |
| `aegis check` | Daily Workflow & Verification | Verify changes: Layer 1 checks, plus a Layer 2 model review with --full |
| `aegis scan` | Daily Workflow & Verification | Show which rules apply to the given files (run before editing them) |
| `aegis status` | Daily Workflow & Verification | Show active rules and stats |
| `aegis team` | Daily Workflow & Verification | Lease lane paths for parallel agents (claim, renew, transfer, release, gc, list, metrics) |
| `aegis rule` | Rule Evolution & Intelligence | Manage rule lifecycle (list, create, promote, demote, archive) |
| `aegis sync` | Rule Evolution & Intelligence | Rebuild rule fitness from the ledger and suggest promotions (--apply to apply them) |
| `aegis hook` | Plumbing | Install, inspect or remove the git pre-commit hook |

### `aegis doctor`

System health and governance audit

Read-only health checks, the host matrix (binary, registration, identity, workspace, bootstrap, budget per host) and the enforcement tiers in force here. --fix changes only what doctor reported (stale v3 and misplaced MCP entries, legacy rule blocks, unedited v3 rule copies, missing packaged AST drivers), after confirmation, backing each file up to ~/.aegis/backups/<UTC stamp>/ first.

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
| `--skills` |  |  | Also copy the packaged skills into the hosts' project skills folders (.claude/skills, .agents/skills), as aegis skills sync does |

### `aegis migrate`

Convert a v3 or .soma workspace to the v4 layout (dry run unless --apply)

Plan, then with --apply perform, the move to the v4 layout: the v3 ledger becomes .aegis/state/ledger.jsonl (v2 rows), aegis.conf/slots.yaml/config.yaml become .aegis/config.json, .soma cells move to .aegis/rules/<type>/, derived counters leave rule frontmatter and v3 runtime state is removed. Every changed file is backed up to .aegis/state/migrate-backup-<time>/ first; running it again changes nothing.

Category: Setup & Environment.

| Argument | Value | Default | Description |
| --- | --- | --- | --- |
| `--apply` |  |  | Perform the migration (default: dry run) |
| `--dry-run` |  |  | Only report what would change (the default) |

### `aegis skills`

Copy the packaged skills into your hosts' project skills folders (sync)

Category: Setup & Environment. Subcommands: `sync`.

### `aegis skills sync`

Copy the packaged skills to .claude/skills (Claude Code) and .agents/skills (Codex CLI, Antigravity), replacing only Aegis's own unedited copies

| Argument | Value | Default | Description |
| --- | --- | --- | --- |
| `--host` | `HOST[,HOST]|auto` |  | Hosts to copy skills for (default: the hosts in .aegis/config.json); 'auto' takes the ones detected on this machine |
| `--force` |  |  | Also replace Aegis copies edited by hand (never a file without the Aegis marker, a link or anything outside the workspace) |
| `--dry-run` |  |  | Report what would change; write nothing |

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
| `--lane` | `LANE` |  | Post-lane gate: check the lane's commits since merge-base(--base, HEAD) for containment (every changed path, deletions and both sides of a move included, inside the lane's globs) and Python test integrity (removed tests, added skips or xfails, pytest collection changes; assert weakening is not detected). Any finding fails. Self-attested from the live lease or --paths; witnessed with --base-policy. As a CI job it is advisory in v4.1, and a witness is only as strong as the protection on .github/** and on the base branch |
| `--base` | `REF` |  | With --lane: the base branch (default: origin/$GITHUB_BASE_REF, $GITHUB_BASE_REF, origin/main, main, origin/develop or develop). A shallow clone fails: fetch with fetch-depth 0 |
| `--paths` | `GLOB [GLOB ...]` |  | With --lane: the lane's globs instead of its live lease (self-attested). They match as rule target_paths do: a glob without '/' matches at any depth, so CHANGELOG.md also admits docs/CHANGELOG.md. They never allow .aegis/** or .github/workflows/** |
| `--base-policy` |  |  | With --lane: take lanes.<lane> and shared from .aegis/team.json at the base tip, never the candidate; refuses --paths. Only then is the result 'witnessed: base policy', and only then may .aegis/** and .github/workflows/** change |

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

### `aegis team`

Lease lane paths for parallel agents (claim, renew, transfer, release, gc, list, metrics)

Leases under refs/aegis/lanes/<lane> declare which paths a lane works on. A lease is cooperative conflict input, not a lock, not an identity and not proof that an agent is alive: claims of different lanes can race, and owner and role are display labels. The backstops are the post-lane gate (aegis check --lane) and aegis team metrics.

Category: Daily Workflow & Verification. Subcommands: `claim`, `gc`, `list`, `metrics`, `release`, `renew`, `transfer`.

### `aegis team claim`

Lease a lane's paths; prints the lease oid

Refuse when a live lease of another lane may overlap the paths; otherwise create the lane's lease, or take over its expired lease. Prints the new lease oid.

| Argument | Value | Default | Description |
| --- | --- | --- | --- |
| `lane` | `LANE` |  | Lane name: [a-z0-9][a-z0-9._-]{0,62} (required) |
| `--paths` | `GLOB [GLOB ...]` |  | Globs the lane will change (the conflict scope) |
| `--role` | `ROLE` |  | Display label (default: implementer) |
| `--owner` | `OWNER` |  | Display label (default: <user>@<hostname>) |
| `--ttl` | `SECONDS` | `3600` | Seconds until the lease expires, at most 86400 |
| `--branch` | `BRANCH` |  | The lane's branch, recorded for display |

### `aegis team gc`

Delete expired leases

Delete every expired lease by compare-and-swap; unreadable leases are kept.

### `aegis team list`

Show leases (conflict input, not liveness proof)

A lease is conflict input, not liveness proof: it records which paths a lane declared and until when, not that its agent is still working. The backstops are the post-lane gate (aegis check --lane) and aegis team metrics.

### `aegis team metrics`

Lease events and merge outcomes

Claims and denials from the events log, and for each first-parent merge since --base: whether both sides changed a common path and whether git merge-tree reports a conflict (unavailable before git 2.38). GitHub's synthetic refs/pull/*/merge commits are excluded.

| Argument | Value | Default | Description |
| --- | --- | --- | --- |
| `--base` | `REF` |  | Count merges since this commit (default: the branch base, as for aegis check --lane: origin/main, main, origin/develop or develop; with none, the whole first-parent history) |

### `aegis team release`

Delete a lease

Delete a lease by compare-and-swap. Anyone may release; the events log records the caller.

| Argument | Value | Default | Description |
| --- | --- | --- | --- |
| `lane` | `LANE` |  | Lane name: [a-z0-9][a-z0-9._-]{0,62} (required) |
| `--expect` | `OID` |  | The lease oid the lane must hold now (printed by claim, renew, transfer and list) |

### `aegis team renew`

Extend a lease; prints the new lease oid

Renew by compare-and-swap; an expired lease is re-claimed, overlap check included.

| Argument | Value | Default | Description |
| --- | --- | --- | --- |
| `lane` | `LANE` |  | Lane name: [a-z0-9][a-z0-9._-]{0,62} (required) |
| `--expect` | `OID` |  | The lease oid the lane must hold now (printed by claim, renew, transfer and list) |
| `--ttl` | `SECONDS` |  | New lifetime in seconds, at most 86400 (default: keep it) |

### `aegis team transfer`

Give a live lease to another owner

Change a live lease's owner (and role) by compare-and-swap.

| Argument | Value | Default | Description |
| --- | --- | --- | --- |
| `lane` | `LANE` |  | Lane name: [a-z0-9][a-z0-9._-]{0,62} (required) |
| `--expect` | `OID` |  | The lease oid the lane must hold now (printed by claim, renew, transfer and list) |
| `--owner` | `OWNER` |  | The new owner label |
| `--role` | `ROLE` |  | The new role label (default: keep it) |

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

Install, inspect or remove the git pre-commit hook

Category: Plumbing. Subcommands: `install`, `run`, `safety-gate`, `status`, `uninstall`.

### `aegis hook install`

Install the pre-commit hook into the git repository

| Argument | Value | Default | Description |
| --- | --- | --- | --- |
| `--force` |  |  | Overwrite symlinks pointing outside repository |
| `--dry-run` |  |  | Preview without creating or modifying hook |

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

Remove the aegis block from the pre-commit hook

| Argument | Value | Default | Description |
| --- | --- | --- | --- |
| `--force` |  |  | Force removal |
| `--dry-run` |  |  | Preview without modifying disk |

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

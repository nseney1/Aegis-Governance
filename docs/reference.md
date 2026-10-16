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
| `aegis init` | Setup & Environment | Set up governance for this project |
| `aegis migrate` | Setup & Environment | Convert a v3 or .soma workspace to the v4 layout (dry run unless --apply) |
| `aegis uninstall` | Setup & Environment | Uninstall Aegis governance rules and configuration |
| `aegis check` | Daily Workflow & Verification | Verify changes: Layer 1 checks, plus a Layer 2 model review with --full |
| `aegis scan` | Daily Workflow & Verification | Show which rules apply to the given files (run before editing them) |
| `aegis status` | Daily Workflow & Verification | Show active rules and stats |
| `aegis rule` | Rule Evolution & Intelligence | Manage rule lifecycle (list, create, promote, demote, archive) |
| `aegis sync` | Rule Evolution & Intelligence | Rebuild rule fitness from the ledger and suggest promotions (--apply to apply them) |
| `aegis hook` | Plumbing | Install, inspect or remove the git pre-commit hook |

### `aegis doctor`

System health and governance audit

Category: Setup & Environment.

| Argument | Value | Default | Description |
| --- | --- | --- | --- |
| `--fix` |  |  | Automatically repair detected issues (pre-commit hooks, missing AST drivers) |
| `--drivers` |  |  | Run only AST driver and language detection health check |

### `aegis init`

Set up governance for this project

Category: Setup & Environment.

| Argument | Value | Default | Description |
| --- | --- | --- | --- |
| `--dry-run` |  |  | Show what would be installed without doing it |
| `--platform` | one of `gemini`, `claude`, `cursor`, `copilot`, `kiro` |  | Skip platform detection, force a platform |
| `--local` |  |  | Install rules to project-local directory instead of user home |
| `--rules` | one of `minimal`, `standard`, `full` | `"standard"` | Rule set to install (default: standard) |
| `--mcp` |  |  | Generate .mcp.json for JIT rule matching |
| `--yes`, `-y` |  |  | Skip confirmation prompts |
| `--force` |  |  | Overwrite existing rules |
| `--no-hooks` |  |  | Skip installing git pre-commit hook |

### `aegis migrate`

Convert a v3 or .soma workspace to the v4 layout (dry run unless --apply)

Plan, then with --apply perform, the move to the v4 layout: the v3 ledger becomes .aegis/state/ledger.jsonl (v2 rows), aegis.conf/slots.yaml/config.yaml become .aegis/config.json, .soma cells move to .aegis/rules/<type>/, derived counters leave rule frontmatter and v3 runtime state is removed. Every changed file is backed up to .aegis/state/migrate-backup-<time>/ first; running it again changes nothing.

Category: Setup & Environment.

| Argument | Value | Default | Description |
| --- | --- | --- | --- |
| `--apply` |  |  | Perform the migration (default: dry run) |
| `--dry-run` |  |  | Only report what would change (the default) |

### `aegis uninstall`

Uninstall Aegis governance rules and configuration

Category: Setup & Environment.

| Argument | Value | Default | Description |
| --- | --- | --- | --- |
| `--platform`, `-p` | one of `gemini`, `kiro`, `copilot`, `claude`, `mcp` |  | Target platform (default: auto-detected or gemini) |
| `--local` |  |  | Uninstall from project-local directory |
| `--dry-run` |  |  | Show what would be uninstalled without deleting files |
| `--purge` |  |  | Purge .aegis directory and local governance state |

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

Category: Plumbing. Subcommands: `install`, `safety-gate`, `status`, `uninstall`.

### `aegis hook install`

Install the pre-commit hook into the git repository

| Argument | Value | Default | Description |
| --- | --- | --- | --- |
| `--force` |  |  | Overwrite symlinks pointing outside repository |
| `--dry-run` |  |  | Preview without creating or modifying hook |

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

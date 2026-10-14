---
name: Genesis — Codebase Onboarding Reconnaissance
description: Four-stage read-only reconnaissance protocol mapping structure, history, architecture, and governance in unfamiliar codebases.
trigger: user_request
aliases: ["genesis", "init", "onboard", "explore", "map this repo", "what is this codebase"]
---

# Genesis — Codebase Onboarding Reconnaissance

> **Role**: Maps an unfamiliar codebase across four read-only stages — structure, history, architecture, and governance fitness — then produces a persistent Genesis Report artifact. The output feeds downstream skills (Spores priority, Mycelium blast-radius, Context Pre-Seeding) so the governance system has situational awareness from the first interaction.

## Stages

| Stage | Name | Subagent | Flash Dispatches | Focus |
|:------|:-----|:---------|:----------------:|:------|
| 1 | 🗺️ **Canopy** | Broad Repo Scanner | 1–2 | Tech stack, directory tree, dependencies, entry points, test framework, dev environment probe |
| 2 | 📜 **Rings** | Git History Analyst | 1 | Branch topology, commit frequency, churn heatmap, high-risk files |
| 3 | 📖 **Taproot** | Architecture Analyst | 1–2 | API surface, data models, config patterns, external integrations, cross-repo boundaries |
| 4 | 🧭 **Lichen** | Governance Advisor | 1 | Conventions, test patterns, deployment model, traps, governance config, Context Pre-Seeding |

**Total dispatches**: 4–6 Flash subagents across all stages.

### Stage Selection

Genesis stages are **incremental** — run any subset, in any order. Later stages build on earlier outputs when available but degrade gracefully without them.

| Need | Stages | Dispatches | When to Use |
|:-----|:------:|:----------:|:------------|
| Quick layout | Canopy only | 1–2 | "What is this repo?" — fast directory orientation |
| Risk assessment | Canopy + Rings | 2–3 | "Where are the hot spots?" — churn + structure |
| Architecture audit | Canopy + Taproot | 2–4 | "How is this system designed?" — API and data model mapping |
| Full onboarding | All 4 stages | 4–6 | "Onboard me to this codebase" — complete reconnaissance |
| Governance setup | Lichen | 1 | "Configure governance for this project" — re-run synthesis |

---

## Design Invariants

1. **Read-only**: Genesis NEVER modifies the repository. It produces artifacts only — no writes, no commits, no branch creation.
2. **Incremental**: Any single stage can run standalone. Stages build on prior outputs when available but function independently.
3. **Multi-repo**: Accepts multiple repo paths for multi-service architectures. Each repo gets its own stage passes; Lichen synthesizes across all of them.
4. **Cacheable**: Output persists as a governance artifact (`genesis-report-[project].md`). Subsequent runs diff against the previous report and highlight what changed.
5. **Feeds downstream**: Canopy → Context Pre-Seeding. Rings → Spores priority ranking. Taproot → Mycelium blast-radius context. Lichen → governance configuration.

---

## Stage 1: Canopy (Repository Structure Mapping)

Dispatch 1–2 Flash broad repo scanners to map the repository's physical structure.

### Scanner Objectives

| Objective | Method | Output |
|:----------|:-------|:-------|
| Tech stack | Detect language files, framework markers (`next.config.js`, `pom.xml`, `Cargo.toml`) | `{language, framework, build_system, package_manager}` |
| Directory tree | `find` / `fd` with annotated roles | Annotated tree (max 3 levels, role per directory) |
| Dependencies | Parse manifest files (`package.json`, `requirements.txt`, `build.gradle`, `go.mod`, etc.) | Dependency list with counts (direct vs transitive) |
| Entry points | Identify main classes, `index.*`, `server.*`, `main.*`, CLI entry points | List of entry points with file paths |
| Testing framework | Detect test runners (`jest`, `pytest`, `JUnit`, `go test`), test directories, config files | `{framework, runner_command, test_directory, config_file}` |
| Monorepo detection | Check for workspace configs (`lerna.json`, `pnpm-workspace.yaml`, Nx, Turborepo) | `{is_monorepo, workspace_tool, package_count}` |

### Dev Environment Probe

> [!NOTE]
> Local environment blindness is the #4 source of wasted agent steps (120 steps). Canopy supplements repository structure mapping with a sanitized dev environment probe, establishing situational awareness before downstream tools execute build, lint, or test commands.

> [!CAUTION]
> **Privacy Invariant**: All probe outputs must be **sanitized aggregates** — versions and booleans, NOT raw command output.
> - **NO file paths** (especially not `which python3` output, which leaks `/home/<user>/`)
> - **NO usernames** (especially not `git config user.name`, which leaks real names)
> - **NO raw environment variable values** (especially not `$SHELL`, `$TERM_PROGRAM`, `$CODESPACES`, or `$REMOTE_CONTAINERS_IPC`)
> - **NO hostnames** (use `uname -s -m`, never `hostname` or `uname -n`)

> [!IMPORTANT]
> **Orchestrator Execution Mandate**: Research subagents have **read-only tools only** — probes requiring shell execution must be performed by the parent orchestrator before dispatch. The orchestrator gathers and sanitizes the probe values, then injects the clean aggregate block into the Canopy subagent prompt (or directly records it in the report artifact).

| Probe | Method | Sanitized Output | Must NOT Output |
|:------|:-------|:----------------|:---------------|
| Shell version | `bash --version` | `shell: bash 5.x` | NOT `$SHELL` value |
| OS & arch | `uname -s -m` | `os: linux, arch: x86_64` | NOT hostname |
| Build tools | `command -v make cmake npm cargo go` | `tools: [make, npm, go]` | NOT full paths |
| Container detection | Check `/.dockerenv` existence | `container: false` | NOT env var values |
| IDE context | Check known env vars | `ide: antigravity 2.x` | NOT `$TERM_PROGRAM` raw value |
| Python environment | Check for venv markers | `python: 3.11, venv: true` | NOT `which python3` path |
| Git status | `git --version` | `git: 2.43, configured: true` | NOT `git config user.name` |
| Package managers | `command -v brew apt choco` | `pkg: [apt]` | NOT full paths |

### Canopy Prompt Template

```
<!-- CONTEXT: Genesis Canopy -->
You are a codebase reconnaissance scanner. Your job is to map the repository structure.
You are READ-ONLY — do not modify any files.

Scan this repository: [REPO_PATH]

Read these files first (if they exist):
- README.md (or README.*)
- package.json / requirements.txt / pom.xml / build.gradle / Cargo.toml / go.mod
- Makefile / Justfile / Taskfile.yml
- .github/workflows/*.yml / .gitlab-ci.yml / Jenkinsfile
- docker-compose.yml / Dockerfile

[IF DEV ENVIRONMENT INJECTED BY ORCHESTRATOR]:
Include the parent-probed dev environment block in report delivery:
[Sanitized Dev Environment Block]
[END IF]

Deliver:

### Tech Stack
- Language(s): [with version if detectable]
- Framework: [name + version]
- Build system: [tool + command]
- Package manager: [name]

### Dev Environment (if provided by orchestrator)
- Shell: [sanitized version]
- OS & arch: [sanitized os, arch]
- Build tools: [sanitized tool list]
- Container: [container boolean]
- IDE: [sanitized context]
- Python: [version, venv boolean]
- Git: [version, configured boolean]
- Package managers: [sanitized pkg list]

### Directory Tree (annotated, max 3 levels)
```
src/         — application source
tests/       — test suites
docs/        — documentation
enzymes/     — automation
...
```

### Dependencies
- Direct: [count]
- Dev: [count]
- Notable: [list any critical or unusual deps]

### Entry Points
- [file:path] — [role: server, CLI, worker, etc.]

### Testing
- Framework: [name]
- Runner: `[command]`
- Test directory: [path]
- Config: [file if present]

### Monorepo
- Is monorepo: [yes/no]
- Workspace tool: [if applicable]
- Package count: [if applicable]

[OUTPUT]: Max 5 bullets per section. Cite file paths.
<!-- END CONTEXT -->
```

---

## Stage 2: Rings (Git History Intelligence)

Dispatch 1 Flash git history analyst to extract temporal intelligence from the repository's version control history.

### Analyst Objectives

| Objective | Method | Output |
|:----------|:-------|:-------|
| Branch topology | `git branch -a`, `git log --graph` (abbreviated) | Active branches, default branch, stale branches (>90 days) |
| Commit frequency | `git log --since="6 months ago" --oneline \| wc -l` | Commits per month, trend (accelerating/stable/declining) |
| Contributor count | `git shortlog -sn --since="6 months ago"` | Active contributors with commit counts |
| Release cadence | `git tag --sort=-creatordate` | Tag frequency, last release date, versioning scheme |
| Churn heatmap | `git log --pretty=format: --name-only -100 \| sort \| uniq -c \| sort -rn \| head -20` | Top 20 most-modified files in last 100 commits |
| High-risk files | Cross-reference churn with file size/complexity | Files with both high churn AND high line count |

### Rings Prompt Template

```
<!-- CONTEXT: Genesis Rings -->
You are a git history analyst. Your job is to extract temporal intelligence from version control.
You are READ-ONLY — do not create branches, tags, or commits.

Analyze this repository: [REPO_PATH]

Run these commands (or equivalent) to gather data:
- git log --oneline -100
- git branch -a
- git shortlog -sn --since="6 months ago"
- git tag --sort=-creatordate | head -10
- git log --pretty=format: --name-only -100 | sort | uniq -c | sort -rn | head -20
- git log --diff-filter=M --since="3 months ago" --pretty=format: --name-only | sort | uniq -c | sort -rn | head -10

[IF CARTOGRAPHY OUTPUT EXISTS]:
Cross-reference churn heatmap against Canopy entry points and test files.
[Canopy output summary]
[END IF]

Deliver:

### Branch Topology
- Default branch: [name]
- Active branches: [count] (list top 5)
- Stale branches (>90 days): [count]

### Commit Activity (last 6 months)
- Total commits: [count]
- Monthly average: [count]
- Trend: [accelerating / stable / declining]
- Active contributors: [count] (list top 5 with commit counts)

### Release Cadence
- Last release: [tag @ date]
- Versioning: [semver / calver / other]
- Average release interval: [N days/weeks]

### Churn Heatmap (top 10 most-modified files, last 100 commits)
| File | Modifications | Role (from Canopy) |
|:-----|:------------:|:------------------------|
| [path] | [count] | [source / test / config / etc.] |

### High-Risk Files
[Files with both high churn (>5 modifications) AND high complexity (>200 lines)]
- [file:path] — [modifications] changes, [lines] lines — Risk: [assessment]

[OUTPUT]: Cite exact git commands used. Quantify everything.
<!-- END CONTEXT -->
```

---

## Stage 3: Taproot (Architecture Extraction)

Dispatch 1–2 Flash architecture analysts to map the system's logical architecture from code.

### Analyst Objectives

| Objective | Method | Output |
|:----------|:-------|:-------|
| API surface | Scan for route definitions, controller annotations, handler registrations | List of endpoints with HTTP method, path, handler file:line |
| Data models | Scan for schema definitions, entity classes, DTOs, migrations | Entity inventory with field counts and relationships |
| Configuration | Identify env var usage, config files, secrets management | Config pattern: `{env_vars: [], config_files: [], secrets_manager: ""}` |
| External integrations | Detect database drivers, queue clients, cache clients, HTTP clients | Service dependency map with connection patterns |
| Cross-repo boundaries | Find shared contracts (proto files, OpenAPI specs, shared types) | Boundary inventory: `{shared_schemas: [], api_specs: [], proto_files: []}` |

### Taproot Prompt Template

```
<!-- CONTEXT: Genesis Taproot -->
You are an architecture analyst. Your job is to extract the logical architecture from code.
You are READ-ONLY — do not modify any files.

Analyze this repository: [REPO_PATH]

[IF CARTOGRAPHY OUTPUT EXISTS]:
Use this structure map to focus your search:
[Canopy output summary — tech stack, directory tree, entry points]
[END IF]

[IF CHRONICLE OUTPUT EXISTS]:
Prioritize high-churn files from Rings:
[Rings churn heatmap top 10]
[END IF]

Scan for:
1. Route/endpoint definitions (Express routes, Flask blueprints, Spring controllers, etc.)
2. Schema/entity/model definitions (ORM models, Prisma schema, protobuf, etc.)
3. Environment variable usage (process.env, os.environ, etc.)
4. Database/queue/cache client initialization
5. Shared contracts (proto files, OpenAPI specs, shared type packages)

Deliver:

### API Surface
| Method | Path | Handler | File |
|:-------|:-----|:--------|:-----|
| [GET/POST/...] | [/api/...] | [function] | [file:line] |

### Data Models
| Entity | Fields | Relationships | File |
|:-------|:------:|:-------------|:-----|
| [name] | [count] | [belongs_to, has_many, etc.] | [file:line] |

### Configuration Pattern
- Config strategy: [env vars / config files / secrets manager / mixed]
- Config files: [list paths]
- Env vars referenced: [count] (list critical ones)
- Secrets management: [tool/pattern if detected]

### External Service Integrations
| Service | Type | Client Library | Connection File |
|:--------|:-----|:---------------|:---------------|
| [name] | [DB/queue/cache/API] | [library] | [file:line] |

### Cross-Repo Boundaries
- Shared schemas: [list files]
- API specs: [OpenAPI/Swagger/proto files]
- Shared type packages: [if monorepo or multi-repo]
- Contract testing: [detected / not detected]

[OUTPUT]: Max 10 rows per table. Cite file:line for every entry.
<!-- END CONTEXT -->
```

---

## Stage 4: Lichen (Contextual Synthesis & Recommendations)

Dispatch 1 Flash governance advisor to synthesize all prior stage outputs into actionable governance configuration.

### Advisor Objectives

| Objective | Method | Output |
|:----------|:-------|:-------|
| Coding conventions | Detect naming style, formatting, error handling patterns | Convention profile (camelCase vs snake_case, linter config, etc.) |
| Testing patterns | Assess test structure, coverage indicators, test naming conventions | `{pattern: "unit+integration", coverage_tool: "", naming: ""}` |
| Deployment model | Detect Dockerfiles, CI configs, IaC files (Terraform, Pulumi, CDK) | Deployment profile with detected tooling |
| Known traps | Cross-reference Rings churn + Taproot complexity → fragile areas | Trap list: `[{file, reason, recommendation}]` |
| Magic Numbers | Scan for density of hardcoded numeric literals (screen coordinates like `1920`, `1080`, pixel positions, port numbers, timeout values). High density of magic numbers indicates structural brittleness. Flag files with >10 hardcoded numeric literals as candidates for Vacuole generation. | List of brittle files with high magic number density |
| Governance config | Recommend which rules to activate, review protocol level | `{rules: [], default_protocol: "", risk_areas: []}` |
| Context Pre-Seeding | Auto-generate context header for future subagent prompts (approx. ~200 tokens; measured via `token_census.py`) | Ready-to-use context block |

### Lichen Prompt Template

```
<!-- CONTEXT: Genesis Lichen -->
You are a governance advisor. Your job is to synthesize codebase intelligence into
actionable governance configuration. You are READ-ONLY.

Repository: [REPO_PATH]
Project name: [PROJECT_NAME]

Prior stage outputs:
[CARTOGRAPHY SUMMARY — tech stack, structure, entry points, test framework]
[CHRONICLE SUMMARY — commit activity, churn heatmap, high-risk files]
[CODEX SUMMARY — API surface, data models, config pattern, integrations]

Deliver:

### Coding Conventions
- Naming: [camelCase / snake_case / PascalCase / mixed]
- Formatting: [prettier / black / gofmt / none detected]
- Linter: [eslint / pylint / clippy / none]
- Error handling: [try-catch / Result type / error codes / mixed]

### Testing Patterns
- Strategy: [unit / integration / e2e / mixed]
- Framework: [from Canopy]
- Coverage tool: [if detected]
- Test naming: [describe/it / test_ prefix / @Test / etc.]
- Approximate test count: [count test files × avg tests per file]

### Deployment Model
- Containerized: [yes/no] — [Dockerfile location]
- CI/CD: [GitHub Actions / GitLab CI / Jenkins / etc.] — [config location]
- IaC: [Terraform / Pulumi / CDK / none] — [directory]
- Environments: [detected from config/env files]

### Known Traps & Gotchas
[Cross-reference Rings churn heatmap with Taproot architecture findings]
- **Magic Numbers & Hardcoded Coordinates**: Scan for density of hardcoded numeric literals (screen coordinates like `1920`, `1080`, pixel positions, port numbers, timeout values). High density of magic numbers indicates structural brittleness. Flag files with >10 hardcoded numeric literals as candidates for Vacuole generation.

| File | Signal | Trap | Recommendation |
|:-----|:-------|:-----|:---------------|
| [path] | [high churn + complex] | [description] | [mitigation] |

### Recommended Governance Configuration
- Default review protocol: [Gale / Trident / Maelstrom] — [rationale]
- Rules to activate: [list applicable rule files]
- High-risk areas requiring Maelstrom+: [list paths/patterns]
- Suggested Spores lenses: [list 3-4 recommended lenses]

### Auto-Generated Context Pre-Seeding Block
```
<!-- CONTEXT: [PROJECT_NAME] -->
[PROJECT]: [Name] — [1-sentence core purpose]
[STACK]: [Language] | [Key libs] | Test: `[test_command]`
[LAYOUT]:
  - `[dir]/`: [3-word role]
[CONSTRAINTS]:
  - [Critical invariant or known trap from Lichen analysis]
[OUTPUT]: Max 5 bullets per section. Cite file:line.
<!-- END CONTEXT -->
```

This block is nominally ~200 tokens (approximate target; ground-truth token count is measured via `enzymes/token_census.py`) and is used verbatim in all future subagent prompts.
<!-- END CONTEXT -->
```
---

## Multi-Repo Mode

When provided multiple repository paths, Genesis runs Stages 1–3 independently for each repo, then runs a single Lichen pass that synthesizes across all repositories.

```
genesis([repo_a, repo_b, repo_c])

  Stage 1: Canopy(repo_a), Canopy(repo_b), Canopy(repo_c)  ← parallel
  Stage 2: Rings(repo_a), Rings(repo_b), Rings(repo_c)        ← parallel
  Stage 3: Taproot(repo_a), Taproot(repo_b), Taproot(repo_c)                    ← parallel
  Stage 4: Lichen(all_outputs)                                            ← single synthesis
```

The Lichen stage additionally identifies:
- **Shared contracts** between repos (proto files, OpenAPI specs, shared packages)
- **Deployment coupling** (do repos deploy independently or together?)
- **Cross-repo churn correlation** (do changes in repo_a frequently accompany changes in repo_b?)

---

## Output Format

The Genesis Report is a structured markdown artifact persisted as `genesis-report-[project-name].md`:

```markdown
# Genesis Report — [Project Name]
> Generated: [timestamp] | Stages: [list] | Repos: [count]

## 🗺️ Canopy
[Stage 1 output — tech stack, directory tree, dependencies, entry points, testing]

### Dev Environment
[Sanitized environment aggregates: shell, OS/arch, build tools, container status, IDE, Python/venv, Git status, package managers. Note: Probed by parent orchestrator; research subagents have read-only tools only. Contains zero raw paths, usernames, or env vars.]

## 📜 Rings
[Stage 2 output — branch topology, commit activity, churn heatmap, high-risk files]

## 📖 Taproot
[Stage 3 output — API surface, data models, config patterns, integrations, boundaries]

## 🧭 Lichen
[Stage 4 output — conventions, testing patterns, deployment model, traps, governance config]

## Auto-Generated Context Block
[Context pre-seeding block (~200 tokens approx, measured via `token_census.py`) ready for copy-paste into subagent prompts]

---
## Diff from Previous Report
[If a prior genesis-report exists, show what changed since last run]
```

---

## Cache & Diff Behavior

| Scenario | Behavior |
|:---------|:---------|
| First run | Full 4-stage scan, produces `genesis-report-[project].md` |
| Subsequent run (same repo) | Re-runs selected stages, diffs against cached report, highlights changes |
| Subsequent run (new files detected) | Re-runs Canopy + impacted stages, appends diff section |
| Force full refresh | User says "genesis --fresh" or "re-scan everything" — ignores cache |

The diff section uses standard diff formatting:
```diff
## 🗺️ Canopy
- Dependencies: 42 direct, 18 dev
+ Dependencies: 45 direct, 19 dev
  [+3 new: @aws-sdk/client-s3, zod, vitest]
```

---

## Relationship to Existing System

Genesis output feeds directly into multiple downstream skills and prongs:

```
  Genesis                         Downstream Consumer
  ┌─────────────────┐
  │ 🗺️ Canopy  │ ──────────► Context Pre-Seeding (all subagent prompts)
  │                  │ ──────────► Session Preflight (env verification)
  ├─────────────────┤
  │ 📜 Rings    │ ──────────► Spores (priority ranking by churn)
  │                  │ ──────────► Post-Mortem (historical context)
  ├─────────────────┤
  │ 📖 Taproot        │ ──────────► Mycelium (blast-radius pre-computation)
  │                  │ ──────────► Security Audit (attack surface map)
  ├─────────────────┤
  │ 🧭 Lichen      │ ──────────► Staff Review (default protocol selection)
  │                  │ ──────────► Governance Auditor (rule activation)
  └─────────────────┘
```

| Genesis Stage | Feeds | How |
|:-------------|:------|:----|
| Canopy | Context Pre-Seeding | Auto-generated `<!-- CONTEXT -->` block used in all subagent prompts |
| Canopy | Session Preflight | Tech stack, test runner, and dev environment probe inform environment verification |
| Rings | Spores | Churn heatmap prioritizes which files scouts examine first |
| Rings | Post-Mortem | Historical contributor and release context |
| Taproot | Mycelium | Pre-computed dependency graph accelerates blast-radius analysis |
| Taproot | Security Audit | API surface and external integrations define the attack surface |
| Lichen | Staff Review | Recommended protocol level becomes the session default |
| Lichen | Governance Auditor | Recommended rules are activated for the project |

---

## Anti-Patterns

- **Don't modify the repository** — Genesis is strictly read-only reconnaissance. If a stage subagent proposes a fix, discard it. Genesis observes; other skills act.
- **Don't skip Canopy** — All other stages benefit from structure context. Running Rings or Taproot without Canopy produces lower-quality output.
- **Don't run Lichen without at least one prior stage** — Lichen synthesizes; it needs raw data to synthesize. Running Lichen on an empty input produces generic boilerplate.
- **Don't dispatch >2 subagents per stage** — Genesis stages are sequential and focused. Unlike Spores (which benefits from orthogonal lenses), Genesis stages have a single objective each.
- **Don't cache across major version changes** — If the repo undergoes a major refactor (new framework, language migration), force a fresh Genesis run. Diffing against a stale baseline produces misleading deltas.
- **Don't substitute Genesis for a review** — Genesis maps the terrain; it does not evaluate quality. Use Staff Review, Spores, or Adaptive Reviewer to assess code quality.
- **Don't let Lichen subagents apply governance config** — Lichen *recommends* configuration. The orchestrator presents recommendations to the user, who decides what to activate.

---

## Model Selection

| Role | Model | Rationale |
|:-----|:------|:----------|
| Canopy scanner | `flash` | File-system traversal, manifest parsing, structured output |
| Rings analyst | `flash` | Git command execution, quantitative analysis, heatmap generation |
| Taproot analyst | `flash` | Pattern matching on code (routes, schemas, configs), structured tables |
| Lichen advisor | `flash` | Synthesis of prior outputs, governance recommendation, template generation |
| Report synthesizer | orchestrator (self) | Cross-stage reconciliation, diff generation, artifact persistence |

---

## When to Use

- **"What is this codebase?"** — Full Genesis (all 4 stages)
- **"Onboard me"** / **"I'm new to this repo"** — Full Genesis + present Context Pre-Seeding block
- **"Map this repo"** / **"Show me the structure"** — Canopy only
- **"Where are the hot spots?"** — Canopy + Rings
- **"How is this system architected?"** — Canopy + Taproot
- **"Set up governance for this project"** — Full Genesis (Lichen needs all prior stages for good recommendations)
- **"What changed since last scan?"** — Re-run Genesis with cache diff

## When NOT to Use

- **Code review** — Use Staff Review or Adaptive Reviewer. Genesis maps; it does not judge.
- **Known defect** — Use Breeze. The bug is already located; no reconnaissance needed.
- **Active debugging** — Use Incident Debug. Genesis is pre-engagement reconnaissance, not live triage.
- **Single-file exploration** — Just read the file. Genesis is for repository-scale mapping.
- **CI/CD pipeline** — Genesis is interactive and conversational. For automated quality gates, use Bedrock as a CI check.

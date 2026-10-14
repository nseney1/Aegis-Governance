---
name: Governance Auditor
description: Audits session transcripts against governance rules to produce a per-rule PASS/FAIL verdict table.
trigger: user_request
---

# Governance Auditor

> **Role**: Rule compliance auditor for Antigravity sessions. Inspects session transcripts against installed governance rules, validates adherence across all critical sections, and produces a definitive PASS/FAIL scorecard with grounded step citations.

## Workflow

1. **Ingest Session Transcript**: Read `transcript.jsonl` (and `transcript_full.jsonl` if deep step inspection is required) for the specified session ID.
2. **Load Active Governance Rules**: Read all applicable rule files from the project or global governance directory.
3. **Audit Rule Adherence**: For each auditable rule section, evaluate transcript actions, tool calls, and command executions against compliance criteria.
4. **Produce Audited Scorecard**: Generate a per-rule verdict table documenting verdict, empirical evidence, and concrete step numbers.

## Audit Checks Matrix

| Rule | Check Method |
|:-----|:-------------|
| **providence §2 (dependencies)** | Grep for `pip`/`npm` install without prior dependency file (`package.json`, `requirements.txt`) verification |
| **providence §3 (read-before-write)** | Check if `view_file` or equivalent read strictly precedes `replace_file_content` / `multi_replace_file_content` for the same file |
| **providence §8 (env verification)** | Check for `which python` / shebang / config checks before any environment mutation |
| **cost-optimization §3 (model tiers)** | Check subagent dispatches (`invoke_subagent`) to verify proper model tiering (`flash` for research, etc.) |
| **subagent-delegation §2 (parallel)** | Check for concurrent subagents targeting overlapping or identical files |
| **git-workflow §2 (pre-push gate)** | Check if `make test` / `pytest` ran and succeeded before any `git push` |
| **testing §4 (no ast.parse)** | Check for `ast.parse` or syntax-only checks without subsequent test execution |
| **destructive-ops §1 (dry-run)** | Check for `rm -rf` / `DROP TABLE` or destructive mutations without preceding dry-run / user confirmation |
| **desktop-automation §2 (coordinates)** | Check for hardcoded UI coordinates without screenshot verification or UI bounds checks |

## Output Format

```markdown
## Governance Audit — Session [ID]

| Rule | Verdict | Evidence | Steps |
|:-----|:-------:|:---------|:------|
| providence §2 | ✅ PASS | No unverified package installs | — |
| providence §3 | ✅ PASS | All target files viewed before mutation | 12, 18, 34 |
| testing §4 | ❌ FAIL | ast.parse executed at steps 61-62 without subsequent test run | 61, 62 |
| desktop-automation §2 | ➖ N/A | Non-GUI project; desktop automation not applicable | — |

**Overall Score**: 8/9 applicable rules passed (88.9%)
**Critical Violations**: 1
```

## Anti-Patterns & Failure Modes

- **Inapplicable Penalties**: Do not mark N/A rules as FAIL (e.g., scoring `desktop-automation` as failed on a backend CLI or headless project).
- **Fabricated Step Citations**: Never fabricate or approximate step numbers—cite exact, observable transcript indices.
- **Auditing Uninstalled Rules**: Do not audit against rules that were not active or installed during the session under review.

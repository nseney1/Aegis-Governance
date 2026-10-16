"""MCP tool definitions, workspace binding and the rule inventory used by the handlers."""
from __future__ import annotations

from typing import Any, Optional

from aegis_core.fitness import for_rules
from aegis_core.rule_inventory import RuleInventoryError
from aegis_core.rules import load_rules
from aegis_core.sync import read_derived, stale_rules
from aegis_core.taxonomy import CANONICAL_RULE_TYPES, REVIEW_MODES, RULE_TYPES
from aegis_core.workspace.base import Workspace
from aegis_core.workspace import resolve_workspace

_STATUS_FAIL = "FAIL"
NOT_GOVERNED_MESSAGE = 'not an Aegis workspace: run "aegis init" in your repository'
# A client whose clientInfo names no known host: its ledger rows say "generic" and its
# scans get the generic slot table, never another vendor's (host-matrix §3.5).
DEFAULT_CLIENT_PLATFORM = "generic"
_VALID_OUTCOMES = ("success", "partial", "failure", "tp", "fp", "pass", "fail")


def _get_workspace(args: Optional[dict] = None) -> Workspace:
    """The workspace a handler acts on.

    Over stdio the server always injects its own workspace; an in-process caller may
    pass one. Without either, resolve strictly from AEGIS_WORKSPACE or the cwd.
    """
    raw = args.get("workspace") if args else None
    if isinstance(raw, Workspace):
        return raw
    return Workspace.confine(raw or resolve_workspace(strict_env=True))


def list_rules(workspace: Workspace, rule_type: Optional[str] = None) -> Any:
    """Every rule with its ledger fitness, plus what is stale or not a rule.

    Returns ``{"rules": [...], "stale_rules": [...], "ignored": [...]}``. A rule file
    that cannot be loaded stays in ``rules`` as a record with ``_error``; an unsafe
    rules tree (a symlink escape, an unreadable directory) fails the whole call.
    """
    try:
        ruleset = load_rules(workspace)
    except RuleInventoryError as exc:
        return {"status": _STATUS_FAIL, "error": str(exc)}
    selected = [r for r in ruleset.rules if not rule_type or r.type == rule_type]
    fits = for_rules(workspace, [r for r in selected if r.ok])
    rules = []
    for rule in selected:
        data = rule.as_dict()
        if rule.ok:
            data["fitness"] = fits[rule.id].as_dict()
        if rule.expired:
            data["_expired"] = True
        rules.append(data)
    stale = stale_rules(ruleset, read_derived(workspace))
    return {
        "rules": rules,
        "stale_rules": [s for s in stale if not rule_type or _type_of(s, ruleset) == rule_type],
        "ignored": [{"path": i.path, "reason": i.reason} for i in ruleset.ignored],
    }


def _type_of(stale: dict, ruleset: Any) -> Optional[str]:
    rule = ruleset.get(stale.get("id") or "")
    return rule.type if rule is not None else None


def build_rule_create_prompt(
    description: str,
    domain_hint: Optional[str] = None,
    rule_type: Optional[str] = None,
    args: Optional[dict] = None,
) -> str:
    workspace = _get_workspace(args)
    examples = [rule.raw.decode("utf-8-sig")[:500] for rule in load_rules(workspace).served]

    example_text = "\n---\n".join(examples[:3]) if examples else "No existing rules found."
    domain_context = f"\nDomain hint: {domain_hint}" if domain_hint else ""
    type_hint = f"\nPreferred rule type: {rule_type}" if rule_type else ""
    type_lines = "\n".join(
        f"- {name}: {spec.description}" for name, spec in RULE_TYPES.items()
    )

    return f"""You are a governance rule generator for Aegis.

Given a natural language description of a concern, generate a governance rule in markdown with YAML frontmatter.

Rule types:
{type_lines}

YAML fields required:
- type: (one of above)
- domain: (one of: efficiency, correctness, security, style, governance)
- enforcement: (gate for invariants, advisory for traps)
- hypothesis: (clear, testable statement)
- prediction: (what will happen if the hypothesis is violated)
- falsification: (how to prove this rule is no longer needed)
- target_paths: (list of file glob patterns this rule monitors)
- minimum_mode: ({' | '.join(REVIEW_MODES)})
- tags: (list of relevant tags)

Do not write a fitness block: fitness is computed from the outcome ledger.

Existing rules in this project for reference:
{example_text}
{domain_context}{type_hint}

User description: "{description}"

Generate ONLY the complete markdown rule file content. Start with --- for the YAML frontmatter. After the closing ---, include a brief description paragraph explaining the rule's purpose. Do not include any other text."""


_VIEW_PROPERTY = {
    "type": "string",
    "enum": ["full", "summary", "ids"],
    "description": "Optional response projection: full (default), summary or ids.",
}
_RULE_TYPE_PROPERTY = {"type": "string", "enum": list(CANONICAL_RULE_TYPES)}

TOOL_DEFINITIONS = [
    {
        "name": "aegis_scan",
        "description": (
            "Call before editing files: returns the governance rules that apply to them, "
            "ranked by ledger fitness and clamped to the JIT token budget. Mandatory rules "
            "(gates, invariants) take at most two slots; the others are listed in "
            "omitted_mandatory. Gates and invariants are served from the reviewed base commit "
            "(rules_base); branch-local edits to them never bind and are listed in unreviewed_rules. "
            "stale_rules lists rules edited since the last aegis sync. "
            "If any rule file cannot be loaded the scan fails (status FAIL) and names it."
        ),
        "annotations": {
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
            "title": "Scan JIT Rules",
        },
        "inputSchema": {
            "type": "object",
            "properties": {
                "files": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Workspace-relative files you are about to edit. Defaults to the git diff.",
                },
                "view": _VIEW_PROPERTY,
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "aegis_report_outcome",
        "description": (
            "Report whether the rules you were shown helped. Each report is an advisory "
            "self-report row in the outcome ledger; it never promotes a rule by itself."
        ),
        "annotations": {
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
            "title": "Report Outcome",
        },
        "inputSchema": {
            "type": "object",
            "properties": {
                "outcome": {"type": "string", "enum": list(_VALID_OUTCOMES), "description": "Verification outcome."},
                "idempotency_key": {
                    "type": "string",
                    "maxLength": 256,
                    "description": "Unique key for this report. Retrying with the same key never records twice.",
                },
                "rules_used": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 1,
                    "description": "Names of the rules this outcome is about, as aegis_scan returned them.",
                },
                "tests_passed": {"type": "boolean"},
                "rework_count": {"type": "integer", "default": 0},
                "notes": {"type": "string", "maxLength": 4096},
                "files": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Optional: the files this change edited (workspace-relative). They measure "
                        "scan-before-edit compliance (aegis status --compliance); they credit no rule."
                    ),
                },
                "view": _VIEW_PROPERTY,
            },
            "required": ["outcome", "rules_used", "idempotency_key"],
            "additionalProperties": False,
        },
    },
    {
        "name": "aegis_create_rule",
        "description": (
            "Turn a natural language concern into a prompt that drafts a governance rule. "
            "It writes nothing: save the drafted rule under .aegis/rules/ yourself."
        ),
        "annotations": {
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
            "title": "Create Rule",
        },
        "inputSchema": {
            "type": "object",
            "properties": {
                "description": {"type": "string", "description": "The concern, in natural language."},
                "rule_type": dict(_RULE_TYPE_PROPERTY, description="Optional rule type hint."),
                "domain": {"type": "string", "description": "Optional domain hint."},
            },
            "required": ["description"],
            "additionalProperties": False,
        },
    },
    {
        "name": "aegis_list_rules",
        "description": (
            "List the governance rules as {rules, stale_rules, ignored}: every rule with its "
            "type, hypothesis and ledger fitness (a file that cannot be loaded is listed with "
            "_error), the rules edited since the last aegis sync, and markdown under "
            ".aegis/rules that is not a rule."
        ),
        "annotations": {
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
            "title": "List Rules",
        },
        "inputSchema": {
            "type": "object",
            "properties": {
                "rule_type": dict(_RULE_TYPE_PROPERTY, description="Optional rule type filter."),
                "view": _VIEW_PROPERTY,
            },
            "additionalProperties": False,
        },
    },
]

TOOL_ARGUMENTS = {
    tool["name"]: frozenset(tool["inputSchema"].get("properties", {})) for tool in TOOL_DEFINITIONS
}

"""MCP tool definitions, workspace binding and the rule inventory used by the handlers."""
from __future__ import annotations

import os
from typing import Any, Optional

from aegis_core.evidence import aggregate_signals
from aegis_core.rule_inventory import RuleInventoryError, inventory_rules
from aegis_core.scoring import compute_cell_fitness
from aegis_core.taxonomy import CANONICAL_RULE_TYPES, REVIEW_MODES
from aegis_core.workspace import Workspace, resolve_workspace
from aegis_core.yaml import parse_frontmatter
from aegis_mcp.jit_engine import warn

_STATUS_FAIL = "FAIL"
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


def _rule_diagnostic(relative_path: str, message: str) -> dict:
    return {
        "_name": os.path.splitext(os.path.basename(relative_path))[0],
        "_path": relative_path,
        "_error": message,
    }


def _matches_rule_type_filter(rel: str, rule_type: Optional[str] = None) -> bool:
    if not rule_type:
        return True
    parent_name = os.path.basename(os.path.dirname(rel))
    return (
        parent_name in (rule_type, f"{rule_type}s")
        or f"/{rule_type}/" in rel
        or f"/{rule_type}s/" in rel
    )


def _ledger_fitness(counts: dict, rule: dict) -> dict:
    """A rule's fitness from its outcome-ledger rows (ADR 0005 C7: ledger, not frontmatter)."""
    entry = next(
        (counts[key] for key in (rule.get("_name"), rule.get("id")) if isinstance(key, str) and key in counts),
        {},
    )
    triggers, tp, fp = entry.get("triggers", 0), entry.get("tp", 0), entry.get("fp", 0)
    # A tp/fp row is an observation even when no trigger row was paired with it.
    observations = max(triggers, tp + fp)
    score = compute_cell_fitness({
        "fitness": {"triggers": observations, "true_positives": tp, "false_positives": fp},
        "impact_weight": rule.get("impact_weight", 1.0),
    })
    return {"triggers": triggers, "tp": tp, "fp": fp, "score": score}


def list_rules(workspace: Workspace, rule_type: Optional[str] = None) -> Any:
    """List rules from one byte snapshot of the rules directory, with ledger fitness.

    A file that cannot be read or parsed becomes an ``_error`` record instead of
    disappearing, and an inventory failure (a symlink escape, an unreadable
    directory) fails the whole call. Unreadable ledger rows are skipped.
    """
    try:
        inventory = inventory_rules(workspace)
    except RuleInventoryError as exc:
        return {"status": _STATUS_FAIL, "error": str(exc)}
    counts = aggregate_signals(str(workspace.evidence_dir)).counts

    rules = []
    for entry in inventory.entries:
        rel = entry.relative_path
        if os.path.basename(rel) == "README.md":
            continue

        path_matches = _matches_rule_type_filter(rel, rule_type)

        try:
            content = entry.content.decode("utf-8")
        except UnicodeDecodeError as exc:
            if not path_matches:
                continue
            message = f"invalid UTF-8: {exc}"
            warn(f"skipped rule {rel}: {message}")
            rules.append(_rule_diagnostic(rel, message))
            continue

        fm = parse_frontmatter(content)
        if fm is None:
            if not path_matches:
                continue
            message = "malformed YAML frontmatter"
            warn(f"skipped rule {rel}: {message}")
            rules.append(_rule_diagnostic(rel, message))
            continue
        if not fm:
            if not path_matches:
                continue
            message = "no frontmatter metadata"
            warn(f"skipped rule {rel}: {message}")
            rules.append(_rule_diagnostic(rel, message))
            continue

        if rule_type and not (fm.get("type") == rule_type or path_matches):
            continue

        fm["_name"] = os.path.splitext(os.path.basename(rel))[0]
        fm["_path"] = rel
        fm["fitness"] = _ledger_fitness(counts, fm)
        rules.append(fm)
    return rules


_RULE_TYPE_GUIDE = {
    "invariant": "Must ALWAYS hold (hard safety gate).",
    "trap": "A known failure mode to watch for.",
    "gate": "A check that blocks a change until it passes.",
    "boundary": "A sensitive area that needs elevated review.",
    "persona": "An idiomatic pattern to follow.",
    "contract": "An API or data-shape agreement across services.",
}


def build_rule_create_prompt(
    description: str,
    domain_hint: Optional[str] = None,
    rule_type: Optional[str] = None,
    args: Optional[dict] = None,
) -> str:
    workspace = _get_workspace(args)
    examples = []
    for entry in inventory_rules(workspace).entries:
        rel = entry.relative_path
        if os.path.basename(rel) == "README.md":
            continue
        try:
            content = entry.content.decode("utf-8")
        except UnicodeDecodeError as exc:
            warn(f"skipped rule example {rel}: invalid UTF-8: {exc}")
            continue
        if content.startswith("---"):
            examples.append(content[:500])

    example_text = "\n---\n".join(examples[:3]) if examples else "No existing rules found."
    domain_context = f"\nDomain hint: {domain_hint}" if domain_hint else ""
    type_hint = f"\nPreferred rule type: {rule_type}" if rule_type else ""
    type_lines = "\n".join(
        f"- {name}: {_RULE_TYPE_GUIDE.get(name, '')}".rstrip() for name in CANONICAL_RULE_TYPES
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
            "ranked and clamped to the JIT token budget."
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
                "notes": {"type": "string"},
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
        "description": "List the governance rules with their type, hypothesis and ledger fitness.",
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

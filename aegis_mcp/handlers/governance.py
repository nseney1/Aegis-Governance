"""aegis_create_rule and aegis_list_rules."""
from __future__ import annotations

from aegis_core.taxonomy import RULE_TYPES
from aegis_mcp.registry import _STATUS_FAIL, _get_workspace, build_rule_create_prompt, list_rules


def handle_create_rule(args: dict) -> dict:
    description = args.get("description")
    if not isinstance(description, str) or not description.strip():
        return {"error": "'description' must be a non-empty string.", "status": _STATUS_FAIL}
    try:
        prompt = build_rule_create_prompt(
            description=description,
            domain_hint=args.get("domain"),
            rule_type=args.get("rule_type"),
            args=args,
        )
    except (ValueError, RuntimeError) as exc:
        return {"error": str(exc), "status": _STATUS_FAIL}
    return {
        "prompt": prompt,
        "instruction": (
            "Process this prompt and return the rule markdown. Then use a file-writing tool "
            "to save it as .aegis/rules/<type directory>/<id>.md, where the type directory is "
            + ", ".join(f"{spec.directory}/ ({name})" for name, spec in RULE_TYPES.items())
            + "."
        ),
    }


def handle_list_rules(args: dict):
    try:
        workspace = _get_workspace(args)
    except ValueError as exc:
        return {"status": _STATUS_FAIL, "error": str(exc)}
    return list_rules(workspace, rule_type=args.get("rule_type"))

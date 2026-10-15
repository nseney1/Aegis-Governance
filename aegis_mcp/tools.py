"""Tool dispatch: argument check, one handler per tool, opt-in response projection."""
from __future__ import annotations

from typing import Any

from aegis_mcp.handlers.core import handle_scan
from aegis_mcp.handlers.governance import handle_create_rule, handle_list_rules
from aegis_mcp.handlers.telemetry import handle_report_outcome
from aegis_mcp.projection import project_response
from aegis_mcp.registry import TOOL_ARGUMENTS, TOOL_DEFINITIONS

_TOOL_HANDLERS = {
    "aegis_scan": handle_scan,
    "aegis_report_outcome": handle_report_outcome,
    "aegis_create_rule": handle_create_rule,
    "aegis_list_rules": handle_list_rules,
}

# Set by the server (or passed by an in-process caller), never part of a tool schema.
_SERVER_INJECTED = frozenset({"workspace", "_host", "_session"})


def is_known_tool(name: Any) -> bool:
    return isinstance(name, str) and name in _TOOL_HANDLERS


def execute_tool(name: str, args: dict) -> Any:
    """Check the argument names, dispatch, and project the response if a view is asked for."""
    handler = _TOOL_HANDLERS.get(name)
    if handler is None:
        raise ValueError(f"Unknown tool: {name}")
    unknown = sorted(k for k in args if k not in TOOL_ARGUMENTS[name] and k not in _SERVER_INJECTED)
    if unknown:
        return {"status": "FAIL", "error": f"Unknown argument(s) for {name}: {unknown}"}

    result = handler(args)
    view = args.get("view")
    if view:
        return project_response(result, view=view)
    return result


__all__ = ["TOOL_DEFINITIONS", "execute_tool", "is_known_tool"]

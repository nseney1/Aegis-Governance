"""Lean Gateway Router: Normalization, dispatch, opt-in response projection, and re-exports (<150 LOC)."""
from __future__ import annotations

import os
from typing import Any, Dict, Optional, Tuple

from aegis_mcp.handlers import (
    _handle_audit_performance,
    _handle_audit_security,
    _handle_capture_insight,
    _handle_checkpoint,
    _handle_coverage,
    _handle_create_cell,
    _handle_fitness,
    _handle_generate_manifest,
    _handle_grade,
    _handle_list_cells,
    _handle_poll_verification,
    _handle_propose_change,
    _handle_report_outcome,
    _handle_request_receipt,
    _handle_scan,
    _handle_soma_handoff,
    _handle_verify_changes,
)
from aegis_mcp.projection import project_response
from aegis_mcp.registry import (
    _HAS_SDK,
    _STATUS_FAIL,
    _STATUS_PASS,
    _VALID_OUTCOMES,
    DISABLED_BY_DEFAULT_TOOLS,
    TOOL_DEFINITIONS,
    _cell_diagnostic,
    _classify_propose_result,
    _get_workspace,
    _list_cells_stdlib,
    _matches_cell_type_filter,
    build_cell_create_prompt,
    get_governance,
    inventory_cells,
    normalize_tool_call,
    resolve_workspace,
)
from aegis_mcp.security import (
    Workspace,
    confine_path,
    confine_workspace,
    validate_rule_names,
)

yaml = None  # Backward-compatible sentinel: zero-dependency runtime

_TOOL_HANDLERS = {
    "aegis_create_cell": _handle_create_cell,
    "aegis_create_rule": _handle_create_cell,
    "aegis_list_cells": _handle_list_cells,
    "aegis_list_rules": _handle_list_cells,
    "aegis_propose_change": _handle_propose_change,
    "aegis_audit_security": _handle_audit_security,
    "aegis_audit_performance": _handle_audit_performance,
    "aegis_verify_changes": _handle_verify_changes,
    "aegis_poll_verification": _handle_poll_verification,
    "aegis_checkpoint": _handle_checkpoint,
    "aegis_scan": _handle_scan,
    "aegis_report_outcome": _handle_report_outcome,
    "aegis_capture_insight": _handle_capture_insight,
    "aegis_generate_manifest": _handle_generate_manifest,
    "aegis_grade": _handle_grade,
    "aegis_coverage": _handle_coverage,
    "aegis_fitness": _handle_fitness,
    "aegis_rule_fitness": _handle_fitness,
    "aegis_request_receipt": _handle_request_receipt,
    "aegis_handoff": _handle_soma_handoff,
}


def execute_tool(name: str, args: dict):
    """Normalize porcelain aliases, dispatch to execution plane, and project response."""
    canonical_name, normalized_args = normalize_tool_call(name, args)
    gov = get_governance(normalized_args)
    handler = _TOOL_HANDLERS.get(canonical_name)
    if not handler:
        raise ValueError(f"Unknown tool: {canonical_name}")

    raw_res = handler(normalized_args, gov)
    view = normalized_args.get("view")
    fields = normalized_args.get("fields")
    if view or fields:
        return project_response(raw_res, view=view, fields=fields)
    return raw_res


__all__ = [
    "TOOL_DEFINITIONS",
    "execute_tool",
    "normalize_tool_call",
    "get_governance",
    "resolve_workspace",
    "confine_workspace",
    "_get_workspace",
    "build_cell_create_prompt",
    "_handle_create_cell",
    "_handle_list_cells",
    "_handle_propose_change",
    "_handle_generate_manifest",
    "_handle_soma_handoff",
    "_handle_verify_changes",
    "_handle_poll_verification",
    "_handle_checkpoint",
    "_handle_request_receipt",
    "_handle_audit_security",
    "_handle_audit_performance",
    "_handle_scan",
    "_handle_report_outcome",
    "_handle_capture_insight",
    "_handle_grade",
    "_handle_coverage",
    "_handle_fitness",
    "_TOOL_HANDLERS",
    "_STATUS_PASS",
    "_STATUS_FAIL",
    "_VALID_OUTCOMES",
    "DISABLED_BY_DEFAULT_TOOLS",
]

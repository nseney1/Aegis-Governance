"""Execution plane tool handlers for Soma MCP gateway."""
from __future__ import annotations

from aegis_mcp.handlers.audit import (
    _handle_audit_performance,
    _handle_audit_security,
    _handle_scan,
)
from aegis_mcp.handlers.governance import (
    _handle_create_cell,
    _handle_create_rule,
    _handle_generate_manifest,
    _handle_list_cells,
    _handle_list_rules,
    _handle_propose_change,
    _handle_soma_handoff,
)
from aegis_mcp.handlers.telemetry import (
    _handle_capture_insight,
    _handle_coverage,
    _handle_fitness,
    _handle_grade,
    _handle_report_outcome,
    _handle_rule_fitness,
)
from aegis_mcp.handlers.verification import (
    _handle_checkpoint,
    _handle_poll_verification,
    _handle_request_receipt,
    _handle_verify_changes,
)

__all__ = [
    "_handle_create_cell",
    "_handle_create_rule",
    "_handle_list_cells",
    "_handle_list_rules",
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
    "_handle_rule_fitness",
]


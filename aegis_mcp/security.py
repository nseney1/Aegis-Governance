"""Shared security utilities for the Soma MCP server.

Delegates path confinement, workspace validation, and cell name verification
to the canonical single-authority implementation in aegis_core.workspace.
"""
from __future__ import annotations

from aegis_core.workspace import (
    _WINDOWS_DEVICE_NAMES,
    Workspace,
    confine_path,
    confine_workspace,
    validate_rule_names,
)

__all__ = [
    "_WINDOWS_DEVICE_NAMES",
    "Workspace",
    "confine_path",
    "confine_workspace",
    "validate_rule_names",
]

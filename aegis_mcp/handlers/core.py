"""Core MCP execution handlers: thin delegation to canonical audit scan handler."""
from __future__ import annotations

from aegis_mcp.handlers.audit import _handle_scan, handle_scan

__all__ = [
    "handle_scan",
    "_handle_scan",
]

"""Core MCP execution handlers: handle_scan with pre-edit planned_symbols support."""
from __future__ import annotations

from typing import Any, List, Optional

from aegis_mcp.jit_engine import express as jit_express
from aegis_mcp.registry import _STATUS_FAIL, _STATUS_PASS, _get_workspace

__all__ = [
    "handle_scan",
    "_handle_scan",
]


def handle_scan(
    args: dict,
    gov: Any = None,
    planned_symbols: Optional[List[str]] = None,
) -> dict:
    """Execute JIT rule scan for target files and optional pre-edit planned_symbols."""
    try:
        workspace = _get_workspace(args)
    except ValueError as exc:
        return {"error": str(exc), "status": _STATUS_FAIL}

    files = args.get("files", None) if isinstance(args, dict) else None
    if files is not None:
        if not isinstance(files, (list, tuple)) or not all(isinstance(f, str) for f in files):
            return {"error": "'files' must be a list of file paths", "status": _STATUS_FAIL}
        try:
            files = [str(workspace.confine_path(f)[1]) for f in files]
        except ValueError as exc:
            return {"error": str(exc), "status": _STATUS_FAIL}

    symbols = planned_symbols
    if symbols is None and isinstance(args, dict):
        raw_symbols = args.get("planned_symbols")
        if raw_symbols is not None:
            if not isinstance(raw_symbols, (list, tuple)) or not all(isinstance(s, str) for s in raw_symbols):
                return {"error": "'planned_symbols' must be a list of strings", "status": _STATUS_FAIL}
            symbols = list(raw_symbols)

    return jit_express(workspace, changed_files=files, planned_symbols=symbols)


_handle_scan = handle_scan

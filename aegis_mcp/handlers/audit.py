"""Audit execution handlers: security audit, performance audit, and JIT scan."""
from __future__ import annotations

import os
import sys
from typing import Any, Dict, List, Optional

from aegis_mcp.jit_engine import express as jit_express
from aegis_mcp.registry import _STATUS_FAIL, _STATUS_PASS, _get_workspace

__all__ = [
    "_handle_audit_security",
    "_handle_audit_performance",
    "handle_scan",
    "_handle_scan",
]


def _handle_audit_security(args: dict, gov) -> dict:
    content = args.get("proposed_content") or ""
    file_path = args.get("file_path") or ""
    if file_path:
        try:
            workspace = _get_workspace(args)
            _, rel_path = workspace.confine_path(file_path)
            file_path = rel_path
        except ValueError as exc:
            return {"error": str(exc), "status": _STATUS_FAIL}
    flags = []
    if "password=" in content.lower() or "secret=" in content.lower():
        flags.append(f"- Hardcoded secret or password detected in {file_path}.")
    if "eval(" in content:
        flags.append(f"- eval() detected in {file_path}. Potential injection vector.")
    if file_path:
        ext = os.path.splitext(file_path)[1].lower()
        if ext in (".html", ".htm", ".js", ".jsx", ".ts", ".tsx"):
            if "innerHTML" in content or "document.write" in content:
                flags.append(f"- Potential XSS vector in {file_path}: innerHTML/document.write usage.")
        if ext == ".sql" or ("execute(" in content and "%s" not in content and "?" not in content):
            if 'f"' in content or "f'" in content or "% " in content:
                flags.append(f"- Potential SQL injection in {file_path}: string formatting in query.")

    if flags:
        return {
            "status": "FAIL",
            "feedback": "\n".join(flags),
            "file_path": file_path,
            "instruction": "Fix these issues and resubmit.",
        }
    return {
        "status": "PASS",
        "feedback": f"Security Audit passed for {file_path or 'input'}. No OWASP flaws or exposed secrets detected.",
        "file_path": file_path,
    }


def _handle_audit_performance(args: dict, gov) -> dict:
    content = args.get("proposed_content") or ""
    file_path = args.get("file_path") or ""
    if file_path:
        try:
            workspace = _get_workspace(args)
            _, rel_path = workspace.confine_path(file_path)
            file_path = rel_path
        except ValueError as exc:
            return {"error": str(exc), "status": _STATUS_FAIL}
    flags = []
    if content.count("for ") > 2 and "in " in content:
        flags.append(f"- Potential O(N^2) or deeply nested loop detected in {file_path}.")
    if ".query(" in content and "SELECT *" in content:
        flags.append(f"- Inefficient DB query (SELECT *) detected in {file_path}. Select only needed columns.")
    if file_path:
        ext = os.path.splitext(file_path)[1].lower()
        if ext == ".py":
            if "import *" in content:
                flags.append(f"- Wildcard import in {file_path} may slow startup and increase memory.")

    if flags:
        return {
            "status": "FAIL",
            "feedback": "\n".join(flags),
            "file_path": file_path,
            "instruction": "Optimize the code and resubmit.",
        }
    return {
        "status": "PASS",
        "feedback": f"Performance Audit passed for {file_path or 'input'}. No obvious bottlenecks detected.",
        "file_path": file_path,
    }


def _interpolate_scan_slots(res: dict, platform: str, workspace: Any) -> dict:
    """Resolve ${SLOT.*} placeholders in JIT scan results for the active MCP client platform."""
    try:
        from aegis_core.skills.slots import SlotRegistry
        if hasattr(SlotRegistry, "for_platform"):
            reg = SlotRegistry.for_platform(platform, workspace=str(workspace))
        else:
            reg = SlotRegistry.load(str(workspace))
    except Exception:
        return res

    for top_key in ("context", "guidance"):
        val = res.get(top_key)
        if isinstance(val, str) and "${SLOT." in val:
            res[top_key] = reg.resolve(val, strict=False)

    seen_ids = set()
    for list_key in ("relevant_rules", "relevant_cells", "genome_guidance", "target_constraints", "wall_warnings", "invariant_warnings"):
        items = res.get(list_key)
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict) or id(item) in seen_ids:
                continue
            seen_ids.add(id(item))
            for field in ("content", "body", "guidance", "summary", "hypothesis", "prediction"):
                val = item.get(field)
                if isinstance(val, str) and "${SLOT." in val:
                    item[field] = reg.resolve(val, strict=False)
    return res


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

    res = jit_express(workspace, changed_files=files, planned_symbols=symbols)
    if not isinstance(res, dict):
        return res

    client_platform = None
    if isinstance(args, dict):
        client_platform = args.get("_client_platform") or args.get("platform")
    if not client_platform:
        server_mod = sys.modules.get("aegis_mcp.server")
        client_platform = getattr(server_mod, "_client_platform", "gemini") if server_mod else "gemini"

    return _interpolate_scan_slots(res, str(client_platform), workspace)


_handle_scan = handle_scan

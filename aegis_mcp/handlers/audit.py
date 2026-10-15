"""Audit execution handlers: security audit, performance audit, and JIT scan."""
from __future__ import annotations

import os
from typing import Any, Dict

from aegis_mcp.jit_engine import express as jit_express
from aegis_mcp.registry import _STATUS_FAIL, _STATUS_PASS, _get_workspace

__all__ = [
    "_handle_audit_security",
    "_handle_audit_performance",
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


def _handle_scan(args: dict, gov) -> dict:
    try:
        workspace = _get_workspace(args)
    except ValueError as exc:
        return {"error": str(exc), "status": _STATUS_FAIL}
    files = args.get("files", None)
    if files is not None:
        if not isinstance(files, (list, tuple)) or not all(isinstance(f, str) for f in files):
            return {"error": "'files' must be a list of file paths", "status": _STATUS_FAIL}
        try:
            files = [str(workspace.confine_path(f)[1]) for f in files]
        except ValueError as exc:
            return {"error": str(exc), "status": _STATUS_FAIL}
    planned_symbols = args.get("planned_symbols", None)
    if planned_symbols is not None:
        if not isinstance(planned_symbols, (list, tuple)) or not all(isinstance(s, str) for s in planned_symbols):
            return {"error": "'planned_symbols' must be a list of strings", "status": _STATUS_FAIL}
        planned_symbols = list(planned_symbols)
    return jit_express(workspace, changed_files=files, planned_symbols=planned_symbols)

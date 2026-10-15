"""aegis-mcp stdio server: JSON-RPC framing, workspace binding and server-owned arguments."""
from __future__ import annotations

import contextlib
import json
import os
import sys
import threading
import time
import traceback
import uuid
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Optional

from aegis_core.taxonomy import MCP_DEFAULT_RATE_LIMITS
from aegis_core.workspace import Workspace

from .registry import DEFAULT_CLIENT_PLATFORM, TOOL_DEFINITIONS
from .tools import execute_tool, is_known_tool

NOT_GOVERNED_MESSAGE = 'not an Aegis workspace: run "aegis init" in your repository'

# Arguments only the server may set. A client value is dropped before dispatch, so the
# workspace, the host attribution and the session of a ledger row are never the caller's.
SERVER_OWNED_KEYS = frozenset({
    "workspace", "host", "session", "source", "platform",
    "_host", "_session", "_client_platform",
})

_canonical_workspace: Workspace | None = None
_client_platform: str = DEFAULT_CLIENT_PLATFORM
_session_id: Optional[str] = None
# Set by run_stdio_server when no governed workspace resolves; every tools/call
# then answers with it. In-process callers of handle_request leave it None.
_workspace_error: Optional[str] = None

_RATE_LIMITS = {
    "aegis_report_outcome": MCP_DEFAULT_RATE_LIMITS["MUTATION"],
}
_tool_call_times: Dict[str, list] = defaultdict(list)
_rate_limit_lock = threading.Lock()

# Messages that mean "the operation did not happen", regardless of the tool.
_ERROR_STATUSES = ("FAIL", "FAILED", "ERROR", "REJECTED", "BLOCKED", "ESCALATION_REQUIRED")
_ERROR_TEXT_PREFIXES = ("ERROR", "CRITICAL ERROR")


def strip_server_owned(args: Any) -> Dict[str, Any]:
    """Return a copy of client arguments without server-owned keys."""
    if not isinstance(args, dict):
        return {}
    return {k: v for k, v in args.items() if k not in SERVER_OWNED_KEYS}


def _check_rate_limit(tool_name: str) -> bool:
    """Return True if the call is within rate limits, False if exceeded."""
    if tool_name not in _RATE_LIMITS:
        return True
    max_calls, window_seconds = _RATE_LIMITS[tool_name]
    now = time.monotonic()
    with _rate_limit_lock:
        recent = [ts for ts in _tool_call_times[tool_name] if now - ts < window_seconds]
        if len(recent) >= max_calls:
            _tool_call_times[tool_name] = recent
            return False
        recent.append(now)
        _tool_call_times[tool_name] = recent
        return True


def _server_version() -> str:
    """Resolve the version from a single source of truth."""
    version_file = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "VERSION"
    )
    if os.path.isfile(version_file):
        try:
            with open(version_file, "r", encoding="utf-8") as fh:
                val = fh.read().strip()
                if val:
                    return val
        except OSError:
            pass
    try:
        from importlib.metadata import PackageNotFoundError, version
        for pkg_name in ("aegis-guardrails", "aegis-governance", "soma-governance"):
            try:
                return version(pkg_name)
            except PackageNotFoundError:
                continue
    except ImportError:
        pass
    return "unknown"


def send_response(response: Dict[str, Any]):
    # stdout is the JSON-RPC transport: only framed responses may be written here.
    print(json.dumps(response), flush=True)


def _is_error_text(value: Any) -> bool:
    return isinstance(value, str) and value.lstrip().upper().startswith(_ERROR_TEXT_PREFIXES)


def _is_error_result(result: Any) -> bool:
    """Decide whether a tool result represents a failure.

    A tool can signal failure three ways: an "error" key, an explicit failure
    "status", or a failure-prefixed message string.
    """
    if _is_error_text(result):
        return True
    if isinstance(result, dict):
        if "error" in result:
            return True
        if str(result.get("status", "")).upper() in _ERROR_STATUSES:
            return True
        if _is_error_text(result.get("result")):
            return True
    return False


def _error(req_id: Any, code: int, message: str) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


def send_error(id: Any, code: int, message: str):
    send_response(_error(id, code, message))


def _detect_client_platform(params: Any) -> str:
    client_info = params.get("clientInfo", {}) if isinstance(params, dict) else {}
    client_name = str(client_info.get("name", "")).lower() if isinstance(client_info, dict) else ""
    for marker in ("claude", "cursor", "copilot", "kiro"):
        if marker in client_name:
            return marker
    return DEFAULT_CLIENT_PLATFORM


def _tool_result(req_id: Any, text: str, is_error: bool) -> Dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "result": {"content": [{"type": "text", "text": text}], "isError": is_error},
    }


def handle_request(request: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    global _session_id, _client_platform

    method = request.get("method")
    params = request.get("params", {})
    req_id = request.get("id")

    if method == "initialize":
        _session_id = uuid.uuid4().hex
        _client_platform = _detect_client_platform(params)
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "aegis-mcp", "version": _server_version()},
            },
        }
    if method == "notifications/initialized":
        return None
    if method not in ("tools/list", "tools/call"):
        return _error(req_id, -32601, f"Method not found: {method}")
    if _session_id is None:
        return _error(req_id, -32002, "Server not initialized")
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": TOOL_DEFINITIONS}}

    if _workspace_error:
        return _tool_result(req_id, _workspace_error, True)
    if not isinstance(params, dict):
        return _error(req_id, -32602, "Tool call params must be an object.")

    name = params.get("name")
    args = params.get("arguments", {})
    if args is None:
        args = {}
    if not isinstance(args, dict):
        return _error(req_id, -32602, "Tool arguments must be an object.")
    if not is_known_tool(name):
        return _error(req_id, -32602, f"Unknown tool: {name}")
    if not _check_rate_limit(name):
        max_calls, window = _RATE_LIMITS[name]
        return _error(req_id, -32000, f"Rate limit exceeded for '{name}': max {max_calls} calls per {window}s")

    # The client never chooses the workspace or the attribution of what it reports.
    args = strip_server_owned(args)
    if _canonical_workspace:
        args["workspace"] = _canonical_workspace
    args["_host"] = _client_platform
    args["_session"] = _session_id

    try:
        # Handlers may print progress notes; stdout belongs to the JSON-RPC framing.
        with contextlib.redirect_stdout(sys.stderr):
            result = execute_tool(name, args)
    except Exception as exc:
        traceback.print_exc(file=sys.stderr)
        return _tool_result(req_id, f"Tool execution failed: {exc}", True)
    text = result if isinstance(result, str) else json.dumps(result)
    return _tool_result(req_id, text, _is_error_result(result))


def _resolve_workspace() -> tuple[Optional[Workspace], str]:
    """Bind the operator pin (AEGIS_WORKSPACE) or the cwd, without creating anything.

    Returns (workspace, "") or (None, reason). $HOME is never a workspace (H8): v3.3
    created ~/.aegis/rules there, so that directory existing proves nothing.
    """
    try:
        candidate = os.environ.get("AEGIS_WORKSPACE") or os.getcwd()
        if Path(candidate).resolve() == Path.home().resolve():
            return None, f"{candidate} is the home directory"
        return Workspace.confine(candidate), ""
    except (ValueError, OSError, RuntimeError) as exc:
        return None, str(exc) or type(exc).__name__


def run_stdio_server():
    global _canonical_workspace
    global _workspace_error

    _canonical_workspace, reason = _resolve_workspace()
    _workspace_error = None
    if _canonical_workspace is None:
        # Stay up so the host does not mark the server failed; tools/call explains why.
        _workspace_error = NOT_GOVERNED_MESSAGE
        print(f"aegis-mcp: {NOT_GOVERNED_MESSAGE} ({reason})", file=sys.stderr)

    try:
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                request = json.loads(line)
            except json.JSONDecodeError:
                send_error(None, -32700, "Parse error")
                continue

            if not isinstance(request, dict):
                # Batches are not supported; a scalar or array frame is an Invalid Request.
                send_error(None, -32600, "Invalid Request")
                continue

            try:
                if request.get("jsonrpc") != "2.0":
                    if "id" in request:
                        send_error(request["id"], -32600, "Invalid Request")
                    continue

                response = handle_request(request)
                if "id" in request and response:
                    send_response(response)
            except Exception:
                traceback.print_exc(file=sys.stderr)
                if "id" in request:
                    send_error(request["id"], -32603, "Internal error")
    except (BrokenPipeError, KeyboardInterrupt):
        pass

    # Shutdown deliberately runs nothing (ADR 0005 AD-1): close-time reflection ran the
    # project's test target and, with N servers per repo, recorded one change N times.
    return 0


def main():
    sys.exit(run_stdio_server())

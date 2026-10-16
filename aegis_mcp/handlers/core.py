"""aegis_scan: the rules that apply to the files about to change."""
from __future__ import annotations

from pathlib import PurePath
import sys
from typing import Any, List, Optional, Set, Tuple

from aegis_core import hosts
from aegis_core.scan import scan, scan_user_layer
from aegis_core.skills.slots import render_scan_result
from aegis_mcp.registry import _STATUS_FAIL, DEFAULT_CLIENT_PLATFORM, NOT_GOVERNED_MESSAGE, _get_workspace

# (workspace root, session, files) already recorded: one scan event per session and files.
_RECORDED: Set[Tuple[str, str, Tuple[str, ...]]] = set()


def _slot_profile(host: Any) -> str:
    """The ${SLOT.*} profile of the identified host (host-matrix §3.3 ``slot_profile``).

    Any other value (an in-process caller's platform name) goes to the slot table as
    given, which maps what it does not know to the generic profile.
    """
    if not host:
        return DEFAULT_CLIENT_PLATFORM
    try:
        return hosts.get(str(host)).slot_profile
    except KeyError:
        return str(host)


def _record_scan(workspace: Any, args: dict, files: Optional[List[str]]) -> None:
    """One ``scan`` activity event per (session, files) for aegis status --compliance.

    Telemetry never costs the agent its guidance: a failed append is logged and the
    scan result stands.
    """
    from aegis_core import gitsafe, scan_compliance

    session = args.get("_session")
    if not session:
        return
    basis = "files"
    if files is None:
        basis = "git_diff"
        files = gitsafe.changed_files(workspace.root, "working") or []
    paths = tuple(sorted({PurePath(f).as_posix() for f in files}))
    key = (str(workspace.root), str(session), paths)
    if not paths or key in _RECORDED:
        return
    try:
        scan_compliance.record(
            workspace, "scan", host=str(args.get("_host") or DEFAULT_CLIENT_PLATFORM), session=str(session),
            files=paths, client={"name": args.get("_client_name") or "", "version": args.get("_client_version") or ""},
            binding=args.get("_binding"), basis=basis,
        )
    except Exception as exc:  # telemetry only: never fail the scan
        print(f"aegis-mcp: scan event not recorded: {exc}", file=sys.stderr)
        return
    _RECORDED.add(key)


def _scan_user_layer(args: dict) -> dict:
    """Nothing governs this call (H8): the read-only user layer, never a ledger write."""
    files = args.get("files")
    if files is not None and (not isinstance(files, (list, tuple)) or not all(isinstance(f, str) for f in files)):
        return {"error": "'files' must be a list of file paths", "status": _STATUS_FAIL}
    res = scan_user_layer(list(files) if files else None)
    if res.get("status") == _STATUS_FAIL:
        return res
    res = {"status": "not_governed", "message": NOT_GOVERNED_MESSAGE, "reason": args.get("_unbound"), **res}
    return render_scan_result(res, _slot_profile(args.get("_host")), None)


def handle_scan(args: dict) -> dict:
    """Express the JIT rules for the given files (or the git diff when none are given)."""
    if args.get("_unbound"):
        return _scan_user_layer(args)
    try:
        workspace = _get_workspace(args)
    except ValueError as exc:
        return {"error": str(exc), "status": _STATUS_FAIL}
    files = args.get("files")
    if files is not None:
        if not isinstance(files, (list, tuple)) or not all(isinstance(f, str) for f in files):
            return {"error": "'files' must be a list of file paths", "status": _STATUS_FAIL}
        try:
            files = [str(workspace.confine_path(f)[1]) for f in files]
        except ValueError as exc:
            return {"error": str(exc), "status": _STATUS_FAIL}

    res = scan(workspace, changed_files=files)
    if res.get("status") == _STATUS_FAIL:
        return res
    _record_scan(workspace, args, files)
    return render_scan_result(res, _slot_profile(args.get("_host")), workspace)

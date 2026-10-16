"""aegis_scan: the rules that apply to the files about to change."""
from __future__ import annotations

from pathlib import PurePath
import sys
from typing import Any, List, Optional, Set, Tuple

from aegis_core import hosts
from aegis_core.scan import scan, scan_user_layer
from aegis_mcp.registry import _STATUS_FAIL, DEFAULT_CLIENT_PLATFORM, NOT_GOVERNED_MESSAGE, _get_workspace

# (workspace root, session, files) already recorded: one scan event per session and files.
_RECORDED: Set[Tuple[str, str, Tuple[str, ...]]] = set()


def _add_scan_warnings(res: dict, warnings: List[str]) -> None:
    existing = res.get("warnings")
    merged = list(existing) if isinstance(existing, list) else []
    merged.extend(w for w in warnings if w not in merged)
    if merged:
        res["warnings"] = merged


def _interpolate_scan_slots(res: dict, platform: str, workspace: Any) -> dict:
    """Resolve ${SLOT.*} placeholders in JIT scan results for the active MCP client platform.

    The agent reads this output, so slot values are sanitized before inlining and
    ignored keys or unparseable config files are reported in res["warnings"] (H5).
    """
    from aegis_core.skills.slots import SlotRegistry, SlotResolutionError

    try:
        loaded = SlotRegistry.for_platform(platform, workspace=str(workspace) if workspace is not None else None)
    except (SlotResolutionError, OSError, RuntimeError):
        # Slot loading must never cost the agent its guidance. The error can quote file
        # content or paths, so report a fixed message instead.
        _add_scan_warnings(res, [
            "config files (.aegis/config.json or ~/.aegis/config.json) could not be read or parsed; "
            "${SLOT.*} placeholders were left unresolved"
        ])
        return res
    _add_scan_warnings(res, loaded.warnings)
    reg = loaded.sanitized()

    val = res.get("guidance")
    if isinstance(val, str) and "${SLOT." in val:
        res["guidance"] = reg.resolve(val, strict=False)

    seen_ids = set()
    for list_key in ("relevant_rules", "invariant_warnings"):
        items = res.get(list_key)
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict) or id(item) in seen_ids:
                continue
            seen_ids.add(id(item))
            for field in ("body", "hypothesis", "prediction"):
                val = item.get(field)
                if isinstance(val, str) and "${SLOT." in val:
                    item[field] = reg.resolve(val, strict=False)
    return res


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
    return _interpolate_scan_slots(res, _slot_profile(args.get("_host")), None)


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
    return _interpolate_scan_slots(res, _slot_profile(args.get("_host")), workspace)

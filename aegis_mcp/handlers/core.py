"""aegis_scan: the rules that apply to the files about to change."""
from __future__ import annotations

from typing import Any, List

from aegis_mcp.jit_engine import express as jit_express
from aegis_mcp.registry import _STATUS_FAIL, DEFAULT_CLIENT_PLATFORM, _get_workspace


def _add_scan_warnings(res: dict, warnings: List[str]) -> None:
    existing = res.get("warnings")
    merged = list(existing) if isinstance(existing, list) else []
    merged.extend(w for w in warnings if w not in merged)
    if merged:
        res["warnings"] = merged


def _interpolate_scan_slots(res: dict, platform: str, workspace: Any) -> dict:
    """Resolve ${SLOT.*} placeholders in JIT scan results for the active MCP client platform.

    The agent reads this output, so slot values are sanitized before inlining and
    ignored or unparseable slot files are reported in res["warnings"] (H5).
    """
    from aegis_core.skills.slots import SlotRegistry, SlotResolutionError

    try:
        loaded = SlotRegistry.for_platform(platform, workspace=str(workspace))
    except (SlotResolutionError, OSError, RuntimeError):
        # Slot loading must never cost the agent its guidance. The error can quote file
        # content or paths, so report a fixed message instead.
        _add_scan_warnings(res, [
            "slot files (.aegis/slots.yaml or ~/.aegis/slots.yaml) could not be read or parsed; "
            "${SLOT.*} placeholders were left unresolved"
        ])
        return res
    _add_scan_warnings(res, loaded.warnings)
    reg = loaded.sanitized()

    val = res.get("guidance")
    if isinstance(val, str) and "${SLOT." in val:
        res["guidance"] = reg.resolve(val, strict=False)

    seen_ids = set()
    for list_key in ("relevant_rules", "genome_guidance", "invariant_warnings"):
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


def handle_scan(args: dict) -> dict:
    """Express the JIT rules for the given files (or the git diff when none are given)."""
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

    res = jit_express(workspace, changed_files=files)
    if not isinstance(res, dict):
        return res
    platform = args.get("_host") or DEFAULT_CLIENT_PLATFORM
    return _interpolate_scan_slots(res, str(platform), workspace)

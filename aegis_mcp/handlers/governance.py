"""Governance execution handlers: cell creation, inventory, proposal, manifests, and swarm handoff."""
from __future__ import annotations

import os
import sys
import uuid
from typing import Any, Dict

from aegis_core.integrity import generate_key, generate_manifest, load_key, save_manifest
from aegis_mcp.jit_engine import express as jit_express
from aegis_mcp.registry import (
    _STATUS_FAIL,
    _STATUS_PASS,
    _VALID_OUTCOMES,
    _classify_propose_result,
    _get_workspace,
    _list_cells_stdlib,
    build_cell_create_prompt,
    soma_propose_change,
)

__all__ = [
    "_handle_create_cell",
    "_handle_create_rule",
    "_handle_list_cells",
    "_handle_list_rules",
    "_handle_propose_change",
    "_handle_generate_manifest",
    "_handle_soma_handoff",
    "_handle_report_outcome",
    "_handle_capture_insight",
]


def _handle_create_cell(args: dict, gov) -> dict:
    try:
        prompt = build_cell_create_prompt(
            description=args.get("description"),
            domain_hint=args.get("domain"),
            cell_type=args.get("rule_type") or args.get("cell_type"),
            args=args,
        )
    except ValueError as exc:
        return {"error": str(exc), "status": _STATUS_FAIL}
    if args.get("dry_run"):
        return {
            "prompt": prompt,
            "rule_prompt": prompt,
            "dry_run": True,
            "instruction": "Dry run: showing prompt that would be used. No cell will be created.",
        }
    return {
        "prompt": prompt,
        "rule_prompt": prompt,
        "instruction": "Process this prompt and return the cell YAML. Then use a file-writing tool to save it to the appropriate .aegis/rules/ directory.",
    }


_handle_create_rule = _handle_create_cell


def _handle_list_cells(args: dict, gov):
    cell_type = args.get("rule_type") or args.get("cell_type")
    if gov:
        try:
            return gov.list_cells(cell_type=cell_type)
        except RuntimeError as exc:
            return {"status": _STATUS_FAIL, "error": str(exc)}
    try:
        workspace = _get_workspace(args)
    except ValueError as exc:
        return {"status": _STATUS_FAIL, "error": str(exc)}
    return _list_cells_stdlib(workspace, cell_type=cell_type)


_handle_list_rules = _handle_list_cells


def _handle_propose_change(args: dict, gov) -> dict:
    if not soma_propose_change:
        return {"error": "soma_propose_change not available"}
    try:
        workspace = _get_workspace(args)
    except ValueError as exc:
        return {"error": str(exc), "status": _STATUS_FAIL}
    file_path = args.get("file_path")
    if not file_path:
        return {"error": "file_path is required", "status": _STATUS_FAIL}
    try:
        _, rel_path = workspace.confine_path(file_path)
        file_path = str(rel_path)
    except ValueError as exc:
        return {"error": str(exc), "status": _STATUS_FAIL}
    proposed_content = args.get("proposed_content")

    # Express JIT rules for the given file to get active playbooks
    jit_result = jit_express(workspace, changed_files=[file_path])
    active_playbooks = jit_result.get("relevant_cells", [])

    result = soma_propose_change(file_path, proposed_content, active_playbooks, workspace=workspace)
    status, verdict = _classify_propose_result(result)
    payload = {"result": result, "status": status}
    if verdict:
        payload["verdict"] = verdict
    return payload


def _handle_generate_manifest(args: dict, gov) -> dict:
    try:
        workspace = _get_workspace(args)
    except ValueError as exc:
        return {"error": str(exc), "status": "FAIL"}
    cells_dir = str(workspace.rules_dir)

    key_created = False
    if args.get("generate_key") and load_key(workspace) is None:
        generate_key(workspace)
        key_created = True

    manifest = generate_manifest(cells_dir)
    save_manifest(workspace, manifest)

    return {
        "status": "OK",
        "cell_count": manifest["cell_count"],
        "rule_count": manifest.get("rule_count", manifest["cell_count"]),
        "signed": "signature" in manifest,
        "key_generated": key_created,
        "generated_at": manifest["generated_at"],
    }


def _handle_report_outcome(args: dict, gov) -> dict:
    try:
        workspace = _get_workspace(args)
    except ValueError as exc:
        return {"error": str(exc), "status": _STATUS_FAIL}
    raw_outcome = args.get("outcome")
    outcome_value = raw_outcome.strip().lower() if isinstance(raw_outcome, str) else None
    if outcome_value not in _VALID_OUTCOMES:
        return {
            "error": (
                f"Invalid 'outcome': {raw_outcome!r}. "
                f"Expected one of {list(_VALID_OUTCOMES)}."
            ),
            "status": _STATUS_FAIL,
        }
    if "idempotency_key" not in args or args.get("idempotency_key") is None:
        idempotency_key = uuid.uuid4().hex
    else:
        idempotency_key = args.get("idempotency_key")
    if not isinstance(idempotency_key, str) or not idempotency_key:
        return {
            "error": "'idempotency_key' must be a nonempty string.",
            "status": _STATUS_FAIL,
        }
    raw_cells_used = args.get("rules_used") if "rules_used" in args else args.get("cells_used")
    if raw_cells_used is None:
        if "rules" in args:
            raw_cells_used = args["rules"]
        elif "cell_id" in args:
            val = args["cell_id"]
            raw_cells_used = [val] if isinstance(val, str) else val
        elif "rule_id" in args:
            val = args["rule_id"]
            raw_cells_used = [val] if isinstance(val, str) else val
    if raw_cells_used is not None:
        if not isinstance(raw_cells_used, (list, tuple)) or not all(isinstance(c, str) for c in raw_cells_used):
            return {
                "error": "'cells_used' must be a list of cell names.",
                "status": _STATUS_FAIL,
            }
        cells_used = list(raw_cells_used)
    else:
        cells_used = []

    if cells_used:
        invalid = workspace.validate_rule_names(cells_used)
        if invalid:
            return {
                "error": f"Unknown cell(s): {invalid}. Only existing cells can be reported.",
                "status": _STATUS_FAIL,
            }
    tests_passed = args.get("tests_passed")
    rework_count = args.get("rework_count", 0)
    notes = args.get("notes", "")
    signal_map = {
        "success": "tp",
        "tp": "tp",
        "failure": "fp",
        "fp": "fp",
        "partial": "trigger",
        "pass": "tp",
        "fail": "fp",
    }
    metadata = {
        "notes": notes,
        "tests_passed": tests_passed,
        "rework_count": rework_count,
    }
    events = [
        {
            "cell_name": cell_id,
            "signal_type": signal_map.get(outcome_value, "trigger"),
            "source": "mcp",
            "metadata": metadata,
            "principal": "mcp",
            "idempotency_scope": "report_outcome",
            "idempotency_key": idempotency_key,
        }
        for cell_id in cells_used
    ]
    try:
        from aegis_core.telemetry import append_signals, read_generation

        generation = read_generation(workspace)
        records = append_signals(workspace, events, expected_generation=generation)
    except Exception as exc:
        return {
            "status": _STATUS_FAIL,
            "error": f"Failed to record outcome: {exc}",
        }
    return {"status": "recorded", "records": records}


def _handle_capture_insight(args: dict, gov) -> dict:
    try:
        workspace = _get_workspace(args)
    except ValueError as exc:
        return {"error": str(exc), "status": _STATUS_FAIL}
    try:
        if sys.modules.get("aegis_core.insights") is None and "aegis_core.insights" in sys.modules:
            raise ImportError("aegis_core.insights is not importable.")
        from aegis_core.insights import capture_insight
    except ImportError:
        return {"error": "aegis_core.insights is not importable.", "status": _STATUS_FAIL}
    try:
        context_files_arg = args.get("context_files") or []
        if not isinstance(context_files_arg, (list, tuple)) or not all(isinstance(f, str) for f in context_files_arg):
            return {"error": "'context_files' must be a list of file paths", "status": _STATUS_FAIL}
        scaffold_wall = bool(args.get("scaffold_wall", args.get("scaffold_rule", False)))
        wall_id = args.get("wall_id") or args.get("rule_id")
        record = capture_insight(
            workspace=workspace,
            insight=args.get("insight", ""),
            context_files=[str(workspace.confine_path(f)[1]) for f in context_files_arg],
            source_conversation=args.get("source_conversation"),
            category=args.get("category"),
            scaffold_wall=scaffold_wall,
            wall_id=wall_id,
        )
    except ValueError as exc:
        return {"error": str(exc), "status": _STATUS_FAIL}
    return {
        "status": "recorded",
        "insight": record,
    }


def _handle_soma_handoff(args: dict, gov) -> dict:
    from_skill = args.get("from_skill")
    to_skill = args.get("to_skill")
    artifact_type = args.get("artifact_type")
    payload = args.get("payload")
    if not (from_skill and to_skill and artifact_type and payload is not None):
        return {
            "status": _STATUS_FAIL,
            "error": "Missing required handoff arguments: 'from_skill', 'to_skill', 'artifact_type', and 'payload' are required.",
        }
    try:
        workspace = _get_workspace(args)
    except ValueError as exc:
        return {"status": _STATUS_FAIL, "error": str(exc)}

    try:
        from aegis_core.skills.handoff import soma_handoff

        ticket = soma_handoff(
            workspace=workspace,
            from_skill=from_skill,
            to_skill=to_skill,
            artifact_type=artifact_type,
            payload=payload,
            producer_tier=args.get("producer_tier"),
            session_secret=args.get("session_secret"),
        )
        return {
            "status": "OK",
            "ticket": ticket.to_dict(),
            "prompt_block": ticket.format_prompt_block(),
        }
    except Exception as exc:
        return {"status": _STATUS_FAIL, "error": str(exc)}


try:
    import aegis_mcp.handlers.telemetry as _telemetry_mod
    _telemetry_mod._handle_report_outcome = _handle_report_outcome
    _telemetry_mod._handle_capture_insight = _handle_capture_insight
except Exception:
    pass

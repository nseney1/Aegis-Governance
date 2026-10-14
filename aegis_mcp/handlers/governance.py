"""Governance execution handlers: cell creation, inventory, proposal, manifests, and swarm handoff."""
from __future__ import annotations

import os
from typing import Any, Dict

from aegis_mcp.integrity import generate_key, generate_manifest, load_key, save_manifest
from aegis_mcp.jit_engine import express as jit_express
from aegis_mcp.registry import (
    _STATUS_FAIL,
    _STATUS_PASS,
    _classify_propose_result,
    _get_workspace,
    _list_cells_stdlib,
    build_cell_create_prompt,
    soma_propose_change,
)

__all__ = [
    "_handle_create_cell",
    "_handle_list_cells",
    "_handle_propose_change",
    "_handle_generate_manifest",
    "_handle_soma_handoff",
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
            "dry_run": True,
            "instruction": "Dry run: showing prompt that would be used. No cell will be created.",
        }
    return {
        "prompt": prompt,
        "instruction": "Process this prompt and return the cell YAML. Then use a file-writing tool to save it to the appropriate .aegis/rules/ directory.",
    }


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
        "signed": "signature" in manifest,
        "key_generated": key_created,
        "generated_at": manifest["generated_at"],
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

"""Verification execution handlers: verify_changes, poll_verification, checkpoint, request_receipt."""
from __future__ import annotations

import os
from typing import Any, Dict, List

from aegis_mcp.registry import (
    _CHECKPOINT_NAMES,
    _STATUS_FAIL,
    _STATUS_PASS,
    _get_workspace,
    _run_checkpoint_checks,
    resolve_workspace,
)

__all__ = [
    "_handle_verify_changes",
    "_handle_poll_verification",
    "_handle_checkpoint",
    "_handle_request_receipt",
]


def _handle_verify_changes(args: dict, gov) -> dict:
    try:
        workspace = _get_workspace(args)
    except ValueError as exc:
        return {"error": str(exc), "status": _STATUS_FAIL}
    files = args.get("files") or []
    if not isinstance(files, (list, tuple)) or not all(isinstance(f, str) for f in files):
        return {"error": "'files' must be a list of file paths", "status": _STATUS_FAIL}
    if not files and not args.get("async_mode", False):
        return {
            "status": _STATUS_FAIL,
            "summary": "No files specified to verify.",
            "layer1_only": True,
            "evidence": [],
        }
    try:
        files = [workspace.confine_path(f)[1] for f in files]
    except ValueError as exc:
        return {"error": str(exc), "status": _STATUS_FAIL}
    layer1_only = args.get("layer1_only", True)
    async_mode = args.get("async_mode", False)
    if async_mode:
        from aegis_core.verification.jobs import submit_verification_job

        ws_str = str(getattr(workspace, "root", workspace))
        job = submit_verification_job(
            workspace=ws_str,
            files=files,
            layer1_only=layer1_only,
            task_plan=args.get("task_plan", ""),
            receipt=args.get("receipt"),
        )
        return {
            "status": "QUEUED",
            "job_id": job.job_id,
            "message": "Verification job enqueued. Poll with aegis_poll_verification.",
            "created_at": job.created_at,
        }

    try:
        __import__("aegis_core.verification")
        from aegis_core.verification import VerificationPipeline, runner
    except ImportError as exc:
        return {"error": f"aegis_core.verification is not importable: {exc}", "status": _STATUS_FAIL}

    rebuttal = args.get("rebuttal")
    task_plan = args.get("task_plan", "")

    if not layer1_only:
        pipeline = VerificationPipeline()
        pipeline_res = pipeline.run(
            changed_files=files,
            workspace=workspace,
            task_plan=task_plan,
            in_band=True,
            rebuttal=rebuttal,
        )

        evidence = [
            {"tool": r.tool, "target": r.target, "verdict": r.verdict, "detail": r.detail}
            for r in pipeline_res.layer1_evidence
        ]
        try:
            from aegis_core.outcomes import record_verification_telemetry

            record_verification_telemetry(
                workspace=workspace,
                target_files=files,
                passed=pipeline_res.passed,
                verdict=pipeline_res.verdict.name,
                layer1_evidence=evidence,
                source="mcp",
            )
        except Exception:
            pass

        if pipeline_res.charge_sheet:
            res_dict = pipeline_res.charge_sheet.to_dict()
            res_dict["layer1_passed"] = pipeline_res.layer1_passed
            res_dict["summary"] = pipeline_res.summary
            return res_dict

        resp = {
            "status": pipeline_res.verdict.name,
            "verdict": pipeline_res.verdict.name,
            "passed": pipeline_res.passed,
            "summary": pipeline_res.summary,
            "layer1_only": False,
            "evidence": evidence,
        }
        if pipeline_res.arbitration_result:
            if pipeline_res.evidence_path:
                resp["evidence_file"] = pipeline_res.evidence_path
                resp["cycle"] = getattr(pipeline_res, "cycle", None)
            resp["divergences"] = [
                {
                    "category": d.category.value,
                    "type": d.divergence_type,
                    "resolution": d.resolution,
                }
                for d in pipeline_res.arbitration_result.divergences
            ]
            resp["convergences"] = [c.value for c in pipeline_res.arbitration_result.convergences]
        return resp

    results = runner.run_layer1(changed_files=files, repo_root=workspace)
    verdict = runner.gate_verdict(results)
    summary = runner.format_summary(results)
    evidence = [
        {"tool": r.tool, "target": r.target, "verdict": r.verdict, "detail": r.detail}
        for r in results
    ]
    try:
        from aegis_core.outcomes import record_verification_telemetry

        record_verification_telemetry(
            workspace=workspace,
            target_files=files,
            passed=bool(verdict),
            verdict="PASS" if verdict else "FAIL",
            layer1_evidence=evidence,
            source="mcp",
        )
    except Exception:
        pass
    return {
        "status": "PASS" if verdict else "FAIL",
        "summary": summary,
        "layer1_only": True,
        "evidence": evidence,
    }


def _handle_poll_verification(args: dict, gov) -> dict:
    job_id = args.get("job_id")
    if not job_id:
        return {"error": "Missing required argument 'job_id'", "status": _STATUS_FAIL}
    from aegis_core.verification.jobs import get_job

    job = get_job(job_id)
    if job is None:
        return {"error": f"Verification job '{job_id}' not found or expired.", "status": _STATUS_FAIL}
    if job.status == "COMPLETED":
        return {
            "status": "COMPLETED",
            "job_id": job.job_id,
            "completed_at": job.completed_at,
            "result": job.result,
            "receipt": job.receipt,
        }
    elif job.status == "FAILED":
        return {
            "status": "FAILED",
            "job_id": job.job_id,
            "error": job.error,
            "completed_at": job.completed_at,
        }
    elif job.status == "RUNNING":
        return {
            "status": "RUNNING",
            "job_id": job.job_id,
            "started_at": job.started_at,
        }
    else:
        return {
            "status": job.status,
            "job_id": job.job_id,
            "created_at": job.created_at,
        }


def _handle_checkpoint(args: dict, gov) -> dict:
    try:
        workspace = _get_workspace(args)
    except ValueError as exc:
        return {"error": str(exc), "status": _STATUS_FAIL}
    if _run_checkpoint_checks is None:
        return {"error": "checkpoint verification is not available", "status": _STATUS_FAIL}
    issues = _run_checkpoint_checks(workspace.root)
    return {
        "status": "PASS" if not issues else "FAIL",
        "checks": _CHECKPOINT_NAMES,
        "issue_count": len(issues),
        "issues": issues,
    }


def _handle_request_receipt(args: dict, gov) -> dict:
    operation = args.get("operation")
    if not operation:
        return {"error": "Missing required argument 'operation'", "status": _STATUS_FAIL}
    op_args = args.get("arguments", {})
    if not isinstance(op_args, dict):
        return {"error": "arguments must be an object", "status": _STATUS_FAIL}
    from aegis_core.receipts import (
        compute_cell_digest,
        compute_file_digest,
        issue_receipt,
        strip_server_owned,
        target_paths,
    )

    workspace = (
        args.get("workspace")
        or (str(gov.repo_root) if (gov and hasattr(gov, "repo_root")) else resolve_workspace())
    )

    clean_args = strip_server_owned(op_args)
    session_id = args.get("session_id") or args.get("_sessionToken") or "local-session"
    try:
        file_digest = compute_file_digest(workspace, target_paths(clean_args))
        cell_digest = compute_cell_digest(workspace)
    except (ValueError, RuntimeError, OSError) as exc:
        return {"error": str(exc), "status": _STATUS_FAIL}

    receipt_id = issue_receipt(
        session_id=session_id,
        workspace=workspace,
        operation=operation,
        args=clean_args,
        file_digest=file_digest,
        cell_digest=cell_digest,
        ttl_seconds=300,
    )
    return {
        "receipt": receipt_id,
        "operation": operation,
        "status": "ISSUED",
    }

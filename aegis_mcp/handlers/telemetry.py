"""Telemetry execution handlers: report_outcome, capture_insight, grade, coverage, fitness."""
from __future__ import annotations

import os
from typing import Any, Dict

from aegis_mcp.registry import (
    _STATUS_FAIL,
    _STATUS_PASS,
    _VALID_OUTCOMES,
    _get_workspace,
)

__all__ = [
    "_handle_report_outcome",
    "_handle_capture_insight",
    "_handle_grade",
    "_handle_coverage",
    "_handle_fitness",
]


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
    idempotency_key = args.get("idempotency_key")
    if not isinstance(idempotency_key, str) or not idempotency_key:
        return {
            "error": "'idempotency_key' must be a nonempty string.",
            "status": _STATUS_FAIL,
        }
    raw_cells_used = args.get("cells_used")
    if raw_cells_used is None:
        if "cell_id" in args:
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
        import sys
        if sys.modules.get("aegis_core.insights") is None and "aegis_core.insights" in sys.modules:
            raise ImportError("aegis_core.insights is not importable.")
        from aegis_core.insights import capture_insight
    except ImportError:
        return {"error": "aegis_core.insights is not importable.", "status": _STATUS_FAIL}
    try:
        context_files_arg = args.get("context_files") or []
        if not isinstance(context_files_arg, (list, tuple)) or not all(isinstance(f, str) for f in context_files_arg):
            return {"error": "'context_files' must be a list of file paths", "status": _STATUS_FAIL}
        record = capture_insight(
            workspace=workspace,
            insight=args.get("insight", ""),
            context_files=[str(workspace.confine_path(f)[1]) for f in context_files_arg],
            source_conversation=args.get("source_conversation"),
            category=args.get("category"),
            scaffold_wall=bool(args.get("scaffold_wall", False)),
            wall_id=args.get("wall_id"),
        )
    except ValueError as exc:
        return {"error": str(exc), "status": _STATUS_FAIL}
    return {
        "status": "recorded",
        "insight": record,
    }


def _handle_grade(args: dict, gov) -> dict:
    if gov:
        result = gov.grade()
    else:
        try:
            from aegis_core.telemetry import calculate_immune_grade

            workspace = _get_workspace(args)
            result = calculate_immune_grade(workspace)
        except Exception as exc:
            return {"status": _STATUS_FAIL, "error": str(exc)}
    if result is None:
        return {
            "coverage": {"pct": 0.0, "grade": "F"},
            "avg_fitness": {"pct": 0.0, "grade": "F", "score": 0.0},
            "diversity": {"pct": 0.0, "grade": "F"},
            "staleness": {"pct": 0.0, "grade": "F"},
            "wall_integrity": {"pct": 0.0, "grade": "F"},
            "tiers": {},
            "overall": {"pct": 0.0, "grade": "F"},
            "status": "PASS",
            "note": "No cells found to grade",
        }
    if not isinstance(result, dict):
        return {"status": _STATUS_FAIL, "error": str(result)}
    return result


def _handle_coverage(args: dict, gov):
    if gov:
        result = gov.coverage_report()
    else:
        try:
            from aegis_core.telemetry import calculate_coverage

            workspace = _get_workspace(args)
            result = calculate_coverage(workspace)
        except Exception as exc:
            return {"status": _STATUS_FAIL, "error": str(exc)}
    if not isinstance(result, dict):
        return {"status": _STATUS_FAIL, "error": str(result)}
    return result


def _handle_fitness(args: dict, gov):
    bayesian = args.get("bayesian", False)
    if gov:
        result = gov.fitness_landscape(bayesian=bayesian)
    else:
        try:
            from aegis_core.lifecycle import compute_cells_fitness

            workspace = _get_workspace(args)
            result = compute_cells_fitness(workspace=workspace, bayesian=bayesian)
        except Exception as exc:
            return {"status": _STATUS_FAIL, "error": str(exc)}
    if isinstance(result, dict) and "error" in result:
        result["status"] = _STATUS_FAIL
    return result

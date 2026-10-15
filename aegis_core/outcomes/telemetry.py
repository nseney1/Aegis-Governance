"""Outcome telemetry: MCP-reported outcomes and ambient verification evidence."""
from __future__ import annotations

import json
import os
from pathlib import Path
import secrets
import sys
from typing import Any, Optional

from aegis_core.workspace import Workspace, as_workspace, resolve_workspace

__all__ = [
    "VERIFY_TIMEOUT",
    "detect_test_runner",
    "capture_test_outcome",
    "capture_build_outcome",
    "capture_mcp_outcomes",
    "record_verification_telemetry",
]

# Aegis no longer executes a project's own test or build commands (ADR 0005 AD-1, D1).
# The outcome engine ran on every MCP shutdown and session-close hook, so these helpers
# ran the repo's Makefile/npm/cargo/go targets through a shell once per server and
# credited the exit codes to rules. Outcomes now come only from explicit reports and CI.
# The five names below survive only because the aegis_core.outcomes and
# aegis_core.telemetry facades re-export them; they go with those facades (D7).
IMPLICIT_EXECUTION_REMOVED = "implicit test/build execution was removed (ADR 0005 AD-1)"
VERIFY_TIMEOUT = 60


def _run_verify(cmd: str, cwd: str, timeout: Optional[int] = None) -> Optional[dict]:
    raise RuntimeError(f"{IMPLICIT_EXECUTION_REMOVED}; refusing to run {cmd!r}")


def detect_test_runner(workspace: str) -> tuple[Optional[str], Optional[str]]:
    """Never proposes a command: nothing in Aegis runs a project's test suite."""
    return None, None


def capture_test_outcome(workspace: str) -> dict:
    """Always unverified: test results reach the ledger only through explicit reports or CI."""
    return {"verified": False, "reason": IMPLICIT_EXECUTION_REMOVED, "passed": None}


def capture_build_outcome(workspace: str) -> dict:
    """Always unverified: build results reach the ledger only through explicit reports or CI."""
    return {"verified": False, "reason": IMPLICIT_EXECUTION_REMOVED, "passed": None}


def capture_mcp_outcomes(workspace: Workspace | Path | str) -> list[dict]:
    """Read any aegis_report_outcome calls from this session from .aegis/evidence/signals.jsonl."""
    ws = workspace if isinstance(workspace, Workspace) else (
        Workspace(root=Path(workspace).resolve()) if workspace else Workspace.resolve()
    )
    signals_file = str(ws.signals_file)
    outcomes = []
    if not os.path.isfile(signals_file):
        return outcomes
    try:
        with open(signals_file, "r", encoding="utf-8") as f:
            for line in f:
                line_str = line.strip()
                if not line_str:
                    continue
                try:
                    record = json.loads(line_str)
                except Exception:
                    continue

                sig_type = record.get("signal_type") or record.get("signal") or record.get("outcome")
                if not sig_type:
                    continue

                outcome = record.get("outcome")
                if not outcome:
                    if sig_type in ("tp", "success"):
                        outcome = "success"
                    elif sig_type in ("fp", "failure"):
                        outcome = "failure"
                    elif sig_type in ("trigger", "partial"):
                        outcome = "partial"
                    else:
                        outcome = str(sig_type)
                record["outcome"] = outcome

                cell_id = record.get("cell_id") or record.get("cell_name") or record.get("cell")
                if cell_id and "cell_id" not in record:
                    record["cell_id"] = cell_id
                if cell_id and "cells_used" not in record:
                    record["cells_used"] = [cell_id]

                outcomes.append(record)
    except Exception as exc:
        print(f"    ! failed to read signals file: {exc}", file=sys.stderr)
    return outcomes


def record_verification_telemetry(
    workspace: str,
    target_files: list[str],
    passed: bool,
    verdict: Any = None,
    layer1_evidence: Any = None,
    source: str = "session",
    run_id: Optional[str] = None,
) -> bool:
    """Append ambient verification evidence (triggers and outcomes) for matched cells to the ledger."""
    if not workspace or not target_files:
        return False

    ws = workspace if isinstance(workspace, Workspace) else (
        Workspace(root=Path(workspace).resolve()) if workspace else Workspace.resolve()
    )
    cells_dir = ws.rules_dir
    if not cells_dir.is_dir():
        return False

    from aegis_core.outcomes.engine import match_cells_to_changes
    from aegis_core.outcomes.fitness import compute_credit_weights

    matched = match_cells_to_changes(ws, target_files)
    if not matched:
        return False

    from aegis_core.telemetry import append_signals

    if run_id is None:
        run_id = secrets.token_hex(16)

    credit_weights = compute_credit_weights(matched, target_files)
    events = []
    sig_type = "tp" if passed else "fp"

    for cell in matched:
        cell_id = cell.get("_name") or cell.get("id")
        if not cell_id:
            continue
        weight = float(credit_weights.get(cell_id, 1.0))
        weight = max(0.0, min(1.0, weight))

        # 1. Trigger event
        events.append({
            "cell_name": cell_id,
            "signal_type": "trigger",
            "source": source,
            "metadata": {
                "credit_weight": 1.0,
                "verdict": str(verdict) if verdict is not None else ("PASS" if passed else "FAIL"),
                "target_files": target_files[:20],
            },
            "principal": "verification",
            "idempotency_scope": "run",
            "idempotency_key": f"{run_id}:trig:{cell_id}",
        })

        # 2. Outcome event
        events.append({
            "cell_name": cell_id,
            "signal_type": sig_type,
            "source": source,
            "metadata": {
                "credit_weight": weight,
                "verdict": str(verdict) if verdict is not None else ("PASS" if passed else "FAIL"),
                "passed": passed,
                "evidence_checks": len(layer1_evidence) if layer1_evidence else 0,
            },
            "principal": "verification",
            "idempotency_scope": "run",
            "idempotency_key": f"{run_id}:out:{cell_id}",
        })

    # Ledger only: rule files are never rewritten at runtime (ADR 0005 AD-1/H6). Bumping
    # frontmatter here dirtied tracked .aegis/rules on every `aegis check --hook` and
    # broke the committed manifest.
    try:
        append_signals(workspace, events)
        return True
    except Exception as exc:
        print(f"    ! failed to record ambient verification telemetry: {exc}", file=sys.stderr)
        return False

"""Ambient verification evidence: `aegis check` records rule triggers and outcomes in the ledger."""
from __future__ import annotations

from pathlib import Path
import secrets
import sys
from typing import Any, Optional

from aegis_core.workspace import Workspace

__all__ = ["record_verification_telemetry"]


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

    from aegis_core.telemetry_engine.ledger import append_signals

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

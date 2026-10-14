"""Git signal reflection: reverts, rework analysis, and retrospective commit harvesting."""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import os
from pathlib import Path
import subprocess
from typing import Optional

from aegis_core.workspace import Workspace
from aegis_core.outcomes.fitness import update_cell_fitness

__all__ = ["capture_git_signals", "harvest_git_history"]


def capture_git_signals(workspace: str) -> dict:
    """Always verifiable: reverts and rework from git log."""
    signals = {"reverts": 0, "rework_files": []}
    try:
        log_out = subprocess.check_output(
            ["git", "log", "--oneline", "-5"],
            cwd=workspace, text=True, stderr=subprocess.DEVNULL
        )
        revert_count = sum(1 for line in log_out.splitlines() if "revert" in line.lower())
        signals["reverts"] = revert_count
    except Exception:
        pass

    try:
        log_out = subprocess.check_output(
            ["git", "log", "--name-only", "--format=", "-5"],
            cwd=workspace, text=True, stderr=subprocess.DEVNULL
        )
        files = [f for f in log_out.splitlines() if f.strip()]
        counts = Counter(files)
        signals["rework_files"] = [f for f, c in counts.items() if c > 1]
    except Exception:
        pass

    return signals


def harvest_git_history(workspace: Workspace | Path | str, limit: int = 30, dry_run: bool = False) -> dict:
    """Inspect recent git commit diffs, match touched files to cells, and seed baseline fitness evidence."""
    ws = workspace if isinstance(workspace, Workspace) else (
        Workspace(root=Path(workspace).resolve()) if workspace else Workspace.resolve()
    )
    cells_dir = ws.rules_dir
    if not cells_dir.is_dir():
        return {"commits_inspected": 0, "cells_matched": 0, "signals_minted": 0}

    try:
        cmd = ["git", "log", f"-n{max(1, limit)}", "--name-only", "--format=commit:%H:%cI"]
        res = subprocess.run(cmd, cwd=str(ws.root), capture_output=True, text=True, timeout=15)
        if res.returncode != 0:
            return {"commits_inspected": 0, "cells_matched": 0, "signals_minted": 0, "error": res.stderr}
    except Exception as exc:
        return {"commits_inspected": 0, "cells_matched": 0, "signals_minted": 0, "error": str(exc)}

    commits = []
    current_commit = None
    current_date = None
    current_files = []

    for line in res.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("commit:"):
            if current_commit:
                commits.append((current_commit, current_date, current_files))
            parts = line.split(":", 2)
            current_commit = parts[1]
            current_date = parts[2] if len(parts) > 2 else datetime.now(timezone.utc).isoformat()
            current_files = []
        else:
            current_files.append(line)

    if current_commit:
        commits.append((current_commit, current_date, current_files))

    from aegis_core.outcomes.engine import match_cells_to_changes
    from aegis_core.outcomes.fitness import compute_credit_weights, update_cell_fitness

    all_events = []
    fitness_updates_by_cell = {}
    matched_cell_ids = set()

    for commit_hash, commit_date, files in commits:
        if not files:
            continue
        matched = match_cells_to_changes(ws, files)
        if not matched:
            continue

        credit_weights = compute_credit_weights(matched, files)
        for cell in matched:
            cell_id = cell.get("_name") or cell.get("id")
            if not cell_id:
                continue
            matched_cell_ids.add(cell_id)
            weight = float(credit_weights.get(cell_id, 1.0))
            weight = max(0.0, min(1.0, weight))

            all_events.append({
                "cell_name": cell_id,
                "signal_type": "trigger",
                "source": "ci",
                "metadata": {
                    "credit_weight": 1.0,
                    "commit": commit_hash[:10],
                    "commit_date": commit_date,
                },
                "principal": "git_harvest",
                "idempotency_scope": "commit",
                "idempotency_key": f"{commit_hash[:12]}:trig:{cell_id}",
            })
            all_events.append({
                "cell_name": cell_id,
                "signal_type": "tp",
                "source": "ci",
                "metadata": {
                    "credit_weight": weight,
                    "commit": commit_hash[:10],
                    "commit_date": commit_date,
                },
                "principal": "git_harvest",
                "idempotency_scope": "commit",
                "idempotency_key": f"{commit_hash[:12]}:tp:{cell_id}",
            })

            if cell_id not in fitness_updates_by_cell:
                fitness_updates_by_cell[cell_id] = {
                    "cell": cell_id,
                    "_path": cell.get("_path"),
                    "signal": 1.0,
                    "credit_weight": weight,
                }

    if not dry_run and all_events:
        from aegis_core.telemetry import append_signals

        append_signals(ws, all_events)
        if fitness_updates_by_cell:
            update_cell_fitness(ws, list(fitness_updates_by_cell.values()))

    return {
        "commits_inspected": len(commits),
        "cells_matched": len(matched_cell_ids),
        "signals_minted": len(all_events),
    }

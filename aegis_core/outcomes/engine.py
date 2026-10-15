"""ACE reflector loop: run_outcome_engine, cell matching, and main entrypoint."""
from __future__ import annotations

import os
from pathlib import Path
import secrets
import subprocess
import sys
from typing import Any, Optional

from aegis_core.rule_inventory import find_matching_cells
from aegis_core.workspace import Workspace, as_workspace, resolve_workspace

__all__ = ["match_cells_to_changes", "run_outcome_engine", "main"]


def _get_changed_files(workspace: str) -> list[str]:
    try:
        out = subprocess.check_output(
            ["git", "diff", "--name-only", "HEAD~1"],
            cwd=workspace, text=True, stderr=subprocess.DEVNULL
        )
        files = [f.strip() for f in out.splitlines() if f.strip()]
        if files:
            return files
    except Exception:
        pass

    try:
        out = subprocess.check_output(
            ["git", "status", "--porcelain"],
            cwd=workspace, text=True, stderr=subprocess.DEVNULL
        )
        files = []
        for line in out.splitlines():
            # "XY path": the status is exactly 2 columns plus a space, and X is a
            # space for unstaged edits, so the line must not be stripped first.
            path = line[3:].strip()
            if " -> " in path:
                path = path.split(" -> ", 1)[1]
            if path:
                files.append(path)
        return files
    except Exception:
        return []


def match_cells_to_changes(workspace: Workspace | Path | str, changed_files: list[str]) -> list[dict]:
    ws = as_workspace(workspace)
    cells_dir = ws.rules_dir
    matches = find_matching_cells(str(cells_dir), changed_files, allow_basename_match=True)
    triggered = []
    for m in matches:
        cell_dict = dict(m.frontmatter)
        cell_dict["_name"] = m.cell_id
        cell_dict["_path"] = m.cell_path
        triggered.append(cell_dict)
    return triggered


def run_outcome_engine(workspace: Optional[Workspace | Path | str] = None, mod: Any = None) -> int:
    """Canonical ACE reflector loop."""
    from aegis_core.outcomes.fitness import append_fitness_log, compute_fitness_signals, update_cell_fitness
    from aegis_core.outcomes.harvest import capture_git_signals
    from aegis_core.outcomes.insights import commit_insight_cursor, read_human_insight_signals
    from aegis_core.outcomes.telemetry import capture_mcp_outcomes

    m = mod if mod is not None else sys.modules[__name__]
    resolve_ws = getattr(m, "resolve_workspace", resolve_workspace)
    raw_ws = workspace if workspace is not None else resolve_ws()
    ws = as_workspace(raw_ws)
    cells_dir = ws.rules_dir
    if not cells_dir.is_dir():
        return 0

    print("  Running outcome engine (ACE reflector)...")
    from aegis_core.telemetry import read_generation

    read_gen = getattr(m, "read_generation", read_generation)
    generation = read_gen(ws)

    cap_git = getattr(m, "capture_git_signals", capture_git_signals)
    cap_mcp = getattr(m, "capture_mcp_outcomes", capture_mcp_outcomes)
    read_insights = getattr(m, "read_human_insight_signals", read_human_insight_signals)
    commit_cursor = getattr(m, "commit_insight_cursor", commit_insight_cursor)
    get_changed = getattr(m, "_get_changed_files", _get_changed_files)
    match_cells_fn = getattr(m, "match_cells_to_changes", match_cells_to_changes)
    comp_signals = getattr(m, "compute_fitness_signals", compute_fitness_signals)
    append_log = getattr(m, "append_fitness_log", append_fitness_log)
    update_fitness = getattr(m, "update_cell_fitness", update_cell_fitness)

    # No test/build execution here (ADR 0005 AD-1): the engine never runs a project's
    # own commands. Signals come from git history, explicit reports and human insights.
    outcomes: dict[str, Any] = {}
    outcomes["git"] = cap_git(ws)
    mcp = cap_mcp(ws)
    if mcp:
        outcomes["mcp"] = mcp

    insight_signals, insight_offset = read_insights(ws)
    blind_spots = [s for s in insight_signals if s.get("signal_type") == "blind_spot"]
    cell_boosts = [s for s in insight_signals if s.get("_path") is not None]

    if blind_spots:
        print(f"    {len(blind_spots)} governance blind spot(s) detected from human insights")

    changed_files = get_changed(ws)
    triggered = match_cells_fn(ws, changed_files)

    if not triggered and not cell_boosts:
        print("    No cells matched changed files.")
        commit_cursor(ws, insight_offset)
        return 0

    signals = comp_signals(triggered, outcomes, changed_files=changed_files) if triggered else []

    existing_paths = {s["_path"] for s in signals if "_path" in s}
    for boost in cell_boosts:
        if boost["_path"] not in existing_paths:
            signals.append(boost)
            existing_paths.add(boost["_path"])

    if signals:
        run_idempotency_prefix = secrets.token_hex(16)
        if append_log(
            ws,
            signals,
            outcomes,
            expected_generation=generation,
            idempotency_prefix=run_idempotency_prefix,
        ):
            commit_cursor(ws, insight_offset)
            update_fitness(ws, signals)
        else:
            print("    ! evidence log incomplete; cells and insight cursor left unchanged (will retry)", file=sys.stderr)
    else:
        commit_cursor(ws, insight_offset)

    verified_count = sum(1 for s in signals if s.get("verified"))
    print(f"    {len(signals)} cells evaluated ({verified_count} with verified outcomes)")
    for s in signals:
        indicator = "↑" if s["signal"] > 0 else "↓" if s["signal"] < 0 else "→"
        v = "✓" if s.get("verified") else "?"
        reasons_str = ", ".join(s.get("reasons", [])) or "no signal"
        print(f"      {indicator} [{v}] {s['cell']}: {s['signal']:+.1f} ({reasons_str})")
    return 0


def main(*args, **kwargs) -> int:
    """Outcome engine main entrypoint."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    ws = kwargs.get("workspace")
    if ws is not None:
        return run_outcome_engine(ws)
    return run_outcome_engine()

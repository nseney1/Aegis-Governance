"""Selection pressure, cell crossover, and hypothesis merging."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import sys
from typing import Optional

from aegis_core.yaml import _get_body, dump_frontmatter, parse_frontmatter
from aegis_core.locking import workspace_lock
from aegis_core.storage import atomic_write_text
from aegis_core.workspace import Workspace, resolve_workspace
from aegis_core.workspace.layout import LockResource
from .constants import (
    EXTINCTION_THRESHOLD,
)
from .parsers import (
    find_cell,
    get_type_plural,
    parse_cell,
)

__all__ = [
    "run_cell_selection",
    "select_cell",
    "prune_cells",
]


def run_cell_selection(workspace: Workspace | Path | str | None = None, execute: bool = False) -> int:
    """Selection pressure engine for Soma immune cells."""
    ws = workspace if isinstance(workspace, Workspace) else (
        Workspace(root=Path(workspace).resolve()) if workspace else Workspace.resolve()
    )
    cells_dir = ws.rules_dir
    archive_dir = cells_dir / ".archive"
    evidence_dir = ws.evidence_dir
    evidence_dir.mkdir(parents=True, exist_ok=True)
    fitness_log = evidence_dir / "lifecycle.jsonl"

    if not cells_dir.exists():
        print("No cells directory found.")
        return 0

    print(f"Running cell selection (execute={execute})...")
    if not execute:
        _select(cells_dir, archive_dir, fitness_log, execute)
        return 0
    archive_dir.mkdir(parents=True, exist_ok=True)
    # Moves and rewrites happen under the same rules lock as promote/demote.
    with workspace_lock(ws.root, LockResource.RULES):
        _select(cells_dir, archive_dir, fitness_log, execute)
    return 0


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _select(cells_dir: Path, archive_dir: Path, fitness_log: Path, execute: bool) -> None:
    for root_str, _dirs, files in os.walk(cells_dir):
        if ".archive" in root_str:
            continue
        for f in files:
            if not f.endswith(".md") or f == "README.md":
                continue
            fpath = Path(root_str) / f
            try:
                content = fpath.read_text(encoding="utf-8")
            except Exception:
                continue

            meta = parse_frontmatter(content)
            if not meta:
                continue
            fitness = meta.get("fitness") if isinstance(meta.get("fitness"), dict) else {}

            def get_val(key: str, default: float = 0.0) -> float:
                raw = fitness.get(key, meta.get(key))
                if raw is not None and str(raw) != "null":
                    try:
                        return float(raw)
                    except (ValueError, TypeError):
                        return default
                return default

            triggers = get_val("triggers", 0.0)
            tp = get_val("true_positives", 0.0)
            fp = get_val("false_positives", 0.0)
            cell_type = str(meta.get("type", ""))
            dormant = "dormant_since" in meta or "dormant_since" in fitness

            if triggers == 0:
                category = "DORMANT"
                score = 0.0
            else:
                score = tp / triggers
                if fp > 0 and tp > 0 and fp > 2 * tp:
                    category = "APOPTOSIS_WARNING" if cell_type in ("wall", "invariant") else "APOPTOSIS"
                elif score > 0.7:
                    category = "SURVIVE"
                elif score >= EXTINCTION_THRESHOLD:
                    category = "ADAPT"
                else:
                    category = "EXTINCT"

            print(f"[{category}] {f} (Score: {score:.2f})")

            if execute:
                action = None
                if category in ("EXTINCT", "APOPTOSIS"):
                    if category == "APOPTOSIS":
                        last_gasp_dir = cells_dir / ".last_gasp_queue"
                        last_gasp_dir.mkdir(parents=True, exist_ok=True)
                        dest = last_gasp_dir / f
                        shutil.move(str(fpath), str(dest))
                        action = "last_gasp_requested"
                    else:
                        dest = archive_dir / f
                        shutil.move(str(fpath), str(dest))
                        action = "moved_to_archive"
                elif category == "DORMANT" and not dormant:
                    meta["dormant_since"] = _utc_timestamp()
                    body = _get_body(content).lstrip()
                    atomic_write_text(fpath, dump_frontmatter(meta, body=body))
                    action = "marked_dormant"

                if action:
                    with open(fitness_log, "a", encoding="utf-8") as log:
                        log.write(json.dumps({
                            "timestamp": _utc_timestamp(),
                            "cell": f,
                            "action": action,
                        }) + "\n")


def prune_cells(workspace: Workspace | Path | str | None = None, execute: bool = False) -> int:
    """Evaluate and prune extinct or apoptotic rules."""
    return run_cell_selection(workspace=workspace, execute=execute)


select_cell = run_cell_selection
prune_rules = prune_cells





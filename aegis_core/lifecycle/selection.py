"""Selection pressure, cell crossover, and hypothesis merging."""
from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
import shutil
from typing import Optional

from aegis_core.yaml_engine.frontmatter import _get_body, parse_frontmatter
from aegis_core.yaml_engine.serializer import dump_frontmatter
from aegis_core.storage import append_jsonl, atomic_write_text, locked
from aegis_core.workspace.base import Workspace
from .constants import (
    EXTINCTION_THRESHOLD,
)

__all__ = [
    "PARKED_RULE_DIRS",
    "run_cell_selection",
    "prune_cells",
]


# Rules parked out of the active set; selection never classifies them again.
# Only .archive is still written. v3 selection also parked apoptotic rules in
# .last_gasp_queue for a sentinel that never ran (defense #4); rules already
# there stay parked until `aegis migrate` (wave B2) decides what to do with them.
PARKED_RULE_DIRS = frozenset({".archive", ".last_gasp_queue"})

_ARCHIVE_CANDIDATE_NOTE = "archive candidate: false positives exceed 2x true positives; left in place"


def run_cell_selection(workspace: Workspace | Path | str | None = None, execute: bool = False) -> int:
    """Selection pressure engine for Soma immune cells."""
    ws = workspace if isinstance(workspace, Workspace) else (
        Workspace(root=Path(workspace).resolve()) if workspace else Workspace.resolve()
    )
    cells_dir = ws.rules_dir
    archive_dir = cells_dir / ".archive"
    lifecycle_log = ws.layout.lifecycle_log

    if not cells_dir.exists():
        print("No cells directory found.")
        return 0

    print(f"Running cell selection (execute={execute})...")
    if execute:
        archive_dir.mkdir(parents=True, exist_ok=True)

    # The rule list is taken up front, so a rule parked during this pass is
    # not visited again.
    for fpath in _active_rule_files(cells_dir):
        content = _read_text(fpath)
        if content is None:
            continue
        verdict = _classify(content)
        if verdict is None:
            continue
        category, score, _meta, dormant = verdict
        note = f" {_ARCHIVE_CANDIDATE_NOTE}" if category == "APOPTOSIS" else ""
        print(f"[{category}] {fpath.name} (Score: {score:.2f}){note}")
        if not execute or _action_for(category, dormant) is None:
            continue

        # Classified unlocked, changed under the lock one rule at a time (as
        # the tier pass does): a pass over hundreds of rules must not starve
        # concurrent create/promote into LockTimeoutError.
        with locked(ws.root):
            action = _apply_locked(fpath, cells_dir, archive_dir)
            if action:
                append_jsonl(lifecycle_log, [{
                    "timestamp": _utc_timestamp(),
                    "cell": fpath.name,
                    "action": action,
                }])
    return 0


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _active_rule_files(cells_dir: Path) -> list[Path]:
    found: list[Path] = []
    for root_str, dirs, files in os.walk(cells_dir):
        dirs[:] = sorted(d for d in dirs if d not in PARKED_RULE_DIRS)
        found.extend(
            Path(root_str) / f for f in sorted(files) if f.endswith(".md") and f != "README.md"
        )
    return found


def _read_text(fpath: Path) -> Optional[str]:
    try:
        return fpath.read_text(encoding="utf-8")
    except Exception:
        return None


def _classify(content: str) -> Optional[tuple[str, float, dict, bool]]:
    """Return ``(category, score, metadata, already_dormant)``, or None if unparseable."""
    meta = parse_frontmatter(content)
    if not meta:
        return None
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
        return "DORMANT", 0.0, meta, dormant
    score = tp / triggers
    if fp > 0 and tp > 0 and fp > 2 * tp:
        category = "APOPTOSIS_WARNING" if cell_type in ("wall", "invariant") else "APOPTOSIS"
    elif score > 0.7:
        category = "SURVIVE"
    elif score >= EXTINCTION_THRESHOLD:
        category = "ADAPT"
    else:
        category = "EXTINCT"
    return category, score, meta, dormant


def _action_for(category: str, dormant: bool) -> Optional[str]:
    if category == "EXTINCT":
        return "moved_to_archive"
    if category == "DORMANT" and not dormant:
        return "marked_dormant"
    return None


def _apply_locked(fpath: Path, cells_dir: Path, archive_dir: Path) -> Optional[str]:
    """Re-read and re-classify ``fpath`` under the rules lock, then act on what is on disk.

    A rule moved or deleted since it was classified is skipped; one edited
    since is judged by its new content.
    """
    content = _read_text(fpath)
    if content is None:
        return None
    verdict = _classify(content)
    if verdict is None:
        return None
    category, _score, meta, dormant = verdict
    action = _action_for(category, dormant)
    if action == "moved_to_archive":
        _park(fpath, archive_dir)
    elif action == "marked_dormant":
        meta["dormant_since"] = _utc_timestamp()
        atomic_write_text(fpath, dump_frontmatter(meta, body=_get_body(content).lstrip()))
    return action


def _park(fpath: Path, dest_dir: Path) -> Path:
    """Move a rule into ``dest_dir`` without replacing a rule already parked there."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / fpath.name
    n = 1
    while os.path.lexists(dest):
        dest = dest_dir / f"{fpath.stem}.{n}{fpath.suffix}"
        n += 1
    shutil.move(str(fpath), str(dest))
    return dest


def prune_cells(workspace: Workspace | Path | str | None = None, execute: bool = False) -> int:
    """Evaluate and prune extinct or apoptotic rules."""
    return run_cell_selection(workspace=workspace, execute=execute)



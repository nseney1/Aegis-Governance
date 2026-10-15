"""Cell file parsing, validation, frontmatter transforms, and discovery."""
from __future__ import annotations

from datetime import datetime, timezone
import glob
import os
from pathlib import Path
import re
from typing import Any, Optional, Tuple

from aegis_core.yaml_engine.serializer import dump_frontmatter
from aegis_core.yaml_engine.frontmatter import parse_frontmatter, parse_rule_frontmatter
from aegis_core.workspace import literal_workspace
from aegis_core.workspace.base import Workspace
from .constants import (
    TYPE_TO_DIR,
)

__all__ = [
    "find_cell_file",
    "generate_slug",
    "sanitize_cell_id",
    "validate_cell_id",
]


def sanitize_cell_id(cell_id: str) -> Optional[str]:
    """Validate cell identifier to prevent path traversal."""
    if not cell_id or "/" in cell_id or "\\" in cell_id or ".." in cell_id:
        return None
    cleaned = cell_id.strip()
    if cleaned.endswith(".md"):
        cleaned = cleaned[:-3]
    return cleaned if cleaned else None


def validate_cell_id(cell_id: str | None) -> None:
    """Validate cell ID to prevent path traversal attacks."""
    if not cell_id:
        return
    if "/" in cell_id or "\\" in cell_id or ".." in cell_id:
        raise ValueError(f"Invalid ID_OVERRIDE contains path traversal characters: {cell_id!r}")


def generate_slug(hypothesis: str, id_override: str | None = None) -> str:
    """Generate safe cell slug identifier."""
    if id_override:
        validate_cell_id(id_override)
        return id_override

    cleaned = re.sub(r"[^a-zA-Z0-9 ]", "", hypothesis.lower())
    slug = re.sub(r"\s+", "-", cleaned).strip("-")[:50].rstrip("-")
    return slug or "unnamed-cell"


def find_cell_file(workspace: Workspace | Path | str, cell_id: str) -> Tuple[Optional[Path], Optional[str]]:
    """Locate a cell across .aegis/rules/ and rules/ or genome/ directories."""
    clean_id = sanitize_cell_id(cell_id)
    if not clean_id:
        return None, None

    ws = literal_workspace(workspace)
    candidate_dirs = [
        ws.rules_dir,
    ]
    rules_dir = (ws.root / "rules") if (ws.root / "rules").is_dir() else (ws.root / "genome")

    seen_dirs = set()
    for cells_dir in candidate_dirs:
        if cells_dir in seen_dirs or not cells_dir.is_dir():
            continue
        seen_dirs.add(cells_dir)
        for type_name, dir_name in TYPE_TO_DIR.items():
            candidate = cells_dir / dir_name / f"{clean_id}.md"
            if candidate.is_file():
                return candidate, type_name

    if ws.is_aegis_repo:
        candidate = rules_dir / f"{clean_id}.md"
        if candidate.is_file():
            return candidate, "genome"

    return None, None


def _naive_utc(timestamp: Any) -> Optional[datetime]:
    """Parse a canonical timestamp and normalize it to naive UTC."""
    if not isinstance(timestamp, str) or not timestamp:
        return None
    normalized = timestamp[:-1] + "+00:00" if timestamp.endswith("Z") else timestamp
    try:
        parsed = datetime.fromisoformat(normalized)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is not None:
        return parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def _load_evidence(workspace: Workspace | Path | str) -> dict[str, dict[str, Any]]:
    """Load lifecycle dimensions from the outcome ledger."""
    from aegis_core.telemetry_engine import ledger
    ws = literal_workspace(workspace)
    return {
        rule: {
            "triggers": totals["triggers"],
            "tp": totals["tp"],
            "fp": totals["fp"],
            "last_trigger_ts": _naive_utc(totals["last_ts"]),
            "has_triggers": totals["triggers"] > 0,
        }
        for rule, totals in ledger.aggregate(ws.root).items()
    }


def _load_cells(workspace: Workspace | Path | str) -> list[dict[str, Any]]:
    """Load cell metadata from .aegis/rules/**/*.md and rules/**/*.md files.

    Returns:
        List of cell metadata dicts with at minimum: id, type, created, source_path.
    """
    ws = literal_workspace(workspace)
    cells = []
    scan_roots = [str(ws.rules_dir)]
    if ws.is_aegis_repo:
        rules_root = (ws.root / "rules") if (ws.root / "rules").is_dir() else (ws.root / "genome")
        if str(rules_root) not in scan_roots:
            scan_roots.append(str(rules_root))

    seen_paths = set()
    for cells_root in scan_roots:
        if not os.path.isdir(cells_root):
            continue

        for md_path in glob.glob(os.path.join(cells_root, "**", "*.md"), recursive=True):
            real_md = os.path.abspath(md_path)
            if real_md in seen_paths or os.path.basename(md_path) == "README.md":
                continue
            seen_paths.add(real_md)
            try:
                with open(md_path, encoding="utf-8") as f:
                    content = f.read()
            except OSError:
                continue

            meta = parse_frontmatter(content)
            if not meta:
                continue

            cell_id = meta.get("id", os.path.splitext(os.path.basename(md_path))[0])
            cell_type = meta.get("type", "trap")
            created = meta.get("created", "")

            cells.append({
                "id": cell_id,
                "type": cell_type,
                "created": created,
                "source_path": md_path,
                "meta": meta,
            })

    return cells


def _cell_age_days(cell: dict) -> int:
    """Return cell age in days from its 'created' field."""
    created = cell.get("created", "")
    if not created:
        return 0
    try:
        if isinstance(created, str):
            created_dt = datetime.strptime(created, "%Y-%m-%d")
        else:
            created_dt = datetime.combine(created, datetime.min.time())
        return (datetime.now(timezone.utc).replace(tzinfo=None) - created_dt).days
    except (ValueError, TypeError):
        return 0


def _transform_frontmatter_type(content: str, new_type: str) -> str:
    """Update type field in cell frontmatter preserving body."""
    try:
        meta, body = parse_rule_frontmatter(content)
    except Exception:
        return content

    meta["type"] = new_type
    if new_type in ("wall", "gate", "invariant"):
        meta["enforcement"] = "gate"
    elif new_type == "trap":
        meta.pop("enforcement", None)
        meta.pop("enforcement_artifact", None)

    return dump_frontmatter(meta, body=body)



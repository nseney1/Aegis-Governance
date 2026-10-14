"""Cell file parsing, validation, frontmatter transforms, and discovery."""
from __future__ import annotations

from datetime import datetime, timezone
import glob
import os
from pathlib import Path
import re
import shutil
from typing import Any, Optional, Tuple

from aegis_core.somayaml import parse_frontmatter
from aegis_core.workspace import Workspace
from .constants import (
    TYPE_TO_DIR,
    VALID_TYPES,
)

__all__ = [
    "find_cell",
    "find_cell_file",
    "generate_slug",
    "get_type_plural",
    "parse_cell",
    "resolve_metrics_dir",
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
    """Locate a cell across vacuoles/, walls/, and genome/ directories."""
    clean_id = sanitize_cell_id(cell_id)
    if not clean_id:
        return None, None

    ws = workspace if isinstance(workspace, Workspace) else (
        Workspace(root=Path(workspace).resolve()) if workspace else Workspace.resolve()
    )
    cells_dir = ws.cells_dir
    genome_dir = ws.root / "genome"

    for type_name, dir_name in TYPE_TO_DIR.items():
        candidate = cells_dir / dir_name / f"{clean_id}.md"
        if candidate.is_file():
            return candidate, type_name

    if ws.is_soma_repo:
        candidate = genome_dir / f"{clean_id}.md"
        if candidate.is_file():
            return candidate, "genome"

    return None, None


def find_cell(workspace: Workspace | Path | str, cell_id: str) -> Optional[str]:
    ws = workspace if isinstance(workspace, Workspace) else (
        Workspace(root=Path(workspace).resolve()) if workspace else Workspace.resolve()
    )
    cells_dir = str(ws.cells_dir)
    matches = glob.glob(os.path.join(cells_dir, "**", f"*{cell_id}*"), recursive=True)
    matches = [m for m in matches if os.path.isfile(m) and m.endswith(".md")]
    return matches[0] if matches else None


def parse_cell(file_path: Path | str) -> tuple[Optional[dict], str]:
    try:
        content = Path(file_path).read_text(encoding="utf-8")
        meta = parse_frontmatter(content)
        end_idx = content.find("---", 3)
        body = content[end_idx + 3:].lstrip() if end_idx != -1 else ""
        return meta, body
    except Exception:
        return None, ""


def get_type_plural(cell_type: str) -> str:
    cell_type = cell_type.lower()
    return VALID_TYPES.get(cell_type, "vacuoles")


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
    """Load lifecycle dimensions from the canonical signal ledger."""
    from aegis_core.evidence import aggregate_signals
    ws = workspace if isinstance(workspace, Workspace) else (
        Workspace(root=Path(workspace).resolve()) if workspace else Workspace.resolve()
    )
    evidence_dir = str(ws.evidence_dir)
    aggregation = aggregate_signals(evidence_dir)
    return {
        cell_id: {
            "triggers": counts["triggers"],
            "tp": counts["tp"],
            "fp": counts["fp"],
            "last_trigger_ts": _naive_utc(counts["last_trigger"]),
            "has_triggers": counts["has_triggers"],
        }
        for cell_id, counts in aggregation.counts.items()
    }


def _load_cells(workspace: Workspace | Path | str) -> list[dict[str, Any]]:
    """Load cell metadata from .soma/cells/**/*.md and genome/**/*.md files.

    Returns:
        List of cell metadata dicts with at minimum: id, type, created, source_path.
    """
    ws = workspace if isinstance(workspace, Workspace) else (
        Workspace(root=Path(workspace).resolve()) if workspace else Workspace.resolve()
    )
    cells = []
    scan_roots = [str(ws.cells_dir)]
    if ws.is_soma_repo:
        scan_roots.append(str(ws.root / "genome"))

    for cells_root in scan_roots:
        if not os.path.isdir(cells_root):
            continue

        for md_path in glob.glob(os.path.join(cells_root, "**", "*.md"), recursive=True):
            if os.path.basename(md_path) == "README.md":
                continue
            try:
                with open(md_path, encoding="utf-8") as f:
                    content = f.read()
            except OSError:
                continue

            meta = parse_frontmatter(content)
            if not meta:
                continue

            cell_id = meta.get("id", os.path.splitext(os.path.basename(md_path))[0])
            cell_type = meta.get("type", "vacuole")
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
    """Update type field in cell frontmatter preserving body and comments."""
    content = content.lstrip("\ufeff")
    end_idx = content.find("---", 3)
    if end_idx == -1:
        return content

    frontmatter = content[3:end_idx]
    body = content[end_idx:]

    lines = frontmatter.splitlines()
    new_lines = []
    type_updated = False
    enforcement_updated = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("type:"):
            indent = line[:len(line) - len(line.lstrip())]
            new_lines.append(f"{indent}type: {new_type}")
            type_updated = True
        elif stripped.startswith("enforcement:"):
            if new_type in ("wall", "gate"):
                indent = line[:len(line) - len(line.lstrip())]
                new_lines.append(f"{indent}enforcement: gate")
                enforcement_updated = True
            elif new_type == "vacuole":
                pass
            else:
                new_lines.append(line)
        elif stripped.startswith("enforcement_artifact:"):
            if new_type == "vacuole":
                pass
            else:
                new_lines.append(line)
        else:
            new_lines.append(line)

    if not type_updated:
        new_lines.append(f"type: {new_type}")

    if new_type in ("wall", "gate") and not enforcement_updated:
        new_lines.append("enforcement: gate")

    return "---\n" + "\n".join(new_lines).strip() + "\n" + body


def _atomic_write_and_unlink(
    source_path: Path,
    target_path: Path,
    new_content: str,
) -> None:
    """Write new_content to target_path atomically and unlink source_path with rollback."""
    target_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_target = target_path.with_name(f"{target_path.name}.tmp.{os.getpid()}")
    try:
        with open(tmp_target, "w", encoding="utf-8") as fh:
            fh.write(new_content)
            fh.flush()
            os.fsync(fh.fileno())
        try:
            os.replace(tmp_target, target_path)
        except OSError:
            shutil.move(str(tmp_target), str(target_path))
        try:
            if source_path != target_path and source_path.exists():
                source_path.unlink()
        except Exception:
            if target_path.exists() and source_path.exists():
                try:
                    os.remove(target_path)
                except Exception as ex:
                    raise RuntimeError(f"Rollback failed: duplicate cell remains at {target_path}") from ex
            raise
    except Exception:
        if tmp_target.exists():
            try:
                os.remove(tmp_target)
            except OSError:
                pass
        raise


def resolve_metrics_dir(workspace: Path | str) -> Path:
    from aegis_core.telemetry import resolve_metrics_dir as _res_metrics
    return _res_metrics(workspace)

"""aegis_core.quarantine — Self-healing quarantine for corrupted governance state.

Automatically isolates damaged YAML cells or unparseable JSONL files to prevent
fatal crashes, logging diagnostic telemetry and preserving system uptime.
"""
from __future__ import annotations

import json
import os
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Tuple

from aegis_core.yaml import _get_body, parse_frontmatter
from aegis_core.storage import atomic_write_text

QUARANTINE_DIR = "quarantine"
QUARANTINE_LOG = "quarantine_log.jsonl"


def _resolve_workspace(file_path: Path, workspace: Optional[Path | str] = None) -> Path:
    if workspace:
        return Path(workspace).resolve()
    from aegis_core.workspace import Workspace
    try:
        return Workspace.resolve(file_path.parent).root
    except Exception:
        return file_path.resolve().parent


def _resolve_quarantine_dir(ws: Path) -> Path:
    if (ws / ".aegis").is_dir() or not (ws / ".soma").is_dir():
        return ws / ".aegis" / QUARANTINE_DIR
    return ws / ".soma" / QUARANTINE_DIR


def quarantine_file(
    file_path: Path,
    reason: str,
    workspace: Optional[Path | str] = None,
) -> Path:
    """Isolate a damaged file into .aegis/quarantine/ (or .soma/quarantine/) and record diagnostics.

    Returns:
        The new quarantined file path.
    """
    path = Path(file_path).resolve()
    ws = _resolve_workspace(path, workspace)
    q_dir = _resolve_quarantine_dir(ws)
    q_dir.mkdir(parents=True, exist_ok=True)

    timestamp = int(time.time())
    dest_name = f"{path.stem}.{timestamp}.corrupt"
    dest_path = q_dir / dest_name

    # Copy / move file into quarantine
    shutil.copy2(str(path), str(dest_path))
    try:
        path.unlink()
    except OSError:
        pass

    # Log structured incident entry
    log_file = q_dir / QUARANTINE_LOG
    log_entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "original_path": str(path),
        "quarantined_file": dest_name,
        "reason": str(reason),
    }
    with open(log_file, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(log_entry) + "\n")

    return dest_path


def safe_parse_cell_file(
    cell_path: Path,
    workspace: Optional[Path | str] = None,
) -> Tuple[dict[str, Any], str, str]:
    """Parse cell frontmatter and body, automatically quarantining corrupt files.

    Returns:
        (metadata, body, status) where status is 'ok', 'quarantined', or 'missing'.
    """
    path = Path(cell_path)
    if not path.exists():
        return {}, "", "missing"

    try:
        content = path.read_text(encoding="utf-8-sig")
        metadata = parse_frontmatter(content)
        if metadata is None:
            quarantine_file(path, reason="unparseable_or_unclosed_frontmatter", workspace=workspace)
            return {}, "", "quarantined"
        body = _get_body(content).strip()
        return metadata, body, "ok"
    except Exception as exc:
        quarantine_file(path, reason=f"frontmatter_parse_error: {exc}", workspace=workspace)
        return {}, "", "quarantined"


def safe_read_jsonl(
    file_path: Path,
    workspace: Optional[Path | str] = None,
) -> Tuple[list[dict[str, Any]], str]:
    """Read a JSONL file, automatically quarantining files with severe corruption.

    Returns:
        (records, status) where status is 'ok', 'quarantined', or 'missing'.
    """
    path = Path(file_path)
    if not path.exists():
        return [], "missing"

    records = []
    has_valid_json = False
    invalid_lines = 0

    try:
        content = path.read_text(encoding="utf-8-sig")
        lines = content.splitlines()
        for idx, line in enumerate(lines):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
                has_valid_json = True
            except json.JSONDecodeError:
                invalid_lines += 1
    except (UnicodeDecodeError, Exception) as exc:
        quarantine_file(path, reason=f"unreadable_binary: {exc}", workspace=workspace)
        return [], "quarantined"

    # If file had invalid/non-empty content but zero valid JSON entries, quarantine it
    if invalid_lines > 0 and not has_valid_json:
        quarantine_file(path, reason="corrupted_non_jsonl", workspace=workspace)
        return [], "quarantined"

    return records, "ok"


def _extract_timestamp(filename: str, log_ts_str: Optional[str] = None, fallback_mtime: float = 0.0) -> Tuple[int, str]:
    """Extract unix timestamp and ISO-8601 string from filename, log entry, or mtime."""
    import re
    # Check filename pattern <stem>.<timestamp>.corrupt
    m = re.search(r"\.(\d+)\.corrupt$", filename)
    if m:
        digits = m.group(1)
        if len(digits) >= 9:
            try:
                val = int(digits)
                if len(digits) in (12, 13) or val > 100_000_000_000:
                    val //= 1000
                if 946684800 <= val <= 4102444800:
                    iso_str = datetime.fromtimestamp(val, tz=timezone.utc).isoformat()
                    return val, iso_str
            except (OverflowError, ValueError, OSError):
                pass
    if log_ts_str:
        try:
            dt = datetime.fromisoformat(log_ts_str.replace("Z", "+00:00"))
            return int(dt.timestamp()), log_ts_str
        except Exception:
            pass
    ts = int(fallback_mtime or time.time())
    iso_str = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
    return ts, iso_str


def list_quarantine(workspace: Optional[Path | str] = None) -> list[dict[str, Any]]:
    """List all quarantined files with reasons, timestamps, and sizes."""
    ws = Path(workspace).resolve() if workspace else Path.cwd()
    q_dir = _resolve_quarantine_dir(ws)
    if not q_dir.exists():
        return []

    # Read log entries
    log_map: dict[str, dict[str, Any]] = {}
    log_file = q_dir / QUARANTINE_LOG
    if log_file.exists():
        try:
            for line in log_file.read_text(encoding="utf-8-sig").splitlines():
                if line.strip():
                    entry = json.loads(line)
                    fn = entry.get("quarantined_file")
                    if fn:
                        log_map[fn] = entry
        except Exception:
            pass

    items = []
    for f in q_dir.glob("*.corrupt"):
        stat = f.stat()
        log_entry = log_map.get(f.name, {})
        ts, iso_ts = _extract_timestamp(f.name, log_entry.get("timestamp"), stat.st_mtime)
        items.append({
            "filename": f.name,
            "path": str(f),
            "size_bytes": stat.st_size,
            "timestamp": iso_ts,
            "_unix_timestamp": ts,
            "reason": log_entry.get("reason", "Corrupted state isolated by quarantine"),
            "original_path": log_entry.get("original_path", ""),
        })

    items.sort(key=lambda x: x["_unix_timestamp"], reverse=True)
    return items


def inspect_quarantined_file(filename_or_path: str, workspace: Optional[Path | str] = None) -> Optional[dict[str, Any]]:
    """Inspect a quarantined file and return preview content and diagnostics."""
    ws = Path(workspace).resolve() if workspace else Path.cwd()
    q_dir = _resolve_quarantine_dir(ws)
    target_name = Path(filename_or_path).name
    target_file = q_dir / target_name
    if not target_file.exists():
        return None

    items = list_quarantine(workspace=ws)
    info = next((i for i in items if i["filename"] == target_name), None)
    if not info:
        stat = target_file.stat()
        ts, iso_ts = _extract_timestamp(target_name, fallback_mtime=stat.st_mtime)
        info = {
            "filename": target_name,
            "path": str(target_file),
            "size_bytes": stat.st_size,
            "timestamp": iso_ts,
            "reason": "Corrupted state isolated by quarantine",
            "original_path": "",
        }

    try:
        preview = target_file.read_text(encoding="utf-8-sig", errors="replace")[:2000]
    except Exception as exc:
        preview = f"<unreadable content: {exc}>"

    result = dict(info)
    result["preview"] = preview
    return result


def prune_quarantine(older_than_days: int = 30, workspace: Optional[Path | str] = None) -> int:
    """Prune quarantined files older than specified days and update log.

    Returns the number of deleted files.
    """
    ws = Path(workspace).resolve() if workspace else Path.cwd()
    q_dir = _resolve_quarantine_dir(ws)
    if not q_dir.exists():
        return 0

    cutoff_ts = int(time.time()) - (older_than_days * 86400)
    items = list_quarantine(workspace=ws)

    deleted_names = set()
    for item in items:
        if item.get("_unix_timestamp", 0) <= cutoff_ts:
            f = Path(item["path"])
            try:
                if f.exists():
                    f.unlink()
                deleted_names.add(item["filename"])
            except OSError:
                pass

    if deleted_names:
        log_file = q_dir / QUARANTINE_LOG
        if log_file.exists():
            try:
                lines = log_file.read_text(encoding="utf-8-sig").splitlines()
                kept = []
                for line in lines:
                    if line.strip():
                        entry = json.loads(line)
                        if entry.get("quarantined_file") not in deleted_names:
                            kept.append(line)
                atomic_write_text(log_file, "\n".join(kept) + ("\n" if kept else ""))
            except Exception:
                pass

    return len(deleted_names)


__all__ = [
    "QUARANTINE_DIR",
    "QUARANTINE_LOG",
    "inspect_quarantined_file",
    "list_quarantine",
    "prune_quarantine",
    "quarantine_file",
    "safe_parse_cell_file",
    "safe_read_jsonl",
]


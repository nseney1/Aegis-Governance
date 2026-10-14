"""Human developer insight reading, signals, and atomic cursor persistence."""
from __future__ import annotations

import glob
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
from typing import Optional

from aegis_core.yaml import parse_frontmatter, parse_yaml_subset
from aegis_core.workspace import Workspace, as_workspace

__all__ = ["commit_insight_cursor", "capture_human_insight_signals", "read_human_insight_signals"]


def _insight_cursor_path(workspace: Workspace | Path | str) -> str:
    ws = as_workspace(workspace)
    return str(ws.aegis_dir / "insight_cursor")


def _read_insight_cursor(workspace: Workspace | Path | str) -> int:
    """Return the committed byte offset into human_insights.jsonl (0 if none/invalid)."""
    try:
        with open(_insight_cursor_path(workspace), "r", encoding="utf-8") as cf:
            value = int(cf.read().strip())
    except (OSError, ValueError):
        return 0
    return value if value >= 0 else 0


def commit_insight_cursor(workspace: Workspace | Path | str, offset: Optional[int]) -> bool:
    """Atomically persist the insight cursor (temp file + os.replace)."""
    if offset is None:
        return True
    cursor_file = _insight_cursor_path(workspace)
    if os.path.isfile(cursor_file) and _read_insight_cursor(workspace) == offset:
        return True
    cursor_dir = os.path.dirname(cursor_file)
    tmp_path = None
    try:
        os.makedirs(cursor_dir, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=cursor_dir, prefix=".insight_cursor.", suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as cf:
            cf.write(str(int(offset)))
            cf.flush()
            os.fsync(cf.fileno())
        os.replace(tmp_path, cursor_file)
        return True
    except (OSError, ValueError, TypeError) as e:
        print(f"    ! failed to commit insight cursor: {e}", file=sys.stderr)
        if tmp_path is not None:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
        return False


def capture_human_insight_signals(workspace: Workspace | Path | str) -> list[dict]:
    """Backward-compatible wrapper: read NEW insights and commit the cursor."""
    signals, new_offset = read_human_insight_signals(workspace)
    commit_insight_cursor(workspace, new_offset)
    return signals


def read_human_insight_signals(workspace: Workspace | Path | str) -> tuple[list[dict], int]:
    """Read NEW human insight annotations and produce fitness signals."""
    ws = as_workspace(workspace)
    insights_file = str(ws.aegis_dir / "human_insights.jsonl")
    cursor_offset = _read_insight_cursor(ws)
    if not os.path.isfile(insights_file):
        return [], cursor_offset

    file_size = os.path.getsize(insights_file)
    if cursor_offset > file_size:
        cursor_offset = 0

    weight = 0.5
    config_path = str(ws.aegis_dir / "config.yaml")
    if os.path.isfile(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                content = f.read()
                config = parse_frontmatter(content) if content.startswith("---") else parse_yaml_subset(content)
                config = config or {}
            weight = float(config.get("insight_signal_weight", 0.5))
        except Exception:
            pass

    cell_paths = {}
    cells_dir = ws.rules_dir
    if cells_dir.is_dir():
        for cell_file in glob.glob(os.path.join(str(cells_dir), "**", "*.md"), recursive=True):
            name = os.path.splitext(os.path.basename(cell_file))[0]
            cell_paths[name] = cell_file

    try:
        with open(insights_file, "rb") as f:
            f.seek(cursor_offset)
            data = f.read()
    except OSError:
        return [], cursor_offset

    last_newline = data.rfind(b"\n")
    if last_newline == -1:
        return [], cursor_offset

    complete = data[: last_newline + 1]
    new_offset = cursor_offset + len(complete)

    signals = []
    line_offset = cursor_offset
    for raw_line in complete.split(b"\n"):
        this_offset = line_offset
        line_offset += len(raw_line) + 1
        if not raw_line.strip():
            continue
        try:
            record = json.loads(raw_line.decode("utf-8", errors="surrogatepass"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
        if not isinstance(record, dict):
            continue

        insight_id = f"{this_offset}:{hashlib.sha256(raw_line).hexdigest()}"

        if record.get("was_covered"):
            for cell_name in record.get("covering_cells", []):
                cell_path = cell_paths.get(cell_name)
                if cell_path:
                    signals.append({
                        "cell": cell_name,
                        "_path": cell_path,
                        "signal": weight,
                        "reasons": [f"human insight: {record.get('insight', '')[:80]}"],
                        "verified": True,
                        "signal_type": "human_insight",
                        "insight_id": insight_id,
                        "weight": weight,
                        "files": record.get("context_files", []),
                    })
        else:
            signals.append({
                "cell": None,
                "_path": None,
                "signal": 0.0,
                "reasons": [f"blind spot: {record.get('insight', '')[:80]}"],
                "verified": True,
                "signal_type": "blind_spot",
                "weight": weight,
                "files": record.get("context_files", []),
            })

    return signals, new_offset

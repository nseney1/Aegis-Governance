"""Zero-dependency YAML frontmatter serializer."""
from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

from aegis_core.yaml_engine.parser import (
    _BOOL_FALSE,
    _BOOL_TRUE,
    _FLOAT_RE,
    _INT_RE,
    _NULL_VALUES,
)


def _format_scalar(val: object) -> str:
    if val is None:
        return "null"
    if isinstance(val, bool):
        return "true" if val else "false"
    if isinstance(val, (int, float)):
        return str(val)
    if isinstance(val, (datetime, date)):
        return val.isoformat()
    s = str(val)
    if (
        not s
        or any(c in s for c in ":#{}[]|>&*!%@`,\n\"'")
        or "---" in s
        or s.strip() != s
        or s.lower() in _BOOL_TRUE
        or s.lower() in _BOOL_FALSE
        or s.lower() in _NULL_VALUES
        or _INT_RE.match(s)
        or _FLOAT_RE.match(s)
    ):
        escaped = s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
        return f'"{escaped}"'
    return s


def _dump_lines(d: Mapping[str, Any], indent: int = 0) -> List[str]:
    lines: List[str] = []
    prefix = " " * indent
    for k, v in d.items():
        key_str = str(k)
        if isinstance(v, (dict, Mapping)):
            if not v:
                lines.append(f"{prefix}{key_str}: {{}}")
            else:
                lines.append(f"{prefix}{key_str}:")
                lines.extend(_dump_lines(v, indent + 2))
        elif isinstance(v, (list, tuple, set)):
            if not v:
                lines.append(f"{prefix}{key_str}: []")
            else:
                lines.append(f"{prefix}{key_str}:")
                for item in v:
                    if isinstance(item, (dict, Mapping)):
                        lines.append(f"{prefix}  -")
                        lines.extend(_dump_lines(item, indent + 4))
                    else:
                        lines.append(f"{prefix}  - {_format_scalar(item)}")
        else:
            lines.append(f"{prefix}{key_str}: {_format_scalar(v)}")
    return lines


def dump_frontmatter(data: Mapping[str, Any] | Dict[str, Any], body: Optional[str] = None) -> str:
    """Serialize metadata dictionary to YAML frontmatter string without requiring PyYAML."""
    dict_data = dict(data)
    yaml_text = "\n".join(_dump_lines(dict_data)) + "\n"
    if body is not None:
        return f"---\n{yaml_text}---\n{body}"
    return yaml_text


def write_frontmatter(target_path: str | Path, metadata: Dict[str, Any], body: str) -> None:
    """Write metadata and markdown body to target_path with frontmatter delimiters."""
    content = dump_frontmatter(metadata, body=body)
    Path(target_path).write_text(content, encoding="utf-8")


__all__ = [
    "_dump_lines",
    "_format_scalar",
    "dump_frontmatter",
    "write_frontmatter",
]

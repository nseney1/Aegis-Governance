"""Opt-in response projection engine for MCP gateway with SOMA-V01 security guards."""
from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Set

# SOMA-V01 Denylist: Raw prompts, plans, and Python introspection symbols are strictly forbidden
DENYLIST: frozenset[str] = frozenset({
    "task_plan",
    "prompt",
    "raw_prompt",
    "__class__",
    "__mro__",
    "__globals__",
    "__subclasses__",
    "__builtins__",
    "__dict__",
    "__doc__",
})

SUMMARY_FIELDS: frozenset[str] = frozenset({
    "id",
    "name",
    "type",
    "tier",
    "category",
    "status",
    "verdict",
    "passed",
    "failed",
    "skipped",
    "score",
    "total",
    "count",
    "summary",
    "violations_found",
    "tree_hash",
    "timestamp",
    "error",
    "warning",
    "risk_level",
    "ticket_id",
})


def _is_denied(key: str) -> bool:
    """Check if key or any path component matches the SOMA-V01 denylist."""
    parts = key.split(".")
    return any(p.strip().lower() in DENYLIST for p in parts)


def _get_nested(obj: Any, path_parts: Sequence[str]) -> Any:
    """Zero-dependency nested dictionary lookup without eval or getattr."""
    curr = obj
    for part in path_parts:
        if isinstance(curr, Mapping):
            if part in curr:
                curr = curr[part]
            else:
                return None
        elif isinstance(curr, list):
            try:
                idx = int(part)
                if 0 <= idx < len(curr):
                    curr = curr[idx]
                else:
                    return None
            except ValueError:
                return None
        else:
            return None
    return curr


def _set_nested(target: Dict[str, Any], path_parts: Sequence[str], value: Any) -> None:
    """Set value into nested dictionary structure along path_parts."""
    curr = target
    for i, part in enumerate(path_parts[:-1]):
        if part not in curr or not isinstance(curr[part], dict):
            curr[part] = {}
        curr = curr[part]
    curr[path_parts[-1]] = value


def _sanitize_data(data: Any) -> Any:
    """Recursively scrub any denylisted keys from returned payloads."""
    if isinstance(data, Mapping):
        return {
            k: _sanitize_data(v)
            for k, v in data.items()
            if not _is_denied(str(k))
        }
    elif isinstance(data, list):
        return [_sanitize_data(item) for item in data]
    return data


def project_response(
    data: Any,
    view: Optional[str] = "full",
    fields: Optional[Sequence[str]] = None,
) -> Any:
    """Project MCP tool response according to client token optimization preferences.

    - view="full" (default): Returns full sanitized response.
    - view="ids": Returns list of IDs or key identifier mappings.
    - view="summary": Returns compact summary dictionary omitting bulky instruction texts.
    - fields=[...]: Sparse projection containing only requested dot-separated field paths.
    """
    sanitized = _sanitize_data(data)

    # 1. Custom field projection takes precedence
    if fields:
        valid_paths = [f.strip() for f in fields if f.strip() and not _is_denied(f.strip())]
        if not valid_paths:
            return {}

        if isinstance(sanitized, list):
            projected_list: List[Any] = []
            for item in sanitized:
                if isinstance(item, Mapping):
                    proj_item: Dict[str, Any] = {}
                    for field_path in valid_paths:
                        parts = field_path.split(".")
                        val = _get_nested(item, parts)
                        if val is not None:
                            _set_nested(proj_item, parts, val)
                    projected_list.append(proj_item)
                else:
                    projected_list.append(item)
            return projected_list
        elif isinstance(sanitized, Mapping):
            proj_dict: Dict[str, Any] = {}
            for field_path in valid_paths:
                parts = field_path.split(".")
                val = _get_nested(sanitized, parts)
                if val is not None:
                    _set_nested(proj_dict, parts, val)
            return proj_dict
        return sanitized

    view_norm = (view or "full").strip().lower()

    # 2. Full view (strict backwards-compatibility)
    if view_norm == "full":
        return sanitized

    # 3. IDs view
    if view_norm == "ids":
        if isinstance(sanitized, list):
            return [
                item.get("id") or item.get("name") or str(item)
                for item in sanitized
                if isinstance(item, Mapping)
            ]
        elif isinstance(sanitized, Mapping):
            # Check for common list containers
            for container in ("cells", "rules", "skills", "items", "results", "signals", "entries"):
                if container in sanitized and isinstance(sanitized[container], list):
                    return {
                        container: [
                            item.get("id") or item.get("name") or str(item)
                            for item in sanitized[container]
                            if isinstance(item, Mapping)
                        ]
                    }
            if "id" in sanitized:
                return {"id": sanitized["id"]}
            return {"keys": list(sanitized.keys())}
        return sanitized

    # 4. Summary view
    if view_norm == "summary":
        if isinstance(sanitized, list):
            summary_list: List[Any] = []
            for item in sanitized:
                if isinstance(item, Mapping):
                    summary_list.append({
                        k: v for k, v in item.items() if k in SUMMARY_FIELDS
                    })
                else:
                    summary_list.append(item)
            return summary_list
        elif isinstance(sanitized, Mapping):
            summary_dict: Dict[str, Any] = {}
            for k, v in sanitized.items():
                if k in SUMMARY_FIELDS:
                    summary_dict[k] = v
                elif isinstance(v, list):
                    # Summarize list containers to their count and lightweight items
                    summary_dict[f"{k}_count"] = len(v)
                    if v and isinstance(v[0], Mapping):
                        summary_dict[k] = [
                            {ik: iv for ik, iv in elem.items() if ik in SUMMARY_FIELDS}
                            for elem in v[:10]  # Cap summary lists to top 10
                        ]
            return summary_dict

    # Fallback to full sanitized
    return sanitized

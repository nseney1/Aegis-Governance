"""Opt-in response projection engine for MCP gateway with SOMA-V01 security guards."""
from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional

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
})


def _is_denied(key: str) -> bool:
    """Check if key or any path component matches the SOMA-V01 denylist."""
    parts = key.split(".")
    return any(p.strip().lower() in DENYLIST for p in parts)


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


def project_response(data: Any, view: Optional[str] = "full") -> Any:
    """Project MCP tool response according to client token optimization preferences.

    - view="full" (default): Returns full sanitized response.
    - view="ids": Returns list of IDs or key identifier mappings.
    - view="summary": Returns compact summary dictionary omitting bulky instruction texts.
    """
    sanitized = _sanitize_data(data)

    view_norm = (view or "full").strip().lower()

    # Full view
    if view_norm == "full":
        return sanitized

    # IDs view
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

    # Summary view
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

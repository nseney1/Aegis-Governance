"""Opt-in projection of a tool response: full (default), summary or ids."""
from __future__ import annotations

from typing import Any, Mapping, Optional

# The first of these names a rule: its file stem (`_name`, from aegis_list_rules) is
# what aegis_report_outcome accepts, so it wins over a frontmatter `name` or `id`.
_IDENTITY_KEYS = ("_name", "name", "rule_id", "id")

SUMMARY_FIELDS: frozenset[str] = frozenset({
    "_name",
    "name",
    "rule_id",
    "id",
    "type",
    "enforcement",
    "tier",
    "status",
    "fitness",
    "rules_staged",
})
_SUMMARY_LIST_CAP = 10


def is_error_result(result: Any) -> bool:
    """A handler reports failure as {"status": "FAIL", "error": ...}."""
    return isinstance(result, Mapping) and ("error" in result or result.get("status") == "FAIL")


def _identity(item: Mapping) -> Optional[str]:
    for key in _IDENTITY_KEYS:
        value = item.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _ids(data: Any) -> Any:
    if isinstance(data, list):
        # An item with no identity is dropped, never stringified: that would dump its body.
        names = (_identity(item) if isinstance(item, Mapping) else item for item in data)
        return [name for name in names if name is not None]
    if isinstance(data, Mapping):
        return {key: _ids(value) for key, value in data.items() if isinstance(value, list)}
    return data


def _summary_item(item: Any) -> Any:
    if isinstance(item, Mapping):
        return {key: value for key, value in item.items() if key in SUMMARY_FIELDS}
    return item


def _summary(data: Any) -> Any:
    if isinstance(data, list):
        return [_summary_item(item) for item in data]
    if isinstance(data, Mapping):
        summary: dict[str, Any] = {}
        for key, value in data.items():
            if isinstance(value, list):
                summary[f"{key}_count"] = len(value)
                summary[key] = [_summary_item(item) for item in value[:_SUMMARY_LIST_CAP]]
            elif key in SUMMARY_FIELDS:
                summary[key] = value
        return summary
    return data


def project_response(data: Any, view: Optional[str] = "full") -> Any:
    """Project a tool response for a client that asked for less than the full payload.

    - ids: the rule names in each list of the response;
    - summary: identity, type, status and fitness of each item, lists capped at 10;
    - full (or anything else): the response unchanged.

    An error result is always returned whole, so the host still sees it as an error.
    """
    if is_error_result(data):
        return data
    view_norm = (view or "full").strip().lower()
    if view_norm == "ids":
        return _ids(data)
    if view_norm == "summary":
        return _summary(data)
    return data

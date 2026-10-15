"""``aegis sync``: the one writer of derived state (ADR 0005 AD-1, D1, D3).

Under the one workspace lock, sync loads the rules and the ledger and writes
``.aegis/state/derived.json``::

    {"v": 1, "norm": "lf", "synced_at": "...",
     "rules": {"<id>": {"path", "sha256", "type", "fitness", "triggers", "tp", "fp",
                        "last_ts", "suggestion"}},
     "errors": [{"path", "error"}], "ignored": [{"path", "reason"}],
     "untargeted": [{"id", "path"}],
     "ledger": {"skipped_lines", "unusable_rows", "error", "torn_tail"}}

``suggestion`` is promote, demote, archive or null (``lifecycle.promotion.suggest``).
sync only suggests; ``sync(..., apply=True)`` (``aegis sync --apply``) applies the
suggestions through the lifecycle functions, then rebuilds the view. Nothing else runs
the lifecycle. ``untargeted`` names served rules that apply to no file (no
target_paths). ``ledger`` is what the ledger read could not use: when it hides evidence
(``ledger.incomplete``), fitness and suggestions are partial and applying is refused.

``sha256`` is the LF-normalized digest of each rule file. It is not a signature (rules
are protected by git review and CI, not by Aegis): it only lets scan, list and status
say which rules were edited since the last sync. It never excludes a rule.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from aegis_core.fitness import for_rules
from aegis_core.rules import RuleSet, load_rules
from aegis_core.storage import atomic_write_text, locked, state_dir
from aegis_core.telemetry_engine import ledger
from aegis_core.workspace import literal_workspace
from aegis_core.workspace.layout import WorkspaceLayout

__all__ = ["DERIVED_VERSION", "SyncResult", "build", "read_derived", "stale_rules", "sync"]

DERIVED_VERSION = 1


def _now_iso(now: Optional[datetime]) -> str:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build(
    workspace: Any, ruleset: Optional[RuleSet] = None, now: Optional[datetime] = None, view: Any = None,
) -> Dict[str, Any]:
    """The derived document for ``workspace`` (written by ``sync``); ``view`` is the
    ledger read to use (default: read it now)."""
    from aegis_core.lifecycle.promotion import suggest

    rules = ruleset if ruleset is not None else load_rules(workspace)
    view = view if view is not None else ledger.read(workspace)
    loaded = [r for r in rules.rules if r.ok]
    fits = for_rules(workspace, loaded, now, view=view)
    entries: Dict[str, Any] = {}
    for rule in loaded:
        fit = fits[rule.id]
        entries[rule.id] = {
            "path": rule.path,
            "sha256": rule.digest,
            "type": rule.type,
            "fitness": fit.score,
            "triggers": fit.triggers,
            "tp": fit.tp,
            "fp": fit.fp,
            "last_ts": fit.last_ts,
            "suggestion": suggest(rule, fit, now),
        }
        if rule.expired:
            entries[rule.id]["expired"] = True
    return {
        "v": DERIVED_VERSION,
        "norm": "lf",
        "synced_at": _now_iso(now),
        "rules": entries,
        "errors": [{"path": r.path, "error": r.error} for r in rules.errors],
        "ignored": [{"path": i.path, "reason": i.reason} for i in rules.ignored],
        "untargeted": [{"id": r.id, "path": r.path} for r in sorted(rules.served, key=lambda r: r.id) if not r.target_paths],
        "ledger": view.health(),
    }


def read_derived(workspace: Any) -> Optional[Dict[str, Any]]:
    """The last derived document, or None when there is none or it cannot be used."""
    path = WorkspaceLayout(Path(literal_workspace(workspace).root)).derived_file
    try:
        if path.is_symlink() or not path.is_file():
            return None
        doc = json.loads(path.read_bytes().decode("utf-8"))
    except (OSError, UnicodeDecodeError, ValueError, RecursionError):
        return None
    if not isinstance(doc, dict) or doc.get("v") != DERIVED_VERSION or not isinstance(doc.get("rules"), dict):
        return None
    return doc


def stale_rules(ruleset: RuleSet, derived: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Rules edited, added or removed since the last sync: ``[{id, path, change}]``.

    ``change`` is ``edited`` (the LF-normalized digest or the path differs), ``new``,
    ``unloadable`` (its file is still there but no longer loads; ``error`` says why) or
    ``removed``. Without a derived document there is nothing to compare: ``[]``.
    """
    if derived is None:
        return []
    recorded = derived.get("rules") or {}
    out: List[Dict[str, Any]] = []
    current = set()
    broken: Dict[str, Any] = {}
    for rule in ruleset.rules:
        if not rule.ok:
            broken.setdefault(rule.id, rule)
            continue
        current.add(rule.id)
        entry = recorded.get(rule.id)
        if not isinstance(entry, dict):
            out.append({"id": rule.id, "path": rule.path, "change": "new"})
        elif entry.get("path") != rule.path or entry.get("sha256") != rule.digest:
            out.append({"id": rule.id, "path": rule.path, "change": "edited"})
    for rule_id in sorted(set(recorded) - current):
        if rule_id in broken:
            rule = broken[rule_id]
            out.append({"id": rule_id, "path": rule.path, "change": "unloadable", "error": rule.error})
            continue
        entry = recorded[rule_id]
        path = entry.get("path") if isinstance(entry, dict) else None
        out.append({"id": rule_id, "path": path, "change": "removed"})
    return out


@dataclass
class SyncResult:
    derived: Dict[str, Any]
    path: Path
    applied: List[Dict[str, Any]] = field(default_factory=list)
    refused: Optional[str] = None


def _apply(workspace: Any, derived: Dict[str, Any]) -> List[Dict[str, Any]]:
    from aegis_core.lifecycle.promotion import demote_cell, promote_cell
    from aegis_core.lifecycle.selection import archive_rule

    actions = {
        "promote": lambda rid: promote_cell(workspace, rid, force=True),
        "demote": lambda rid: demote_cell(workspace, rid),
        "archive": lambda rid: archive_rule(workspace, rid),
    }
    applied = []
    for rule_id, entry in sorted(derived["rules"].items()):
        action = entry.get("suggestion")
        if action not in actions:
            continue
        result = actions[action](rule_id)
        record = {"rule": rule_id, "action": action, "status": result.get("status")}
        for key in ("from_type", "to_type", "target_path", "message"):
            if result.get(key) is not None:
                record[key] = result[key]
        applied.append(record)
    return applied


def sync(workspace: Any, apply: bool = False, now: Optional[datetime] = None) -> SyncResult:
    """Rebuild ``.aegis/state/derived.json`` under the workspace lock.

    With ``apply``, every suggestion is applied (promote, demote or archive), then the
    view is rebuilt. Applying is refused, and nothing moves, while any rule file cannot
    be loaded or the ledger is incomplete: the suggestions would be computed over an
    incomplete rule set or over partial evidence.
    """
    ws = literal_workspace(workspace)
    path = WorkspaceLayout(ws.root).derived_file
    with locked(ws.root):
        ruleset = load_rules(ws)
        derived = build(ws, ruleset, now, ledger.read(ws))
        missing = ledger.incomplete(derived["ledger"])
        applied: List[Dict[str, Any]] = []
        refused = None
        if apply and ruleset.errors:
            refused = "not applied: rule files cannot be loaded: " + ", ".join(r.path for r in ruleset.errors)
        elif apply and missing:
            refused = (
                f"not applied: the ledger is incomplete ({missing}); "
                "fitness and suggestions are computed over partial evidence"
            )
        elif apply:
            applied = _apply(ws, derived)
            if applied:
                derived = build(ws, load_rules(ws), now)
        state_dir(ws.root)
        atomic_write_text(path, json.dumps(derived, indent=2, sort_keys=True) + "\n")
    return SyncResult(derived=derived, path=path, applied=applied, refused=refused)

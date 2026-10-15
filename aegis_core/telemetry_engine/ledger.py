"""The outcome ledger, ``.aegis/state/ledger.jsonl`` (build-sheet D13, ADR 0005 AD-1/AD-5).

The ledger is append-only and the only source of rule fitness. Every row is versioned::

    {"v": 2, "seq": 7, "ts": "2026-10-15T12:00:00Z", "rule": "trap-x", "outcome": "tp",
     "source": "mcp", "host": "claude-code", "session": "…", "key": "report-1",
     "weight": 0.5, "meta": {…}}

- ``outcome`` is ``tp``, ``fp`` or ``trigger``. Every outcome row is also a trigger (#15):
  a rule credited with a tp was, by definition, relevant. ``trigger`` alone says the
  rule was relevant without a verdict.
- ``weight`` (0..1, default 1) scales the tp/fp credit; it never scales the trigger count.
- ``seq`` increases by one per row. ``(key, rule)`` is the idempotency identity: one
  report naming N rules shares one key and writes N rows; a retry writes nothing and
  returns the stored row. Reusing a key for a different payload is an EventConflictError.
- Rows are appended under the one workspace lock with one fsync (aegis_core.storage);
  nothing ever rewrites a row. A migration appends an epoch row instead.

Readers accept v1 rows (the ``cell``/``rule_id`` + ``signal`` shape of the v3
``signals.jsonl``) and convert them in memory; see ``normalize_rows``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
import math
import os
from pathlib import Path
import threading
from typing import Any, Dict, Iterable, List, Optional, Tuple

from aegis_core.storage import append_jsonl, locked, read_jsonl
from aegis_core.workspace.layout import WorkspaceLayout

__all__ = [
    "LEDGER_VERSION",
    "OUTCOMES",
    "SOURCES",
    "EventConflictError",
    "LedgerView",
    "aggregate",
    "aggregate_rows",
    "append",
    "append_epoch",
    "append_rows",
    "ledger_path",
    "normalize_rows",
    "read",
]

LEDGER_VERSION = 2
OUTCOMES = ("tp", "fp", "trigger")
SOURCES = ("ci", "session", "mcp", "manual", "migrate")
_V1_SIGNALS = {"tp": "tp", "success": "tp", "fp": "fp", "failure": "fp", "trigger": "trigger"}
_MAX_LEGACY_WEIGHT = Decimal("10")


class EventConflictError(ValueError):
    """An idempotency key was already recorded for this rule with a different payload."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def ledger_path(workspace: Any) -> Path:
    return WorkspaceLayout(Path(os.fspath(workspace)).resolve()).ledger_file


def _weight(row: Dict[str, Any]) -> Optional[Decimal]:
    value = row.get("weight", 1)
    if isinstance(value, bool):
        return None
    try:
        weight = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    if not weight.is_finite() or weight < 0 or weight > _MAX_LEGACY_WEIGHT:
        return None
    return weight


# ── v1 compatibility ─────────────────────────────────────────────────────────

def _v1_rule(row: Dict[str, Any]) -> Optional[str]:
    for key in ("rule_id", "cell", "cell_id"):
        value = row.get(key)
        if isinstance(value, str) and value:
            return value
    used = row.get("cells_used")
    if isinstance(used, list) and used and isinstance(used[0], str) and used[0]:
        return used[0]
    return None


def _v1_to_v2(row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    rule = _v1_rule(row)
    signal = row.get("signal") or row.get("outcome")
    outcome = _V1_SIGNALS.get(signal) if isinstance(signal, str) else None
    if rule is None or outcome is None:
        return None
    meta = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
    meta = dict(meta)
    out: Dict[str, Any] = {
        "v": LEDGER_VERSION,
        "ts": row.get("timestamp") or row.get("triggered_at") or row.get("ts"),
        "rule": rule,
        "outcome": outcome,
        "source": row.get("source"),
        "host": meta.pop("host", None),
        "session": meta.pop("session", None),
        "key": row.get("event_id"),
        "from": "v1",
    }
    if "credit_weight" in meta:
        out["weight"] = meta.pop("credit_weight")
    if meta:
        out["meta"] = meta
    return out


def normalize_rows(rows: Iterable[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], int]:
    """Return ``(v2 outcome rows, unusable row count)`` for raw ledger rows of any version.

    v2 rows pass through; rows without ``rule`` and ``outcome`` (an epoch row) are
    dropped without counting as unusable. v1 rows are converted in memory, never
    rewritten on disk. v1 counted triggers in separate ``trigger`` rows (v3 ``aegis
    check`` wrote one trigger row and one outcome row per rule and run), while a v2
    outcome row is itself a trigger. So per rule, a v1 trigger row is dropped for each
    v1 outcome row it pairs with: the rule ends with max(v1 triggers, v1 outcomes)
    triggers, as v3 readers counted it. The trigger rows kept are the latest ones, so
    the last trigger time survives. v1 MCP rows (``source: "mcp"``) never pair: v3
    wrote a report as one outcome row, and a "partial" as one trigger row.
    """
    out: List[Dict[str, Any]] = []
    unusable = 0
    v1_triggers: Dict[str, List[Dict[str, Any]]] = {}
    v1_outcomes: Dict[str, int] = {}
    for row in rows:
        if row.get("v") == LEDGER_VERSION:
            if "rule" not in row and "outcome" not in row:
                continue  # epoch or other bookkeeping row
            if (
                isinstance(row.get("rule"), str) and row["rule"]
                and row.get("outcome") in OUTCOMES and _weight(row) is not None
            ):
                out.append(row)
            else:
                unusable += 1
            continue
        converted = _v1_to_v2(row)
        if converted is None or _weight(converted) is None:
            unusable += 1
            continue
        rule = converted["rule"]
        if converted["source"] == "mcp":
            out.append(converted)
        elif converted["outcome"] == "trigger":
            v1_triggers.setdefault(rule, []).append(converted)
        else:
            v1_outcomes[rule] = v1_outcomes.get(rule, 0) + 1
            out.append(converted)
    for rule, triggers in v1_triggers.items():
        paired = min(len(triggers), v1_outcomes.get(rule, 0))
        out.extend(triggers[paired:])
    return out, unusable


# ── Reading ──────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class LedgerView:
    """The ledger as read: normalized v2 outcome rows plus what could not be used."""

    rows: List[Dict[str, Any]]
    skipped_lines: List[int] = field(default_factory=list)
    unusable_rows: int = 0
    torn_tail: bool = False
    error: Optional[str] = None
    path: Optional[Path] = None


def read(workspace: Any) -> LedgerView:
    """Read the ledger. Never raises for its content; a missing ledger is empty."""
    path = ledger_path(workspace)
    raw = read_jsonl(path)
    rows, unusable = normalize_rows(raw.rows)
    return LedgerView(rows, list(raw.skipped_lines), unusable, raw.torn_tail, raw.error, path)


def _plain(value: Decimal) -> Any:
    return int(value) if value == value.to_integral_value() else float(value)


def aggregate(workspace: Any, rule: Optional[str] = None) -> Dict[str, Any]:
    """Per-rule totals ``{triggers, tp, fp, last_ts}`` from the ledger.

    With ``rule``, that rule's totals (zeros and ``last_ts: None`` when it has no rows);
    without, a mapping of every rule with rows to its totals. Every outcome row counts
    as one trigger; tp/fp sum the row weights. A row whose weight is not a number in
    [0, 10] (v1 allowed up to 10) is unusable: read() counts it and nothing uses it.
    """
    return aggregate_rows(read(workspace).rows, rule)


def aggregate_rows(rows: Iterable[Dict[str, Any]], rule: Optional[str] = None) -> Dict[str, Any]:
    """aggregate() over rows already read (normalized v2 outcome rows)."""
    sums: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        name = row["rule"]
        if rule is not None and name != rule:
            continue
        entry = sums.setdefault(name, {"triggers": 0, "tp": Decimal(0), "fp": Decimal(0), "last_ts": None})
        entry["triggers"] += 1
        ts = row.get("ts")
        if isinstance(ts, str) and (entry["last_ts"] is None or ts > entry["last_ts"]):
            entry["last_ts"] = ts
        if row["outcome"] in ("tp", "fp"):
            entry[row["outcome"]] += _weight(row) or Decimal(0)
    for entry in sums.values():
        entry["tp"] = _plain(entry["tp"])
        entry["fp"] = _plain(entry["fp"])
    if rule is not None:
        return sums.get(rule, {"triggers": 0, "tp": 0, "fp": 0, "last_ts": None})
    return sums


# ── Writing ──────────────────────────────────────────────────────────────────

def _payload_digest(row: Dict[str, Any]) -> str:
    # Attribution (host, session) and position (seq, ts) are not part of the payload:
    # a retry after a reconnect comes from a new session and must deduplicate.
    payload = {k: row.get(k) for k in ("outcome", "source", "weight", "meta")}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=True).encode("ascii")).hexdigest()


@dataclass
class _Index:
    """What appends need from the ledger: the next seq and the (key, rule) identities.

    Cached per ledger file and refreshed from the bytes appended since the last look,
    so an append in a long-lived process reads only the new tail.
    """

    device: int = -1
    inode: int = -1
    offset: int = 0
    last_seq: int = 0
    keyed: Dict[Tuple[str, str], Dict[str, Any]] = field(default_factory=dict)

    def absorb(self, raw_rows: Iterable[Dict[str, Any]]) -> None:
        for raw in raw_rows:
            seq = raw.get("seq")
            if isinstance(seq, int) and not isinstance(seq, bool) and seq > self.last_seq:
                self.last_seq = seq
        rows, _ = normalize_rows(raw_rows)
        for row in rows:
            key = row.get("key")
            if isinstance(key, str) and key:
                self.keyed.setdefault((key, row["rule"]), row)


_INDEX_GUARD = threading.Lock()
_INDEXES: Dict[str, _Index] = {}


def _parse_tail(data: bytes) -> List[Dict[str, Any]]:
    rows = []
    for line in data.split(b"\n"):
        line = line.rstrip(b"\r")
        if not line.strip():
            continue
        try:
            value = json.loads(line.decode("utf-8-sig"))
        except (UnicodeDecodeError, ValueError, RecursionError):
            continue
        if isinstance(value, dict):
            rows.append(value)
    return rows


def _current_index(path: Path) -> _Index:
    """The index of ``path`` as it is on disk now. Call with the workspace lock held."""
    key = str(path)
    with _INDEX_GUARD:
        index = _INDEXES.get(key)
    try:
        st = os.stat(path)
    except FileNotFoundError:
        index = _Index()
        with _INDEX_GUARD:
            _INDEXES[key] = index
        return index
    if index is None or (index.device, index.inode) != (st.st_dev, st.st_ino) or st.st_size < index.offset:
        index = _Index(device=st.st_dev, inode=st.st_ino)
    if st.st_size > index.offset:
        with open(path, "rb") as fh:
            fh.seek(index.offset)
            data = fh.read(st.st_size - index.offset)
        complete = data.rfind(b"\n") + 1  # a torn tail is read again once it is terminated
        index.absorb(_parse_tail(data[:complete]))
        index.offset += complete
    with _INDEX_GUARD:
        _INDEXES[key] = index
    return index


def _write(path: Path, rows: List[Dict[str, Any]]) -> None:
    """Append rows and absorb them into the index. Call with the workspace lock held."""
    try:
        append_jsonl(path, rows)
    except BaseException:
        with _INDEX_GUARD:
            _INDEXES.pop(str(path), None)  # the file may hold part of the write: re-read it next time
        raise
    _current_index(path)


def _validated(event: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(event, dict):
        raise ValueError("each ledger event must be a mapping")
    rule, outcome, source = event.get("rule"), event.get("outcome"), event.get("source")
    if not isinstance(rule, str) or not rule.strip():
        raise ValueError("rule must be a non-empty string")
    if outcome not in OUTCOMES:
        raise ValueError(f"outcome must be one of {list(OUTCOMES)}, got {outcome!r}")
    if source not in SOURCES:
        raise ValueError(f"source must be one of {list(SOURCES)}, got {source!r}")
    for name in ("host", "session", "key"):
        value = event.get(name)
        if value is not None and not isinstance(value, str):
            raise ValueError(f"{name} must be a string or None")
    row: Dict[str, Any] = {
        "v": LEDGER_VERSION,
        "rule": rule,
        "outcome": outcome,
        "source": source,
        "host": event.get("host"),
        "session": event.get("session"),
        "key": event.get("key") or None,
    }
    weight = event.get("weight")
    if weight is not None:
        if isinstance(weight, bool) or not isinstance(weight, (int, float, Decimal)):
            raise ValueError(f"weight must be a number, got {type(weight).__name__}")
        if not math.isfinite(float(weight)) or not 0 <= weight <= 1:
            raise ValueError(f"weight must be between 0 and 1, got {weight}")
        if weight != 1:
            row["weight"] = float(weight)
    meta = event.get("meta")
    if meta is not None:
        if not isinstance(meta, dict):
            raise ValueError("meta must be a mapping or None")
        try:
            json.dumps(meta, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise ValueError("meta must be JSON serializable") from exc
        if meta:
            row["meta"] = meta
    return row


def append(workspace: Any, events: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Append outcome events; return the row for each event, in order.

    An event is ``{"rule", "outcome", "source"}`` plus optional ``host``, ``session``,
    ``key``, ``weight`` (0..1) and ``meta``. Every event is validated before anything
    is written. An event whose ``(key, rule)`` is already in the ledger writes nothing
    and returns the stored row; with a different payload it raises EventConflictError
    and the call writes nothing.
    """
    if isinstance(events, (str, bytes, dict)):
        raise ValueError("events must be an iterable of mappings")
    planned = [_validated(e) for e in events]
    if not planned:
        return []
    path = ledger_path(workspace)
    with locked(workspace):
        index = _current_index(path)
        seen: Dict[Tuple[str, str], Dict[str, Any]] = {}
        results: List[Dict[str, Any]] = []
        new_rows: List[Dict[str, Any]] = []
        seq = index.last_seq
        stamp = _utc_now()
        for row in planned:
            identity = (row["key"], row["rule"]) if row["key"] else None
            existing = None
            if identity is not None:
                existing = seen.get(identity) or index.keyed.get(identity)
            if existing is not None:
                if _payload_digest(existing) != _payload_digest(row):
                    raise EventConflictError(
                        f"key {row['key']!r} is already recorded for rule {row['rule']!r} with a different payload"
                    )
                results.append(existing)
                continue
            seq += 1
            written = {"v": LEDGER_VERSION, "seq": seq, "ts": stamp, **{k: v for k, v in row.items() if k != "v"}}
            new_rows.append(written)
            results.append(written)
            if identity is not None:
                seen[identity] = written
        if new_rows:
            _write(path, new_rows)
        return results


def append_epoch(workspace: Any, note: Dict[str, Any]) -> Dict[str, Any]:
    """Append an epoch row (no rule, no outcome) recording a migration; return it."""
    if not isinstance(note, dict):
        raise ValueError("note must be a mapping")
    path = ledger_path(workspace)
    with locked(workspace):
        index = _current_index(path)
        row = {"v": LEDGER_VERSION, "seq": index.last_seq + 1, "ts": _utc_now(), "epoch": note}
        _write(path, [row])
        return row


def append_rows(workspace: Any, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Append already-formed v2 outcome rows (``aegis migrate``), renumbering their seq.

    Rows whose ``(key, rule)`` is already in the ledger are skipped, so a re-run adds
    nothing. Returns the rows written.
    """
    path = ledger_path(workspace)
    with locked(workspace):
        index = _current_index(path)
        seq = index.last_seq
        seen = set(index.keyed)
        new_rows = []
        for row in rows:
            key = row.get("key")
            identity = (key, row.get("rule")) if isinstance(key, str) and key else None
            if identity is not None and identity in seen:
                continue
            seq += 1
            new_rows.append({"v": LEDGER_VERSION, "seq": seq, **{k: v for k, v in row.items() if k not in ("v", "seq")}})
            if identity is not None:
                seen.add(identity)
        if new_rows:
            _write(path, new_rows)
        return new_rows

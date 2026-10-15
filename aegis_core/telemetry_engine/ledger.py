"""Atomic evidence ledger, process locks, generation fencing, and signal I/O."""
from __future__ import annotations
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import os
import sys
import tempfile
import threading
from pathlib import Path
from typing import Any, Optional

from aegis_core.locking import _acquire_os_lock, _get_thread_lock, _release_os_lock
from aegis_core.taxonomy import TELEMETRY_LOCK_TIMEOUT_SECONDS
from aegis_core.workspace import resolve_workspace
from aegis_core.workspace.layout import LockResource, WorkspaceLayout

VALID_SIGNAL_TYPES = frozenset({"tp", "fp", "fn", "trigger"})
VALID_SOURCES = frozenset({"ci", "session", "mcp", "manual"})
SIGNALS_FILENAME = "signals.jsonl"
LOCK_FILENAME = ".signals.lock"
EPOCH_FILENAME = "epoch_generation"
DEFAULT_GENERATION = 1
_MSVCRT_RETRY_SECONDS = 0.05

class EventConflictError(ValueError):
    """An event_id already exists in the log with a different payload."""

class StaleGenerationError(RuntimeError):
    """The caller's expected epoch generation no longer matches the workspace."""

_lock_tls = threading.local()
_SIGNALS_CACHE: dict[str, tuple[tuple[int, int, int], bytes, dict[str, dict]]] = {}

def _cfg_signals_filename() -> str:
    return str(getattr(sys.modules.get("aegis_core.telemetry"), "SIGNALS_FILENAME", SIGNALS_FILENAME))

def _cfg_lock_filename() -> str:
    return str(getattr(sys.modules.get("aegis_core.telemetry"), "LOCK_FILENAME", LOCK_FILENAME))

def _cfg_epoch_filename() -> str:
    return str(getattr(sys.modules.get("aegis_core.telemetry"), "EPOCH_FILENAME", EPOCH_FILENAME))

def invalidate_signals_cache() -> None:
    _SIGNALS_CACHE.clear()

def _resolve_evidence_dir(workspace: str) -> str:
    ws = str(workspace)
    from aegis_core.workspace.discovery import check_legacy_soma_sentinel
    check_legacy_soma_sentinel(ws)
    return os.path.join(ws, ".aegis", "evidence")

def _atomic_replace_bytes(path: str, data: bytes) -> None:
    from aegis_core.storage import fsync_dir
    parent = os.path.dirname(os.path.abspath(path))
    os.makedirs(parent, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=".signals.", suffix=".tmp", dir=parent)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data); fh.flush(); os.fsync(fh.fileno())
        os.replace(tmp_path, path)
        fsync_dir(parent)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise

@contextmanager
def evidence_lock(workspace: str):
    """Context manager acquiring both the per-process thread lock and the OS file lock."""
    evidence_dir = _resolve_evidence_dir(workspace)
    os.makedirs(evidence_dir, exist_ok=True)
    legacy_lock_path = os.path.join(evidence_dir, _cfg_lock_filename())
    try:
        if not os.path.exists(legacy_lock_path):
            with open(legacy_lock_path, "a", encoding="utf-8"):
                pass
    except OSError:
        pass
    canonical_lock = WorkspaceLayout(Path(str(workspace))).lock_file(LockResource.SIGNALS)
    os.makedirs(str(canonical_lock.parent), exist_ok=True)
    lock_path = os.path.realpath(str(canonical_lock))
    with _get_thread_lock(lock_path):
        if not hasattr(_lock_tls, "held"):
            _lock_tls.held = {}
        depth, fh = _lock_tls.held.get(lock_path, (0, None))
        if depth > 0 and fh is not None:
            _lock_tls.held[lock_path] = (depth + 1, fh)
            try:
                yield lock_path
            finally:
                d, h = _lock_tls.held.get(lock_path, (1, fh))
                if d <= 1:
                    _lock_tls.held.pop(lock_path, None)
                else:
                    _lock_tls.held[lock_path] = (d - 1, h)
        else:
            with open(lock_path, "a+") as new_fh:
                if not _acquire_os_lock(new_fh.fileno(), timeout_sec=TELEMETRY_LOCK_TIMEOUT_SECONDS):
                    raise TimeoutError("Timed out waiting for file lock")
                _lock_tls.held[lock_path] = (1, new_fh)
                try:
                    yield lock_path
                finally:
                    try:
                        _release_os_lock(new_fh.fileno())
                    finally:
                        _lock_tls.held.pop(lock_path, None)

def read_generation(workspace: str) -> int:
    gen_path = os.path.join(str(workspace), ".aegis", _cfg_epoch_filename())
    if not os.path.isfile(gen_path):
        return DEFAULT_GENERATION
    try:
        with open(gen_path, "r", encoding="utf-8") as f:
            content = f.read().strip()
            return int(content) if content else DEFAULT_GENERATION
    except (OSError, ValueError):
        return DEFAULT_GENERATION

def current_generation(workspace: str) -> int:
    return read_generation(workspace)

def increment_generation(workspace: str) -> int:
    ws = str(workspace)
    with evidence_lock(ws):
        gen = read_generation(ws) + 1
        epoch_file = os.path.join(ws, ".aegis", _cfg_epoch_filename())
        os.makedirs(os.path.dirname(epoch_file), exist_ok=True)
        _atomic_replace_bytes(epoch_file, f"{gen}\n".encode("utf-8"))
        return gen

def get_signals_path(workspace: str) -> str:
    return os.path.join(_resolve_evidence_dir(workspace), _cfg_signals_filename())

def get_lock_path(workspace: str) -> str:
    return str(WorkspaceLayout(Path(str(workspace))).lock_file(LockResource.SIGNALS))

def _normalize_signal_record(record: dict) -> dict:
    rule_id = record.get("rule_id") or record.get("cell")
    if isinstance(rule_id, str) and rule_id:
        record.setdefault("rule_id", rule_id)
        record.setdefault("cell", rule_id)
    return record

def read_signals(workspace: str) -> list[dict]:
    ws, sig_fname = str(workspace), _cfg_signals_filename()
    path = get_signals_path(ws)
    if not os.path.isfile(path):
        alt_path = os.path.join(ws, ".aegis", "telemetry", sig_fname)
        if not os.path.isfile(alt_path):
            return []
        path = alt_path
    records = []
    with open(path, "r", encoding="utf-8", errors="surrogatepass") as f:
        for line in f:
            line_str = line.strip()
            if line_str:
                try:
                    rec = json.loads(line_str)
                    if isinstance(rec, dict):
                        records.append(_normalize_signal_record(rec))
                except Exception:
                    pass
    return records

def load_signals(workspace: Path | str | None = None) -> list[dict]:
    return read_signals(str(workspace) if workspace is not None else str(resolve_workspace()))

def compute_payload_digest(cell_name: str, signal_type: str, source: str, metadata: Any) -> str:
    normalized = json.dumps(
        {"cell": cell_name, "signal": signal_type, "source": source, "metadata": metadata or None},
        sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    )
    return hashlib.sha256(normalized.encode("utf-8", errors="surrogatepass")).hexdigest()

def compute_event_id(principal: str, idempotency_scope: str, idempotency_key: str, cell_name: str) -> str:
    identity = f"{principal}:{idempotency_scope}:{idempotency_key}:{cell_name}"
    return hashlib.sha256(identity.encode("utf-8", errors="surrogatepass")).hexdigest()

def _read_existing_events(log_path: str) -> tuple[bytes, dict[str, dict]]:
    try:
        st = os.stat(log_path)
    except FileNotFoundError:
        _SIGNALS_CACHE.pop(log_path, None); return b"", {}
    fingerprint = (st.st_ino, st.st_mtime_ns, st.st_size)
    cached = _SIGNALS_CACHE.get(log_path)
    if cached is not None and cached[0] == fingerprint:
        return cached[1], dict(cached[2])
    try:
        with open(log_path, "rb") as f:
            raw = f.read()
    except FileNotFoundError:
        _SIGNALS_CACHE.pop(log_path, None); return b"", {}
    by_id: dict[str, dict] = {}
    for line in raw.splitlines():
        try:
            record = json.loads(line.decode("utf-8", errors="surrogatepass"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
        if isinstance(record, dict) and record.get("event_id"):
            by_id.setdefault(record["event_id"], _normalize_signal_record(record))
    _SIGNALS_CACHE[log_path] = (fingerprint, raw, dict(by_id))
    return raw, by_id

def _migration_in_progress(workspace: str) -> bool:
    layout = WorkspaceLayout(Path(str(workspace)))
    return any(os.path.exists(p) for p in (
        str(layout.lock_file(LockResource.MIGRATION)),
        os.path.join(workspace, ".aegis", "migration.lock"),
        os.path.join(workspace, ".aegis", "evidence", ".migration.lock"),
    ))

def _validate_event(event: dict) -> tuple[str, str, str, Optional[dict], str, str, str]:
    if not isinstance(event, dict):
        raise ValueError("each event must be a mapping")
    cell_name = event.get("cell_name") or event.get("rule_id") or event.get("cell")
    signal_type = event.get("signal_type") or event.get("signal")
    source, metadata = event.get("source"), event.get("metadata")
    principal, scope, key = event.get("principal", "unknown"), event.get("idempotency_scope", "global"), event.get("idempotency_key", "")
    if not isinstance(cell_name, str) or not cell_name:
        raise ValueError("cell_name must be a nonempty string")
    if signal_type not in VALID_SIGNAL_TYPES:
        raise ValueError(f"signal_type must be one of {sorted(VALID_SIGNAL_TYPES)}, got {signal_type!r}")
    if source not in VALID_SOURCES:
        raise ValueError(f"source must be one of {sorted(VALID_SOURCES)}, got {source!r}")
    if metadata is not None and not isinstance(metadata, dict):
        raise ValueError("metadata must be a mapping or None")
    for name, value in (("principal", principal), ("idempotency_scope", scope), ("idempotency_key", key)):
        if not isinstance(value, str):
            raise ValueError(f"{name} must be a string")
    if metadata is not None:
        if "credit_weight" in metadata:
            cw = metadata["credit_weight"]
            if not isinstance(cw, (int, float, Decimal)):
                raise ValueError(f"credit_weight must be numeric, got {type(cw)}")
            if cw < 0 or cw > 1:
                raise ValueError(f"credit_weight must be between 0.0 and 1.0, got {cw}")
        try:
            json.dumps(metadata, sort_keys=True, ensure_ascii=False)
        except (TypeError, ValueError) as exc:
            raise ValueError("metadata must be JSON serializable") from exc
    return cell_name, signal_type, source, metadata, principal, scope, key

def append_signals(workspace: str, events: list[dict], expected_generation: Optional[int] = None) -> list[dict]:
    if _migration_in_progress(workspace):
        raise RuntimeError("migration in progress")
    if isinstance(events, (str, bytes)):
        raise ValueError("events must be an iterable of mappings")
    try:
        event_specs = list(events)
    except TypeError as exc:
        raise ValueError("events must be an iterable of mappings") from exc
    if not event_specs:
        return []
    log_path = get_signals_path(workspace)
    with evidence_lock(workspace):
        if _migration_in_progress(workspace):
            raise RuntimeError("migration in progress")
        generation = read_generation(workspace)
        if expected_generation is not None and expected_generation != generation:
            raise StaleGenerationError(f"expected generation {expected_generation}, workspace is at {generation}")
        raw, existing_by_id = _read_existing_events(log_path)
        planned_by_id, new_records, results = dict(existing_by_id), [], []
        for event in event_specs:
            cell_name, signal_type, source, metadata, principal, scope, key = _validate_event(event)
            event_id = payload_digest = None
            if key:
                event_id = compute_event_id(principal, scope, key, cell_name)
                payload_digest = compute_payload_digest(cell_name, signal_type, source, metadata)
                existing = planned_by_id.get(event_id)
                if existing is not None:
                    existing_cell = existing.get("cell") or existing.get("rule_id")
                    existing_digest = existing.get("payload_digest") or compute_payload_digest(
                        existing_cell, existing.get("signal"), existing.get("source"), existing.get("metadata")
                    )
                    if existing_digest != payload_digest:
                        raise EventConflictError(f"event {event_id} already recorded with a different payload")
                    results.append(_normalize_signal_record(existing))
                    continue
            record: dict[str, Any] = {
                "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "rule_id": cell_name, "cell": cell_name, "signal": signal_type, "source": source,
            }
            if event_id is not None:
                record["event_id"], record["payload_digest"] = event_id, payload_digest
            record["generation"] = generation
            if metadata:
                record["metadata"] = metadata
            json.dumps(record, ensure_ascii=False)
            new_records.append(record); results.append(record)
            if event_id is not None:
                planned_by_id[event_id] = record
        if new_records:
            prefix = raw + (b"\n" if raw and not raw.endswith(b"\n") else b"")
            payload = b"".join((json.dumps(r, ensure_ascii=False) + "\n").encode("utf-8", errors="surrogatepass") for r in new_records)
            new_bytes = prefix + payload
            _atomic_replace_bytes(log_path, new_bytes)
            try:
                st = os.stat(log_path)
                _SIGNALS_CACHE[log_path] = ((st.st_ino, st.st_mtime_ns, st.st_size), new_bytes, dict(planned_by_id))
            except OSError:
                _SIGNALS_CACHE.pop(log_path, None)
        return results

def append_signal(
    workspace: str, cell_name: str = "", signal_type: str = "", source: str = "",
    metadata: Optional[dict] = None, principal: str = "unknown",
    idempotency_scope: str = "global", idempotency_key: str = "",
    expected_generation: Optional[int] = None, *, rule_id: Optional[str] = None,
) -> dict:
    target_rule = rule_id if rule_id is not None else cell_name
    events = [{"cell_name": target_rule, "rule_id": target_rule, "signal_type": signal_type, "source": source, "metadata": metadata, "principal": principal, "idempotency_scope": idempotency_scope, "idempotency_key": idempotency_key}]
    return append_signals(workspace, events, expected_generation=expected_generation)[0]

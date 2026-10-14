"""aegis_core.telemetry — Unified telemetry, evidence signals, outcome reflection, and metrics.

Consolidates:
- Atomic evidence ledger, process locks, and idempotency (canonical implementation).
- Re-exports verifiable outcome engine and credit assignment (from aegis_core.outcomes).
- Re-exports transcript fitness updater and platform detection (from aegis_core.outcomes).
- Re-exports metrics snapshots and token census aggregation (from aegis_core.metrics).
- Re-exports quorum sensing across multi-cell triggers (from aegis_core.metrics).
- Re-exports codebase governance coverage mapping (from aegis_core.metrics).
- Re-exports single-grade governance report card (from aegis_core.metrics).
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import os
import secrets
import sys
import tempfile
import threading
import time
from typing import Any, Optional

from aegis_core.locking import _acquire_os_lock, _get_thread_lock, _release_os_lock


# ── Evidence Ledger & Atomic Locking ──────────────────────────────────────

VALID_SIGNAL_TYPES = frozenset({'tp', 'fp', 'fn', 'trigger'})
VALID_SOURCES = frozenset({'ci', 'session', 'mcp', 'manual'})
SIGNALS_FILENAME = 'signals.jsonl'
LOCK_FILENAME = '.signals.lock'
EPOCH_FILENAME = 'epoch_generation'
DEFAULT_GENERATION = 1
_MSVCRT_RETRY_SECONDS = 0.05


class EventConflictError(ValueError):
    """An event_id already exists in the log with a different payload."""


class StaleGenerationError(RuntimeError):
    """The caller's expected epoch generation no longer matches the workspace."""


_lock_tls = threading.local()


def _resolve_evidence_dir(workspace: str) -> str:
    """Resolve canonical evidence directory (.aegis/evidence or fallback .soma/evidence)."""
    ws = str(workspace)
    aegis_evidence = os.path.join(ws, '.aegis', 'evidence')
    soma_evidence = os.path.join(ws, '.soma', 'evidence')
    if os.path.isdir(aegis_evidence):
        return aegis_evidence
    if os.path.isdir(soma_evidence):
        return soma_evidence
    if os.path.isdir(os.path.join(ws, '.aegis')):
        return aegis_evidence
    if os.path.isdir(os.path.join(ws, '.soma')):
        return soma_evidence
    if os.environ.get("AEGIS_WORKSPACE"):
        return aegis_evidence
    return soma_evidence


def _resolve_governance_dir(workspace: str) -> str:
    """Resolve canonical governance directory (.aegis or fallback .soma)."""
    ws = str(workspace)
    aegis_dir = os.path.join(ws, '.aegis')
    soma_dir = os.path.join(ws, '.soma')
    if os.path.isdir(aegis_dir):
        return aegis_dir
    if os.path.isdir(soma_dir):
        return soma_dir
    if os.environ.get("AEGIS_WORKSPACE"):
        return aegis_dir
    return soma_dir


@contextmanager
def evidence_lock(workspace: str):
    """Context manager acquiring both the per-process thread lock and the OS file lock.

    Reentrant within the same thread to prevent POSIX flock self-deadlock.
    """
    evidence_dir = _resolve_evidence_dir(workspace)
    os.makedirs(evidence_dir, exist_ok=True)
    lock_path = os.path.realpath(os.path.join(evidence_dir, LOCK_FILENAME))
    thread_lock = _get_thread_lock(lock_path)
    with thread_lock:
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
            with open(lock_path, 'a+') as new_fh:
                if not _acquire_os_lock(new_fh.fileno(), timeout_sec=10.0):
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
    """Read the current epoch generation integer from .aegis/epoch_generation (or .soma/epoch_generation)."""
    ws = str(workspace)
    aegis_gen = os.path.join(ws, '.aegis', EPOCH_FILENAME)
    if os.path.isfile(aegis_gen):
        gen_path = aegis_gen
    else:
        soma_gen = os.path.join(ws, '.soma', EPOCH_FILENAME)
        if os.path.isfile(soma_gen):
            gen_path = soma_gen
        else:
            return DEFAULT_GENERATION
    try:
        with open(gen_path, 'r', encoding='utf-8') as f:
            content = f.read().strip()
            return int(content) if content else DEFAULT_GENERATION
    except (OSError, ValueError):
        return DEFAULT_GENERATION


def current_generation(workspace: str) -> int:
    """Alias for read_generation."""
    return read_generation(workspace)


def increment_generation(workspace: str) -> int:
    """Atomically increment the epoch generation integer."""
    ws = str(workspace)
    with evidence_lock(ws):
        gen = read_generation(ws) + 1
        if os.path.isfile(os.path.join(ws, '.soma', EPOCH_FILENAME)) and not os.path.isfile(os.path.join(ws, '.aegis', EPOCH_FILENAME)):
            epoch_file = os.path.join(ws, '.soma', EPOCH_FILENAME)
        else:
            epoch_file = os.path.join(ws, '.aegis', EPOCH_FILENAME)
        os.makedirs(os.path.dirname(epoch_file), exist_ok=True)
        _atomic_replace_bytes(epoch_file, f"{gen}\n".encode("utf-8"))
        return gen


def get_signals_path(workspace: str) -> str:
    return os.path.join(_resolve_evidence_dir(workspace), SIGNALS_FILENAME)


def get_lock_path(workspace: str) -> str:
    return os.path.join(_resolve_evidence_dir(workspace), LOCK_FILENAME)


def read_signals(workspace: str) -> list[dict]:
    """Read all signals from the canonical evidence log."""
    path = get_signals_path(str(workspace))
    if not os.path.isfile(path):
        return []
    records = []
    with open(path, 'r', encoding='utf-8', errors='surrogatepass') as f:
        for line in f:
            line_str = line.strip()
            if line_str:
                try:
                    records.append(json.loads(line_str))
                except Exception:
                    pass
    return records


def compute_payload_digest(cell_name: str, signal_type: str, source: str, metadata: Any) -> str:
    normalized = json.dumps(
        {
            'cell': cell_name,
            'signal': signal_type,
            'source': source,
            'metadata': metadata or None,
        },
        sort_keys=True,
        separators=(',', ':'),
        ensure_ascii=False,
    )
    return hashlib.sha256(normalized.encode('utf-8', errors='surrogatepass')).hexdigest()


def compute_event_id(principal: str, idempotency_scope: str, idempotency_key: str, cell_name: str) -> str:
    identity = f"{principal}:{idempotency_scope}:{idempotency_key}:{cell_name}"
    return hashlib.sha256(identity.encode('utf-8', errors='surrogatepass')).hexdigest()


def _read_existing_events(log_path: str) -> tuple[bytes, dict[str, dict]]:
    try:
        with open(log_path, 'rb') as f:
            raw = f.read()
    except FileNotFoundError:
        return b'', {}

    by_id = {}
    for line in raw.splitlines():
        try:
            record = json.loads(line.decode('utf-8', errors='surrogatepass'))
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
        if isinstance(record, dict) and record.get('event_id'):
            by_id.setdefault(record['event_id'], record)
    return raw, by_id


def _fsync_dir(directory: str) -> None:
    if os.name == 'nt':
        return
    try:
        dir_fd = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except OSError:
        pass


def _atomic_replace_bytes(path: str, data: bytes) -> None:
    parent = os.path.dirname(os.path.abspath(path))
    os.makedirs(parent, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix='.signals.', suffix='.tmp', dir=parent)
    try:
        with os.fdopen(fd, 'wb') as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_path, path)
        _fsync_dir(parent)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _migration_in_progress(workspace: str) -> bool:
    return (
        os.path.exists(os.path.join(workspace, '.soma', 'migration.lock'))
        or os.path.exists(os.path.join(workspace, '.soma', 'evidence', '.migration.lock'))
        or os.path.exists(os.path.join(workspace, '.aegis', 'migration.lock'))
        or os.path.exists(os.path.join(workspace, '.aegis', 'evidence', '.migration.lock'))
    )


def _validate_event(event: dict) -> tuple[str, str, str, Optional[dict], str, str, str]:
    if not isinstance(event, dict):
        raise ValueError('each event must be a mapping')

    cell_name = event.get('cell_name')
    signal_type = event.get('signal_type')
    source = event.get('source')
    metadata = event.get('metadata')
    principal = event.get('principal', 'unknown')
    scope = event.get('idempotency_scope', 'global')
    key = event.get('idempotency_key', '')

    if not isinstance(cell_name, str) or not cell_name:
        raise ValueError('cell_name must be a nonempty string')
    if signal_type not in VALID_SIGNAL_TYPES:
        raise ValueError(
            f'signal_type must be one of {sorted(VALID_SIGNAL_TYPES)}, '
            f'got {signal_type!r}'
        )
    if source not in VALID_SOURCES:
        raise ValueError(
            f'source must be one of {sorted(VALID_SOURCES)}, got {source!r}'
        )
    if metadata is not None and not isinstance(metadata, dict):
        raise ValueError('metadata must be a mapping or None')
    for name, value in (
        ('principal', principal), ('idempotency_scope', scope),
        ('idempotency_key', key),
    ):
        if not isinstance(value, str):
            raise ValueError(f'{name} must be a string')

    if metadata is not None:
        if 'credit_weight' in metadata:
            cw = metadata['credit_weight']
            if not isinstance(cw, (int, float, Decimal)):
                raise ValueError(f"credit_weight must be numeric, got {type(cw)}")
            if cw < 0 or cw > 1:
                raise ValueError(f"credit_weight must be between 0.0 and 1.0, got {cw}")
        try:
            json.dumps(metadata, sort_keys=True, ensure_ascii=False)
        except (TypeError, ValueError) as exc:
            raise ValueError('metadata must be JSON serializable') from exc

    return cell_name, signal_type, source, metadata, principal, scope, key


def append_signals(workspace: str, events: list[dict], expected_generation: Optional[int] = None) -> list[dict]:
    """Atomically append a logical batch of canonical evidence events."""
    if _migration_in_progress(workspace):
        raise RuntimeError('migration in progress')

    if isinstance(events, (str, bytes)):
        raise ValueError('events must be an iterable of mappings')
    try:
        event_specs = list(events)
    except TypeError as exc:
        raise ValueError('events must be an iterable of mappings') from exc

    if not event_specs:
        return []

    evidence_dir = _resolve_evidence_dir(workspace)
    log_path = get_signals_path(workspace)

    with evidence_lock(workspace):
        if _migration_in_progress(workspace):
            raise RuntimeError('migration in progress')

        generation = read_generation(workspace)
        if expected_generation is not None and expected_generation != generation:
            raise StaleGenerationError(
                f'expected generation {expected_generation}, workspace is at {generation}'
            )

        raw, existing_by_id = _read_existing_events(log_path)
        planned_by_id = dict(existing_by_id)
        new_records = []
        results = []

        for event in event_specs:
            (cell_name, signal_type, source, metadata, principal,
             scope, key) = _validate_event(event)
            event_id = None
            payload_digest = None
            if key:
                event_id = compute_event_id(principal, scope, key, cell_name)
                payload_digest = compute_payload_digest(
                    cell_name, signal_type, source, metadata)
                existing = planned_by_id.get(event_id)
                if existing is not None:
                    existing_digest = existing.get('payload_digest') or compute_payload_digest(
                        existing.get('cell'), existing.get('signal'),
                        existing.get('source'), existing.get('metadata'))
                    if existing_digest != payload_digest:
                        raise EventConflictError(
                            f'event {event_id} already recorded with a different payload'
                        )
                    results.append(existing)
                    continue

            record = {
                'timestamp': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
                'cell': cell_name,
                'signal': signal_type,
                'source': source,
            }
            if event_id is not None:
                record['event_id'] = event_id
                record['payload_digest'] = payload_digest
            record['generation'] = generation
            if metadata:
                record['metadata'] = metadata

            # Serialization is part of planning: no write can precede an error.
            json.dumps(record, ensure_ascii=False)
            new_records.append(record)
            results.append(record)
            if event_id is not None:
                planned_by_id[event_id] = record

        if new_records:
            prefix = raw
            if prefix and not prefix.endswith(b'\n'):
                prefix += b'\n'
            payload = b''.join(
                (json.dumps(record, ensure_ascii=False) + '\n').encode('utf-8', errors='surrogatepass')
                for record in new_records
            )
            _atomic_replace_bytes(log_path, prefix + payload)
        return results


def append_signal(
    workspace: str,
    cell_name: str,
    signal_type: str,
    source: str,
    metadata: Optional[dict] = None,
    principal: str = "unknown",
    idempotency_scope: str = "global",
    idempotency_key: str = "",
    expected_generation: Optional[int] = None,
) -> dict:
    """Convenience single-signal wrapper around append_signals."""
    events = [{
        'cell_name': cell_name,
        'signal_type': signal_type,
        'source': source,
        'metadata': metadata,
        'principal': principal,
        'idempotency_scope': idempotency_scope,
        'idempotency_key': idempotency_key,
    }]
    results = append_signals(workspace, events, expected_generation=expected_generation)
    return results[0]


# ── Outcome Engine, Credit Assignment & Fitness Reflection ─────────────────
from aegis_core.outcomes import (
    VERIFY_TIMEOUT,
    _run_verify,
    detect_test_runner,
    capture_test_outcome,
    capture_build_outcome,
    capture_git_signals,
    capture_mcp_outcomes,
    _insight_cursor_path,
    _read_insight_cursor,
    commit_insight_cursor,
    capture_human_insight_signals,
    read_human_insight_signals,
    _as_int,
    _get_changed_files,
    match_cells_to_changes,
    to_fraction,
    compute_credit_weights,
    compute_fitness_signals,
    update_cell_fitness,
    INSIGHT_PRINCIPAL,
    INSIGHT_SCOPE,
    append_fitness_log,
    run_outcome_engine,
    PLATFORMS,
    DEFAULT_PLATFORM,
    detect_platform,
    resolve_transcript_id,
    extract_modified_files,
    match_cells,
    update_fitness,
)


def main(*args, **kwargs) -> int:
    return run_outcome_engine(*args, mod=sys.modules[__name__], **kwargs)


# ── Metrics Snapshot, Quorum, Coverage & Immune Grade ─────────────────────
from aegis_core.metrics import (
    resolve_metrics_dir,
    compute_token_census,
    take_snapshot,
    evaluate_quorum,
    calculate_coverage,
    calculate_cell_coverage,
    letter_grade,
    calculate_immune_grade,
)
from aegis_core.workspace import resolve_workspace


__all__ = [
    "VALID_SIGNAL_TYPES",
    "VALID_SOURCES",
    "SIGNALS_FILENAME",
    "LOCK_FILENAME",
    "EPOCH_FILENAME",
    "DEFAULT_GENERATION",
    "EventConflictError",
    "StaleGenerationError",
    "evidence_lock",
    "read_generation",
    "current_generation",
    "increment_generation",
    "get_signals_path",
    "get_lock_path",
    "read_signals",
    "compute_payload_digest",
    "compute_event_id",
    "append_signals",
    "append_signal",
    "detect_test_runner",
    "capture_test_outcome",
    "capture_build_outcome",
    "capture_git_signals",
    "capture_mcp_outcomes",
    "capture_human_insight_signals",
    "read_human_insight_signals",
    "commit_insight_cursor",
    "match_cells_to_changes",
    "to_fraction",
    "compute_credit_weights",
    "compute_fitness_signals",
    "update_cell_fitness",
    "append_fitness_log",
    "run_outcome_engine",
    "main",
    "INSIGHT_PRINCIPAL",
    "INSIGHT_SCOPE",
    "VERIFY_TIMEOUT",
    "_get_changed_files",
    "_read_insight_cursor",
    "_run_verify",
    "PLATFORMS",
    "DEFAULT_PLATFORM",
    "detect_platform",
    "resolve_transcript_id",
    "extract_modified_files",
    "match_cells",
    "update_fitness",
    "resolve_metrics_dir",
    "compute_token_census",
    "take_snapshot",
    "evaluate_quorum",
    "calculate_coverage",
    "calculate_cell_coverage",
    "letter_grade",
    "calculate_immune_grade",
    "resolve_workspace",
]


import types


class _TelemetryFacadeModule(types.ModuleType):
    """Module proxy that mirrors attribute mutations down to canonical submodules."""

    def __setattr__(self, name: str, value: Any) -> None:
        super().__setattr__(name, value)
        try:
            import aegis_core.outcomes as _outcomes
            if hasattr(_outcomes, name):
                setattr(_outcomes, name, value)
        except Exception:
            pass
        try:
            import aegis_core.metrics as _metrics
            if hasattr(_metrics, name):
                setattr(_metrics, name, value)
        except Exception:
            pass


sys.modules[__name__].__class__ = _TelemetryFacadeModule


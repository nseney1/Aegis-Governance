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
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import gzip
import hashlib
import json
import os
import secrets
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Optional

from aegis_core.locking import _acquire_os_lock, _get_thread_lock, _release_os_lock
from aegis_core.taxonomy import TELEMETRY_LOCK_TIMEOUT_SECONDS
from aegis_core.workspace.layout import LockResource, WorkspaceLayout


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
    """Resolve canonical evidence directory (.aegis/evidence)."""
    ws = str(workspace)
    from aegis_core.workspace.discovery import check_legacy_soma_sentinel
    check_legacy_soma_sentinel(ws)
    return os.path.join(ws, '.aegis', 'evidence')


@contextmanager
def evidence_lock(workspace: str):
    """Context manager acquiring both the per-process thread lock and the OS file lock.

    Reentrant within the same thread to prevent POSIX flock self-deadlock.
    """
    evidence_dir = _resolve_evidence_dir(workspace)
    os.makedirs(evidence_dir, exist_ok=True)
    legacy_lock_path = os.path.join(evidence_dir, LOCK_FILENAME)
    try:
        if not os.path.exists(legacy_lock_path):
            with open(legacy_lock_path, "a", encoding="utf-8"):
                pass
    except OSError:
        pass
    canonical_lock = WorkspaceLayout(Path(str(workspace))).lock_file(LockResource.SIGNALS)
    os.makedirs(str(canonical_lock.parent), exist_ok=True)
    lock_path = os.path.realpath(str(canonical_lock))
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
    """Read the current epoch generation integer from .aegis/epoch_generation."""
    ws = str(workspace)
    gen_path = os.path.join(ws, '.aegis', EPOCH_FILENAME)
    if not os.path.isfile(gen_path):
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
        epoch_file = os.path.join(ws, '.aegis', EPOCH_FILENAME)
        os.makedirs(os.path.dirname(epoch_file), exist_ok=True)
        _atomic_replace_bytes(epoch_file, f"{gen}\n".encode("utf-8"))
        return gen


def get_signals_path(workspace: str) -> str:
    return os.path.join(_resolve_evidence_dir(workspace), SIGNALS_FILENAME)


def get_lock_path(workspace: str) -> str:
    return str(WorkspaceLayout(Path(str(workspace))).lock_file(LockResource.SIGNALS))


def read_signals(workspace: str) -> list[dict]:
    """Read all signals from the canonical evidence or telemetry log."""
    ws = str(workspace)
    path = get_signals_path(ws)
    if not os.path.isfile(path):
        alt_path = os.path.join(ws, ".aegis", "telemetry", SIGNALS_FILENAME)
        if os.path.isfile(alt_path):
            path = alt_path
        else:
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


def load_signals(workspace: Path | str | None = None) -> list[dict]:
    """Alias for read_signals supporting optional workspace resolution."""
    ws = str(workspace) if workspace is not None else str(resolve_workspace())
    return read_signals(ws)


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


_SIGNALS_CACHE: dict[str, tuple[tuple[int, int, int], bytes, dict[str, dict]]] = {}


def invalidate_signals_cache() -> None:
    """Clear the in-memory signals file fingerprint cache."""
    _SIGNALS_CACHE.clear()


CHECKPOINT_ROLLUP_FILENAME = "checkpoint_rollup.json"


def _parse_signal_timestamp(ts: Any) -> Optional[datetime]:
    """Parse an ISO-8601 or numeric timestamp into a UTC-aware datetime."""
    if ts is None or isinstance(ts, bool):
        return None
    if isinstance(ts, (int, float)):
        try:
            return datetime.fromtimestamp(float(ts), tz=timezone.utc)
        except (OSError, OverflowError, ValueError):
            return None
    if isinstance(ts, str):
        text = ts.strip()
        if not text:
            return None
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(text)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except ValueError:
            return None
    return None


def _extract_rule_ids(record: dict) -> list[str]:
    """Extract rule/cell IDs associated with a signal record."""
    for key in ("rule_id", "cell", "cell_id", "cell_name", "rule"):
        val = record.get(key)
        if isinstance(val, str) and val.strip():
            return [val.strip()]
    cells_used = record.get("cells_used")
    if isinstance(cells_used, list):
        return [str(c).strip() for c in cells_used if isinstance(c, str) and c.strip()]
    return []


def _new_rollup_rule_entry() -> dict[str, Any]:
    return {
        "applied": 0,
        "helped": 0,
        "harmed": 0,
        "ignored": 0,
        "alpha_delta": 0.0,
        "beta_delta": 0.0,
    }


def _accumulate_record_into_rules(rules_map: dict[str, dict[str, Any]], record: dict) -> None:
    """Accumulate a single signal record into a per-rule rollup map."""
    if not isinstance(record, dict):
        return
    rule_ids = _extract_rule_ids(record)
    if not rule_ids:
        return
    sig = str(
        record.get("signal")
        or record.get("signal_type")
        or record.get("outcome")
        or record.get("action")
        or ""
    ).strip().lower()
    metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
    try:
        weight = float(record.get("credit_weight") or metadata.get("credit_weight", 1.0))
    except (TypeError, ValueError):
        weight = 1.0
    weight = max(0.0, weight)

    for rid in rule_ids:
        entry = rules_map.setdefault(rid, _new_rollup_rule_entry())
        if sig in ("tp", "helped", "success", "pass", "true_positive"):
            entry["applied"] = int(entry.get("applied", 0)) + 1
            entry["helped"] = int(entry.get("helped", 0)) + 1
            entry["alpha_delta"] = round(float(entry.get("alpha_delta", 0.0)) + weight, 6)
        elif sig in ("fp", "harmed", "failure", "fail", "false_positive"):
            entry["applied"] = int(entry.get("applied", 0)) + 1
            entry["harmed"] = int(entry.get("harmed", 0)) + 1
            entry["beta_delta"] = round(float(entry.get("beta_delta", 0.0)) + weight, 6)
        elif sig in ("fn", "ignored", "skip", "skipped"):
            entry["ignored"] = int(entry.get("ignored", 0)) + 1
        elif sig in ("trigger", "applied", "scan"):
            entry["applied"] = int(entry.get("applied", 0)) + 1


def load_checkpoint_rollup(workspace: Path | str | None = None) -> dict[str, Any]:
    """Load checkpoint_rollup.json from .aegis/telemetry or .aegis/evidence if present."""
    ws_path = Path(workspace).resolve() if workspace is not None else Path(resolve_workspace()).resolve()
    candidates = [
        ws_path / ".aegis" / "telemetry" / CHECKPOINT_ROLLUP_FILENAME,
        ws_path / ".aegis" / "evidence" / CHECKPOINT_ROLLUP_FILENAME,
        ws_path / CHECKPOINT_ROLLUP_FILENAME,
    ]
    for cand in candidates:
        if cand.is_file():
            try:
                data = json.loads(cand.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    data.setdefault("rules", {})
                    data.setdefault("compacted_count", 0)
                    data.setdefault("last_compacted_at", "")
                    return data
            except Exception:
                continue
    return {"rules": {}, "compacted_count": 0, "last_compacted_at": ""}


def get_rule_stats(workspace: Path | str | None = None, rule_id: Optional[str] = None) -> dict[str, Any]:
    """Compute aggregated rule stats combining checkpoint_rollup.json and active signals.jsonl."""
    ws_path = Path(workspace).resolve() if workspace is not None else Path(resolve_workspace()).resolve()
    rollup = load_checkpoint_rollup(ws_path)
    rules_map: dict[str, dict[str, Any]] = {}
    for rid, counts in (rollup.get("rules") or {}).items():
        if isinstance(counts, dict):
            rules_map[rid] = {
                "applied": int(counts.get("applied", 0)),
                "helped": int(counts.get("helped", 0)),
                "harmed": int(counts.get("harmed", 0)),
                "ignored": int(counts.get("ignored", 0)),
                "alpha_delta": float(counts.get("alpha_delta", float(counts.get("helped", 0)))),
                "beta_delta": float(counts.get("beta_delta", float(counts.get("harmed", 0)))),
            }

    active_records = read_signals(str(ws_path))
    for rec in active_records:
        _accumulate_record_into_rules(rules_map, rec)

    for rid, entry in rules_map.items():
        alpha = round(1.0 + float(entry["alpha_delta"]), 6)
        beta = round(1.0 + float(entry["beta_delta"]), 6)
        entry["alpha"] = alpha
        entry["beta"] = beta
        entry["mean"] = round(alpha / (alpha + beta), 6) if (alpha + beta) > 0 else 0.5

    if rule_id is not None:
        if rule_id not in rules_map:
            empty = _new_rollup_rule_entry()
            empty["alpha"] = 1.0
            empty["beta"] = 1.0
            empty["mean"] = 0.5
            return empty
        return rules_map[rule_id]
    return rules_map


def compute_cell_fitness(
    cell_or_workspace: Any,
    rule_id: Optional[str] = None,
    workspace: Path | str | None = None,
) -> float:
    """Compute cell/rule fitness incorporating both active signals.jsonl and checkpoint_rollup.json.

    Supports both:
    - compute_cell_fitness(cell_dict[, workspace=...])
    - compute_cell_fitness(workspace, rule_id)
    """
    from aegis_core.scoring import compute_cell_fitness as _scoring_cell_fitness, laplace_score

    if isinstance(cell_or_workspace, dict):
        cell = dict(cell_or_workspace)
        ws = workspace
        rid = rule_id or cell.get("_name") or cell.get("id") or cell.get("rule_id")
        if ws is not None and rid:
            stats = get_rule_stats(ws, str(rid))
            helped = float(stats.get("alpha_delta", stats.get("helped", 0)))
            harmed = float(stats.get("beta_delta", stats.get("harmed", 0)))
            total = max(float(stats.get("applied", 0)), helped + harmed)
            if total > 0:
                impact_weight = float(cell.get("impact_weight", 1.0) or 1.0)
                return laplace_score(helped, helped + harmed, impact_weight)
        return _scoring_cell_fitness(cell)

    ws_target = workspace if workspace is not None else cell_or_workspace
    target_rule = rule_id
    if target_rule is None and isinstance(cell_or_workspace, str) and workspace is not None:
        target_rule = cell_or_workspace
        ws_target = workspace
    if not target_rule:
        return 0.5
    stats = get_rule_stats(ws_target, str(target_rule))
    return float(stats.get("mean", 0.5))


def compact_signals(
    workspace: Path | str | None = None,
    retention_days: int = 30,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Compact expired signals older than retention_days into gzip archives and checkpoint_rollup.json."""
    ws_path = Path(workspace).resolve() if workspace is not None else Path(resolve_workspace()).resolve()
    telemetry_dir = ws_path / ".aegis" / "telemetry"
    evidence_dir = ws_path / ".aegis" / "evidence"

    telemetry_signals = telemetry_dir / SIGNALS_FILENAME
    evidence_signals = evidence_dir / SIGNALS_FILENAME

    source_files: list[Path] = []
    if telemetry_signals.is_file():
        source_files.append(telemetry_signals)
    if evidence_signals.is_file():
        source_files.append(evidence_signals)

    raw_records: list[dict] = []
    if source_files:
        primary_source = source_files[0]
        with open(primary_source, "r", encoding="utf-8", errors="surrogatepass") as f:
            for line in f:
                line_str = line.strip()
                if not line_str:
                    continue
                try:
                    rec = json.loads(line_str)
                    if isinstance(rec, dict):
                        raw_records.append(rec)
                except Exception:
                    continue

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=int(retention_days))

    expired: list[dict] = []
    retained: list[dict] = []
    for rec in raw_records:
        ts_val = rec.get("timestamp") or rec.get("created_at") or rec.get("ts")
        dt = _parse_signal_timestamp(ts_val)
        if dt is not None and dt < cutoff:
            expired.append(rec)
        else:
            retained.append(rec)

    rollup = load_checkpoint_rollup(ws_path)
    rules_map: dict[str, dict[str, Any]] = {}
    for rid, counts in (rollup.get("rules") or {}).items():
        if isinstance(counts, dict):
            rules_map[rid] = {
                "applied": int(counts.get("applied", 0)),
                "helped": int(counts.get("helped", 0)),
                "harmed": int(counts.get("harmed", 0)),
                "ignored": int(counts.get("ignored", 0)),
                "alpha_delta": float(counts.get("alpha_delta", 0.0)),
                "beta_delta": float(counts.get("beta_delta", 0.0)),
            }

    for rec in expired:
        _accumulate_record_into_rules(rules_map, rec)

    compacted_total = int(rollup.get("compacted_count", 0)) + len(expired)
    last_compacted_at = now.strftime("%Y-%m-%dT%H:%M:%SZ") if expired else rollup.get("last_compacted_at", "")
    updated_rollup = {
        "rules": rules_map,
        "compacted_count": compacted_total,
        "last_compacted_at": last_compacted_at,
    }

    archive_paths: list[str] = []
    rollup_path = telemetry_dir / CHECKPOINT_ROLLUP_FILENAME

    if not dry_run and expired:
        # Group expired lines by YYYY-MM
        by_month: dict[str, list[str]] = {}
        for rec in expired:
            ts_val = rec.get("timestamp") or rec.get("created_at") or rec.get("ts")
            dt = _parse_signal_timestamp(ts_val)
            month_key = dt.strftime("%Y-%m") if dt is not None else now.strftime("%Y-%m")
            by_month.setdefault(month_key, []).append(json.dumps(rec, ensure_ascii=False) + "\n")

        target_dirs = [telemetry_dir]
        if evidence_dir.is_dir() or evidence_signals.is_file():
            target_dirs.append(evidence_dir)

        retained_bytes = "".join(
            json.dumps(rec, ensure_ascii=False) + "\n" for rec in retained
        ).encode("utf-8", errors="surrogatepass")
        rollup_bytes = (json.dumps(updated_rollup, indent=2, ensure_ascii=False) + "\n").encode(
            "utf-8", errors="surrogatepass"
        )

        for tdir in target_dirs:
            arch_dir = tdir / "archive"
            arch_dir.mkdir(parents=True, exist_ok=True)
            for month_key, lines in sorted(by_month.items()):
                gz_path = arch_dir / f"signals-{month_key}.jsonl.gz"
                existing_text = ""
                if gz_path.is_file():
                    try:
                        with gzip.open(gz_path, "rt", encoding="utf-8", errors="surrogatepass") as gf:
                            existing_text = gf.read()
                    except Exception:
                        existing_text = ""
                combined_bytes = (existing_text + "".join(lines)).encode("utf-8", errors="surrogatepass")
                _atomic_replace_bytes(str(gz_path), gzip.compress(combined_bytes))
                if tdir == telemetry_dir:
                    archive_paths.append(str(gz_path))

            _atomic_replace_bytes(str(tdir / CHECKPOINT_ROLLUP_FILENAME), rollup_bytes)
            _atomic_replace_bytes(str(tdir / SIGNALS_FILENAME), retained_bytes)

        invalidate_signals_cache()

    return {
        "workspace": str(ws_path),
        "dry_run": dry_run,
        "retention_days": int(retention_days),
        "expired_count": len(expired),
        "retained_count": len(retained),
        "compacted_count": len(expired),
        "total_compacted": compacted_total,
        "archive_files": archive_paths,
        "rollup_path": str(rollup_path),
        "rollup": updated_rollup,
    }



def _read_existing_events(log_path: str) -> tuple[bytes, dict[str, dict]]:
    try:
        st = os.stat(log_path)
    except FileNotFoundError:
        _SIGNALS_CACHE.pop(log_path, None)
        return b'', {}

    fingerprint = (st.st_ino, st.st_mtime_ns, st.st_size)
    cached = _SIGNALS_CACHE.get(log_path)
    if cached is not None and cached[0] == fingerprint:
        return cached[1], dict(cached[2])

    try:
        with open(log_path, 'rb') as f:
            raw = f.read()
    except FileNotFoundError:
        _SIGNALS_CACHE.pop(log_path, None)
        return b'', {}

    by_id: dict[str, dict] = {}
    for line in raw.splitlines():
        try:
            record = json.loads(line.decode('utf-8', errors='surrogatepass'))
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
        if isinstance(record, dict) and record.get('event_id'):
            by_id.setdefault(record['event_id'], record)
    _SIGNALS_CACHE[log_path] = (fingerprint, raw, dict(by_id))
    return raw, by_id


def _atomic_replace_bytes(path: str, data: bytes) -> None:
    from aegis_core.storage import fsync_dir
    parent = os.path.dirname(os.path.abspath(path))
    os.makedirs(parent, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix='.signals.', suffix='.tmp', dir=parent)
    try:
        with os.fdopen(fd, 'wb') as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_path, path)
        fsync_dir(parent)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _migration_in_progress(workspace: str) -> bool:
    layout = WorkspaceLayout(Path(str(workspace)))
    return (
        os.path.exists(str(layout.lock_file(LockResource.MIGRATION)))
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
            new_bytes = prefix + payload
            _atomic_replace_bytes(log_path, new_bytes)
            try:
                st = os.stat(log_path)
                _SIGNALS_CACHE[log_path] = (
                    (st.st_ino, st.st_mtime_ns, st.st_size),
                    new_bytes,
                    dict(planned_by_id),
                )
            except OSError:
                _SIGNALS_CACHE.pop(log_path, None)
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


# ── Metrics Snapshot, Quorum, Coverage & Governance Grade ──────────────────
from aegis_core.metrics import (
    resolve_metrics_dir,
    compute_token_census,
    take_snapshot,
    evaluate_quorum,
    calculate_coverage,
    calculate_cell_coverage,
    calculate_rule_coverage,
    letter_grade,
    calculate_governance_grade,
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
    "load_signals",
    "invalidate_signals_cache",
    "load_checkpoint_rollup",
    "get_rule_stats",
    "compute_cell_fitness",
    "compact_signals",
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
    "calculate_rule_coverage",
    "letter_grade",
    "calculate_governance_grade",
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


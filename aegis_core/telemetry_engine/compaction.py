"""Segmented telemetry signal compaction and gzip archiving."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import gzip
import json
from pathlib import Path
from typing import Any, Optional

from aegis_core.telemetry_engine.ledger import (
    _atomic_replace_bytes,
    _cfg_signals_filename,
    invalidate_signals_cache,
)
from aegis_core.telemetry_engine.rollup import (
    CHECKPOINT_ROLLUP_FILENAME,
    _update_checkpoint_rollup_unlocked,
)
from aegis_core.workspace import resolve_workspace


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


def compact_signals(
    workspace: Path | str | None = None,
    retention_days: int = 30,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Compact expired signals older than retention_days into gzip archives and checkpoint_rollup.json."""
    ws_path = Path(workspace).resolve() if workspace is not None else Path(resolve_workspace()).resolve()
    telemetry_dir = ws_path / ".aegis" / "telemetry"
    evidence_dir = ws_path / ".aegis" / "evidence"
    sig_fname = _cfg_signals_filename()

    telemetry_signals = telemetry_dir / sig_fname
    evidence_signals = evidence_dir / sig_fname

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

    updated_rollup = _update_checkpoint_rollup_unlocked(ws_path, expired, now=now, persist=False)
    compacted_total = int(updated_rollup.get("compacted_count", 0))

    archive_paths: list[str] = []
    rollup_path = telemetry_dir / CHECKPOINT_ROLLUP_FILENAME

    if not dry_run and expired:
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
            _atomic_replace_bytes(str(tdir / sig_fname), retained_bytes)

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


__all__ = [
    "_parse_signal_timestamp",
    "compact_signals",
]

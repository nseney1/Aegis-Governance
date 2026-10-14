"""Canonical, read-only aggregation for Soma signal evidence."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import json
import os
from pathlib import Path
from typing import Dict, Iterator, List, Optional


@dataclass(frozen=True)
class SignalAggregation:
    """Aggregated signal values, parse errors, and normalized trigger events."""

    counts: Dict[str, dict]
    errors: List[dict]
    trigger_events: List[dict]

    def __iter__(self) -> Iterator[object]:
        """Allow ``counts, errors = aggregate_signals(...)`` compatibility."""
        yield self.counts
        yield self.errors


def _new_count() -> dict:
    return {
        "triggers": 0,
        "tp": Decimal("0"),
        "fp": Decimal("0"),
        "last_trigger": None,
        "has_triggers": False,
        "has_outcomes": False,
    }


def _credit_weight(record: dict) -> Optional[Decimal]:
    metadata = record.get("metadata")
    if not isinstance(metadata, dict) or "credit_weight" not in metadata:
        return Decimal("1")
    try:
        weight = Decimal(str(metadata["credit_weight"]))
    except (InvalidOperation, TypeError, ValueError):
        return None
    if not weight.is_finite() or weight < 0 or weight > 10:
        return None
    return weight


def _plain_number(value: Decimal):
    if value == value.to_integral_value():
        return int(value)
    return float(value)


def _cell_id(record: dict) -> Optional[str]:
    value = record.get("cell") or record.get("cell_id")
    if not value:
        cells_used = record.get("cells_used")
        if isinstance(cells_used, list) and cells_used:
            value = cells_used[0]
    if not isinstance(value, str) or not value:
        return None
    return value


def _error(path: str, line: Optional[int], message: str) -> dict:
    return {"file": path, "line": line, "error": message}


def aggregate_signals(evidence_dir: str) -> SignalAggregation:
    """Aggregate only ``signals.jsonl`` into trigger and outcome dimensions.

    Blank rows and an incomplete trailing row are ignored. Malformed complete
    rows are returned as structured errors. TP/FP credit weights are summed as
    ``Decimal`` and converted to plain ``int`` or ``float`` values only after
    the complete ledger has been processed.
    """
    path = os.path.join(os.fspath(evidence_dir), "signals.jsonl")
    counts = {}  # type: Dict[str, dict]
    errors = []  # type: List[dict]
    trigger_events = []  # type: List[dict]

    if not os.path.isfile(path):
        return SignalAggregation(counts, errors, trigger_events)

    try:
        with open(path, "r", encoding="utf-8") as stream:
            for line_no, raw_line in enumerate(stream, 1):
                complete = raw_line.endswith("\n")
                text = raw_line.strip()
                if not text:
                    continue
                try:
                    record = json.loads(text)
                except (json.JSONDecodeError, ValueError) as exc:
                    if complete:
                        errors.append(_error(path, line_no, f"parse failed: {exc}"))
                    continue
                if not isinstance(record, dict):
                    errors.append(_error(path, line_no, "signal row must be a JSON object"))
                    continue

                signal = record.get("signal")
                outcome = record.get("outcome")
                is_trigger = signal == "trigger" or outcome == "trigger"
                effective_outcome = None
                if signal in ("tp", "success", "fp", "failure"):
                    effective_outcome = signal
                elif outcome in ("tp", "success", "fp", "failure"):
                    effective_outcome = outcome
                if not is_trigger and effective_outcome is None:
                    cell_id = _cell_id(record)
                    if cell_id is not None:
                        counts.setdefault(cell_id, _new_count())
                    continue

                cell_id = _cell_id(record)
                if cell_id is None:
                    errors.append(_error(path, line_no, "signal row requires a non-empty cell id"))
                    continue

                entry = counts.setdefault(cell_id, _new_count())
                if is_trigger:
                    timestamp = record.get("timestamp") or record.get("triggered_at")
                    timestamp_text = str(timestamp) if timestamp is not None else None
                    entry["has_triggers"] = True
                    entry["triggers"] += 1
                    if timestamp_text is not None and (
                        entry["last_trigger"] is None
                        or timestamp_text > entry["last_trigger"]
                    ):
                        entry["last_trigger"] = timestamp_text
                    trigger_events.append({"cell": cell_id, "timestamp": timestamp_text})

                if effective_outcome is not None:
                    entry["has_outcomes"] = True
                    weight = _credit_weight(record)
                    if weight is None:
                        errors.append(_error(
                            path, line_no,
                            "metadata.credit_weight must be a finite number",
                        ))
                        continue
                    if effective_outcome in ("tp", "success"):
                        entry["tp"] += weight
                    else:
                        entry["fp"] += weight
    except (OSError, UnicodeError) as exc:
        errors.append(_error(path, None, f"read failed: {exc}"))

    for entry in counts.values():
        entry["tp"] = _plain_number(entry["tp"])
        entry["fp"] = _plain_number(entry["fp"])
    return SignalAggregation(counts, errors, trigger_events)


def log_finding(
    severity: str,
    rule: str,
    change: str,
    source: str,
    logs_dir: Path | None = None,
) -> int:
    """Log a governance finding to audit trail."""
    from datetime import datetime, timezone
    from pathlib import Path
    import sys

    severity_lower = severity.lower()
    if severity_lower not in ("critical", "warning", "nit", "info"):
        print(f"Warning: Unknown severity '{severity}', defaulting to warning", file=sys.stderr)

    resolved_home = Path.home()
    if logs_dir:
        base_logs = Path(logs_dir)
    elif os.environ.get("SOMA_LOGS_DIR"):
        base_logs = Path(os.environ["SOMA_LOGS_DIR"])
    else:
        base_logs = resolved_home / ".gemini" / "antigravity" / "scratch" / "ai-conversation-logs"

    gov_dir = base_logs / "governance"
    gov_dir.mkdir(parents=True, exist_ok=True)

    auto_log = gov_dir / "auto_applied_log.jsonl"
    critical_file = gov_dir / "pending_critical.md"
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    record = {
        "timestamp": timestamp,
        "severity": severity_lower,
        "rule": rule,
        "change": change,
        "source": source,
    }

    try:
        with open(auto_log, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
    except Exception as e:
        print(f"Error writing to audit log {auto_log}: {e}", file=sys.stderr)
        return 1

    if severity_lower == "critical":
        try:
            entry = f"\n### 🔴 CRITICAL: {rule} ({timestamp})\n- **Change**: {change}\n- **Source**: {source}\n"
            with open(critical_file, "a", encoding="utf-8") as f:
                f.write(entry)
        except Exception as e:
            print(f"Error writing to critical findings file {critical_file}: {e}", file=sys.stderr)
            return 1

    print(f"✅ Logged {severity_lower} finding for {rule}")
    return 0


__all__ = [
    "SignalAggregation",
    "aggregate_signals",
    "log_finding",
]


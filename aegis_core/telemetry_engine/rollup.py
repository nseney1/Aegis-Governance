"""Checkpoint rollup aggregation and Bayesian rule fitness calculation."""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Iterable, Optional

from aegis_core.telemetry_engine.ledger import _atomic_replace_bytes, read_signals
from aegis_core.workspace import resolve_workspace

CHECKPOINT_ROLLUP_FILENAME = "checkpoint_rollup.json"


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


def _update_checkpoint_rollup_unlocked(
    workspace: Path | str,
    records: Iterable[dict] = (),
    *,
    now: Optional[datetime] = None,
    persist: bool = False,
) -> dict[str, Any]:
    """Merge expired signal records into the workspace checkpoint rollup."""
    ws_path = Path(workspace).resolve()
    record_list = list(records)
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

    for rec in record_list:
        _accumulate_record_into_rules(rules_map, rec)

    ts_now = now or datetime.now(timezone.utc)
    compacted_total = int(rollup.get("compacted_count", 0)) + len(record_list)
    last_compacted_at = ts_now.strftime("%Y-%m-%dT%H:%M:%SZ") if record_list else rollup.get("last_compacted_at", "")
    updated_rollup = {
        "rules": rules_map,
        "compacted_count": compacted_total,
        "last_compacted_at": last_compacted_at,
    }
    if persist:
        rollup_bytes = (json.dumps(updated_rollup, indent=2, ensure_ascii=False) + "\n").encode(
            "utf-8", errors="surrogatepass"
        )
        _atomic_replace_bytes(str(ws_path / ".aegis" / "evidence" / CHECKPOINT_ROLLUP_FILENAME), rollup_bytes)
    return updated_rollup


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


def compute_rule_fitness(
    cell_or_workspace: Any,
    rule_id: Optional[str] = None,
    workspace: Path | str | None = None,
) -> float:
    """Compute rule/cell fitness incorporating both active signals.jsonl and checkpoint_rollup.json."""
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


compute_cell_fitness = compute_rule_fitness


def get_workspace_rule_fitness(
    workspace: Path | str | None = None,
    rule_id: Optional[str] = None,
) -> Any:
    """Return rule fitness for a specific rule_id (float) or all rules in workspace (dict[str, float])."""
    if rule_id is not None:
        return compute_rule_fitness(workspace, rule_id=rule_id)
    stats_map = get_rule_stats(workspace)
    return {rid: float(entry.get("mean", 0.5)) for rid, entry in stats_map.items() if isinstance(entry, dict)}


__all__ = [
    "CHECKPOINT_ROLLUP_FILENAME",
    "_accumulate_record_into_rules",
    "_extract_rule_ids",
    "_new_rollup_rule_entry",
    "_update_checkpoint_rollup_unlocked",
    "compute_cell_fitness",
    "compute_rule_fitness",
    "get_rule_stats",
    "get_workspace_rule_fitness",
    "load_checkpoint_rollup",
]

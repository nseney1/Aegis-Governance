"""aegis_core.telemetry — Unified telemetry, evidence signals, outcome reflection, and metrics facade."""
from __future__ import annotations

import sys
import types
from typing import Any

from aegis_core.metrics import (
    calculate_cell_coverage, calculate_coverage, calculate_governance_grade,
    calculate_immune_grade, calculate_rule_coverage, compute_token_census,
    evaluate_quorum, letter_grade, resolve_metrics_dir, take_snapshot,
)
from aegis_core.outcomes import (
    DEFAULT_PLATFORM, INSIGHT_PRINCIPAL, INSIGHT_SCOPE, PLATFORMS, VERIFY_TIMEOUT,
    _as_int, _get_changed_files, _insight_cursor_path, _read_insight_cursor, _run_verify,
    append_fitness_log, capture_build_outcome, capture_git_signals,
    capture_human_insight_signals, capture_mcp_outcomes, capture_test_outcome,
    commit_insight_cursor, compute_credit_weights, compute_fitness_signals,
    detect_platform, detect_test_runner, extract_modified_files, match_cells,
    match_cells_to_changes, read_human_insight_signals, resolve_transcript_id,
    run_outcome_engine, to_fraction, update_cell_fitness, update_fitness,
)
from aegis_core.telemetry_engine import (
    CHECKPOINT_ROLLUP_FILENAME, DEFAULT_GENERATION, EPOCH_FILENAME, EventConflictError,
    LOCK_FILENAME, SIGNALS_FILENAME, StaleGenerationError, VALID_SIGNAL_TYPES,
    VALID_SOURCES, _MSVCRT_RETRY_SECONDS, _SIGNALS_CACHE, _accumulate_record_into_rules,
    _atomic_replace_bytes, _extract_rule_ids, _lock_tls, _migration_in_progress,
    _new_rollup_rule_entry, _normalize_signal_record, _parse_signal_timestamp,
    _read_existing_events, _resolve_evidence_dir, _update_checkpoint_rollup_unlocked,
    _validate_event, append_signal, append_signals, compact_signals,
    compute_cell_fitness, compute_event_id, compute_payload_digest,
    compute_rule_fitness, current_generation, evidence_lock, get_lock_path,
    get_rule_stats, get_signals_path, get_workspace_rule_fitness,
    increment_generation, invalidate_signals_cache, load_checkpoint_rollup,
    load_signals, read_generation, read_signals,
)
from aegis_core.workspace import resolve_workspace


def main(*args, **kwargs) -> int:
    return run_outcome_engine(*args, mod=sys.modules[__name__], **kwargs)


__all__ = [
    "VALID_SIGNAL_TYPES", "VALID_SOURCES", "SIGNALS_FILENAME", "LOCK_FILENAME",
    "EPOCH_FILENAME", "DEFAULT_GENERATION", "EventConflictError", "StaleGenerationError",
    "evidence_lock", "read_generation", "current_generation", "increment_generation",
    "get_signals_path", "get_lock_path", "read_signals", "load_signals",
    "invalidate_signals_cache", "load_checkpoint_rollup", "get_rule_stats",
    "compute_cell_fitness", "compute_rule_fitness", "get_workspace_rule_fitness",
    "compact_signals", "compute_payload_digest", "compute_event_id",
    "append_signals", "append_signal", "detect_test_runner", "capture_test_outcome",
    "capture_build_outcome", "capture_git_signals", "capture_mcp_outcomes",
    "capture_human_insight_signals", "read_human_insight_signals", "commit_insight_cursor",
    "match_cells_to_changes", "to_fraction", "compute_credit_weights",
    "compute_fitness_signals", "update_cell_fitness", "append_fitness_log",
    "run_outcome_engine", "main", "INSIGHT_PRINCIPAL", "INSIGHT_SCOPE",
    "VERIFY_TIMEOUT", "_get_changed_files", "_read_insight_cursor", "_run_verify",
    "PLATFORMS", "DEFAULT_PLATFORM", "detect_platform", "resolve_transcript_id",
    "extract_modified_files", "match_cells", "update_fitness", "resolve_metrics_dir",
    "compute_token_census", "take_snapshot", "evaluate_quorum", "calculate_coverage",
    "calculate_cell_coverage", "calculate_rule_coverage", "letter_grade",
    "calculate_governance_grade", "calculate_immune_grade", "resolve_workspace",
]


class _TelemetryFacadeModule(types.ModuleType):
    """Module proxy that mirrors attribute mutations down to canonical submodules."""

    def __setattr__(self, name: str, value: Any) -> None:
        super().__setattr__(name, value)
        for mod_name in (
            "aegis_core.telemetry_engine.ledger",
            "aegis_core.telemetry_engine.rollup",
            "aegis_core.telemetry_engine.compaction",
            "aegis_core.outcomes",
            "aegis_core.metrics",
        ):
            mod = sys.modules.get(mod_name)
            if mod is not None and hasattr(mod, name):
                setattr(mod, name, value)


sys.modules[__name__].__class__ = _TelemetryFacadeModule

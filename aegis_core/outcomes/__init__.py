"""aegis_core.outcomes — Verifiable outcome reflection, credit assignment, and ACE reflector loop."""
from __future__ import annotations

from aegis_core.outcomes.engine import (
    _get_changed_files,
    main,
    match_cells_to_changes,
    run_outcome_engine,
)
from aegis_core.outcomes.fitness import (
    DEFAULT_PLATFORM,
    INSIGHT_PRINCIPAL,
    INSIGHT_SCOPE,
    PLATFORMS,
    _as_int,
    _get_platform_config,
    append_fitness_log,
    compute_credit_weights,
    compute_fitness_signals,
    detect_platform,
    extract_modified_files,
    match_cells,
    resolve_transcript_id,
    to_fraction,
    update_cell_fitness,
    update_fitness,
)
from aegis_core.outcomes.harvest import (
    capture_git_signals,
    harvest_git_history,
)
from aegis_core.outcomes.insights import (
    _insight_cursor_path,
    _read_insight_cursor,
    capture_human_insight_signals,
    commit_insight_cursor,
    read_human_insight_signals,
)
from aegis_core.outcomes.telemetry import (
    VERIFY_TIMEOUT,
    _run_verify,
    capture_build_outcome,
    capture_mcp_outcomes,
    capture_test_outcome,
    detect_test_runner,
    record_verification_telemetry,
)

__all__ = [
    "VERIFY_TIMEOUT",
    "_run_verify",
    "detect_test_runner",
    "capture_test_outcome",
    "capture_build_outcome",
    "capture_git_signals",
    "capture_mcp_outcomes",
    "_insight_cursor_path",
    "_read_insight_cursor",
    "commit_insight_cursor",
    "capture_human_insight_signals",
    "read_human_insight_signals",
    "_as_int",
    "_get_changed_files",
    "_parse_frontmatter",
    "match_cells_to_changes",
    "to_fraction",
    "compute_credit_weights",
    "compute_fitness_signals",
    "update_cell_fitness",
    "INSIGHT_PRINCIPAL",
    "INSIGHT_SCOPE",
    "append_fitness_log",
    "run_outcome_engine",
    "main",
    "PLATFORMS",
    "DEFAULT_PLATFORM",
    "detect_platform",
    "resolve_transcript_id",
    "extract_modified_files",
    "match_cells",
    "update_fitness",
    "record_verification_telemetry",
    "harvest_git_history",
]

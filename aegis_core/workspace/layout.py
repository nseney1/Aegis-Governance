"""Canonical filesystem layout registry for Aegis workspaces."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


class LockResource:
    RULES = "rules"
    EVIDENCE = "evidence"
    SIGNALS = "signals"
    FITNESS = "fitness"
    RECEIPTS = "receipts"
    MIGRATION = "migration"
    SWARM = "swarm"
    PACKS = "packs"


# Machine-local runtime state the current layout writes under .aegis/, as patterns for
# .aegis/.gitignore. Anchored with "/" so a rule subdirectory that happens to share a
# name (rules/traps/evidence/) stays committable. rules/ and config files are absent
# on purpose: they are reviewed and committed.
RUNTIME_STATE_IGNORES: tuple[str, ...] = (
    "/evidence/",          # signals ledger, outcomes, rollups, ledger locks
    "/telemetry/",         # compaction output, skill handoff telemetry
    "/metrics/",           # escaped defects, transfers
    "/governance/",        # gate events
    "/locks/",
    "/keys/",              # manifest and receipt HMAC keys
    "/quarantine/",
    "/swarm/",             # leases, handoff tickets
    "/handoffs/",
    "/receipt_key",        # legacy HMAC key, still read in preference to keys/
    "/receipts.jsonl",
    "/human_insights.jsonl",
    "/insight_cursor",
    "/jobs_state.json",
    "/epoch_generation",
    "/migration.lock",
    "/*.tmp",              # atomic-write temp files left by a crash
)


@dataclass(frozen=True)
class WorkspaceLayout:
    root: Path

    def __post_init__(self) -> None:
        if not isinstance(self.root, Path):
            object.__setattr__(self, "root", Path(self.root).resolve())

    @property
    def aegis_dir(self) -> Path:
        return self.root / ".aegis"

    @property
    def rules_dir(self) -> Path:
        return self.aegis_dir / "rules"

    @property
    def evidence_dir(self) -> Path:
        return self.aegis_dir / "evidence"

    @property
    def evidence_archive_dir(self) -> Path:
        return self.evidence_dir / "archive"

    @property
    def locks_dir(self) -> Path:
        return self.aegis_dir / "locks"

    @property
    def governance_dir(self) -> Path:
        return self.aegis_dir / "governance"

    @property
    def keys_dir(self) -> Path:
        return self.aegis_dir / "keys"

    @property
    def metrics_dir(self) -> Path:
        return self.aegis_dir / "metrics"

    @property
    def quarantine_dir(self) -> Path:
        return self.aegis_dir / "quarantine"

    @property
    def skills_dir(self) -> Path:
        return self.aegis_dir / "skills"

    @property
    def swarm_dir(self) -> Path:
        return self.aegis_dir / "swarm"

    @property
    def handoffs_dir(self) -> Path:
        return self.swarm_dir / "handoffs"

    # Canonical files
    @property
    def signals_file(self) -> Path:
        return self.evidence_dir / "signals.jsonl"

    @property
    def checkpoint_rollup_file(self) -> Path:
        return self.evidence_dir / "checkpoint_rollup.json"

    @property
    def evidence_outcomes_file(self) -> Path:
        return self.evidence_dir / "outcomes.jsonl"

    @property
    def outcomes_file(self) -> Path:
        return self.aegis_dir / "outcomes.jsonl"

    @property
    def receipts_file(self) -> Path:
        return self.aegis_dir / "receipts.jsonl"

    @property
    def leases_file(self) -> Path:
        return self.swarm_dir / "leases.json"

    @property
    def gate_events_file(self) -> Path:
        return self.governance_dir / "gate_events.jsonl"

    @property
    def human_insights_file(self) -> Path:
        return self.aegis_dir / "human_insights.jsonl"

    @property
    def debrief_queue_file(self) -> Path:
        return self.root / "governance" / "debrief_queue.jsonl"

    @property
    def manifest_file(self) -> Path:
        return self.rules_dir / "manifest.json"

    @property
    def manifest_key_file(self) -> Path:
        return self.keys_dir / "manifest.key"

    @property
    def slots_file(self) -> Path:
        return self.aegis_dir / "slots.yaml"

    def lock_file(self, resource: str) -> Path:
        return self.locks_dir / f"{resource}.lock"


__all__ = ["LockResource", "RUNTIME_STATE_IGNORES", "WorkspaceLayout"]

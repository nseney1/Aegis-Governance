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
    def locks_dir(self) -> Path:
        return self.aegis_dir / "locks"

    @property
    def keys_dir(self) -> Path:
        return self.aegis_dir / "keys"

    @property
    def metrics_dir(self) -> Path:
        return self.aegis_dir / "metrics"

    @property
    def skills_dir(self) -> Path:
        return self.aegis_dir / "skills"

    # Canonical files
    @property
    def signals_file(self) -> Path:
        return self.evidence_dir / "signals.jsonl"

    @property
    def manifest_file(self) -> Path:
        return self.rules_dir / "manifest.json"

    @property
    def manifest_key_file(self) -> Path:
        return self.keys_dir / "manifest.key"

    def lock_file(self, resource: str) -> Path:
        return self.locks_dir / f"{resource}.lock"


__all__ = ["LockResource", "RUNTIME_STATE_IGNORES", "WorkspaceLayout"]

---
id: invariant-single-canonical-ledger
domain: correctness
type: invariant
enforcement: gate
hypothesis: "A ledger with two candidate files, unlocked read-modify-write, intolerant reads or random idempotency keys silently loses, duplicates or inflates outcome records"
prediction: "Every ledger reader and writer resolves one path from WorkspaceLayout, mutates it only under evidence_lock, reads bad bytes line by line and uses deterministic or required idempotency keys"
falsification: "0 findings in 15 sessions: prune"
expiry_sessions: 15
expiry_days: 60
created: "2026-10-15T16:11:59Z"
impact_weight: 1.0
tags: ["debrief", "citadel", "ledger", "locking"]
target_paths: ["aegis_core/telemetry_engine/ledger.py", "aegis_core/workspace/layout.py", "aegis_mcp/handlers/governance.py", "aegis_mcp/handlers/telemetry.py", "tests/unit/core/**"]
lineage:
  parent_id: null
  created_by: "manual"
  generation: 0
  siblings: []
---
# Invariant: one canonical ledger, mutated only under its lock

**Rule**: A ledger has exactly one canonical file. Every reader, writer and
compactor resolves it from `WorkspaceLayout` and mutates it only inside
`evidence_lock`. Reads tolerate bad bytes and a BOM line by line. Idempotency
keys are deterministic or required, never random. Each mutation path has a
multi-round test with appends between rounds.

## Incident (v4 Citadel review)

- `compact_signals` read `telemetry/` first while live writers used
  `evidence/`, then wrote the same bytes to both, so a stale snapshot overwrote
  the live ledger (6 records to 0). It ran without `evidence_lock`, so
  concurrent appends were lost.
- One invalid UTF-8 byte killed `read_signals`, `get_rule_stats` and compaction,
  and a BOM dropped the first record. `append_signals` rewrote and fsynced the
  whole file on every call.
- `aegis_report_outcome` generated a random uuid4 idempotency key when none was
  given, so retries inflated fitness counts, and a call with no rule ids
  silently recorded nothing.
- It was missed because compaction was tested only as a single run against one
  directory, with no two-round, interleaved-append or concurrent-writer test,
  and the writer and reader paths never had to share one path constant.

v4.0 deleted compaction and rollup (D7, #22). The ledger stays and gets
versioned rows in wave B2 (D13).

## Check

1. Every reference to a ledger file in `aegis_*` resolves its path through
   `WorkspaceLayout`; a second literal path to the same ledger fails review.
2. Every write path holds `evidence_lock`. Test: two writers append N rows each
   and all 2N rows survive.
3. A ledger with a BOM and one invalid byte still yields every valid row.
4. Reporting the same outcome twice records one row.

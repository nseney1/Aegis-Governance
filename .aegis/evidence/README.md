# Evidence Directory

Runtime fitness data for the Soma governance system.

## Files

- `fitness.jsonl` — Per-cell trigger records (one line per cell-trigger-per-session)
- `sessions_processed.jsonl` — Idempotency ledger (prevents double-counting)

## Schema

### fitness.jsonl
```json
{"cell_id": "trap-hardcoded-paths", "transcript_id": "abc123", "triggered_at": "2026-09-30T14:00:00Z", "matched_files": ["enzymes/cell_create.sh"]}
```

### sessions_processed.jsonl
```json
{"transcript_id": "abc123", "processed_at": "2026-09-30T14:01:00Z", "cells_triggered": 3}
```

## Reproducibility

These files are **gitignored** because they are deterministically reproducible
from the transcript archive. If files are lost or suspected of tampering:

```bash
# Re-run fitness updater on all transcripts
for t in ~/.gemini/antigravity/brain/*/.system_generated/logs/transcript.jsonl; do
    python3 enzymes/fitness_updater.py "$t"
done
```

---
id: trap-fix-one-not-all
domain: correctness
type: trap
enforcement: advisory
hypothesis: "When a pattern is fixed in one file, the same pattern exists in sibling files"
prediction: Fixing a bug in one enzyme without grepping for the same pattern across all enzymes leads to partial fixes that auditors catch later
falsification: "If 10 consecutive multi-file bug fixes all pass the refactoring sweep check on first attempt, this vacuole is unnecessary"
target_paths:
  - "aegis_core/*.py"
  - "aegis_cli/*.py"
  - "aegis_mcp/*.py"
  - "tests/*.py"
triggers:
  - pattern_fix
  - bug_fix
  - refactor
minimum_mode: standard
expiry_sessions: 30
expiry_days: 90
fitness:
  score: 0.5714
  impact_weight: 1.0
  triggers: 76
  true_positives: 29.5383
  false_positives: 30.3898
  last_trigger_date: "2026-10-14T08:55:41Z"
---

# Refactoring Sweep: Fix One → Fix All

When fixing a pattern in one file, **grep for the same pattern across all sibling files** before closing the fix.

## Evidence

This vacuole was created after audit round 4 (2026-09-30) found the same
`id`/`domain` omission bug in `cell_create.sh` and `hgt_ribosome.py` that
had already been fixed in `cell_create_nl.py`. The fix was applied to one
file but not propagated to the other two, requiring a second audit round
to catch the gap.

## Rule

Before marking a bug fix as complete:

1. **Identify the pattern**: What specific code pattern was the bug?
2. **Search siblings**: `grep -rn '<pattern>' enzymes/ aegis_mcp/ tests/`
3. **Fix all instances**: Apply the same fix to every occurrence
4. **Verify**: Run the full test suite after all instances are fixed

## Anti-patterns

- Fixing `cell_create_nl.py` but not `cell_create.sh` or `hgt_ribosome.py`
- Removing an import guard in 27/28 files
- Adding a frontmatter field to new cells but not existing cells
- Updating a function signature in the definition but not all call sites

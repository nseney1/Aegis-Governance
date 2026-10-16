---
id: trap-fix-one-not-all
domain: correctness
type: trap
enforcement: advisory
hypothesis: "When a pattern is fixed in one file, the same pattern exists in sibling files"
prediction: Fixing a bug in one module without grepping for the same pattern across all modules leads to partial fixes that auditors catch later
falsification: "If 10 consecutive multi-file bug fixes all pass the refactoring sweep check on first attempt, this trap is unnecessary"
target_paths:
  - "aegis_core/*.py"
  - "aegis_cli/*.py"
  - "aegis_mcp/*.py"
  - "tests/*.py"
triggers:
  - pattern_fix
  - bug_fix
  - refactor
minimum_mode: patrol
expiry_sessions: 30
expiry_days: 90
impact_weight: 1.0
---

# Refactoring Sweep: Fix One → Fix All

When fixing a pattern in one file, **grep for the same pattern across all sibling files** before closing the fix.

## Evidence

This trap was created after audit round 4 (2026-09-30) found the same
`id`/`domain` omission bug in `aegis_cli/create.py` and `aegis_core/import_export.py` that
had already been fixed in `aegis_mcp/tools.py`. The fix was applied to one
file but not propagated to the other two, requiring a second audit round
to catch the gap.

## Rule

Before marking a bug fix as complete:

1. **Identify the pattern**: What specific code pattern was the bug?
2. **Search siblings**: `grep -rn '<pattern>' aegis_cli/ aegis_core/ aegis_mcp/ tests/`
3. **Fix all instances**: Apply the same fix to every occurrence
4. **Verify**: Run the full test suite after all instances are fixed

## Anti-patterns

- Fixing `aegis_mcp/tools.py` but not `aegis_cli/create.py` or `aegis_core/import_export.py`
- Removing an import guard in 27/28 files
- Adding a frontmatter field to new rules but not existing rules
- Updating a function signature in the definition but not all call sites

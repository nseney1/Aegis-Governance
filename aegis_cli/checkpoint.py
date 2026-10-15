"""The workspace checkpoint inside `aegis check`: repo-wide deterministic checks.

The checks live in aegis_core.verification.checkpoint_checks: a test file per
source file, hardcoded absolute paths, per-test assertions (AST), rule fitness
from the ledger, rule conventions, and invariant/wall rules that do not use
`gate` enforcement ("paper walls").

Issues are warnings unless --strict. A paper wall always blocks: it is a rule
that claims to be a gate but enforces nothing.
"""
from __future__ import annotations

from pathlib import Path

from aegis_core.verification.checkpoint_checks import run_all_checks

__all__ = ["GATE_CHECKS", "is_blocking", "run_checkpoint"]

GATE_CHECKS = frozenset({"paper_walls"})


def is_blocking(issue: dict, strict: bool) -> bool:
    return strict or issue.get("check") in GATE_CHECKS


def run_checkpoint(root: Path, *, strict: bool) -> tuple[list[dict], bool]:
    """Run every checkpoint check on *root*; return (issues, blocking)."""
    issues = run_all_checks(root)
    return issues, any(is_blocking(issue, strict) for issue in issues)

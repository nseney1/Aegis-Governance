"""Release Gate 4.5 verification and dirty-tree inspection helpers."""
from __future__ import annotations

import subprocess

__all__ = ["_is_dirty", "verify_release_gate"]


def _is_dirty(line: str) -> bool:
    """Check if a porcelain git status line represents a dirty code change."""
    parts = line.strip().split(maxsplit=1)
    if len(parts) < 2:
        return False
    path = parts[1].strip()
    # Ignore aegis runtime evidence, metrics, locks, and telemetry
    if (
        path.startswith(".aegis/evidence") or "/.aegis/evidence" in path
        or path.startswith(".aegis/metrics") or "/.aegis/metrics" in path
        or path.startswith(".aegis/telemetry") or "/.aegis/telemetry" in path
        or path.startswith(".aegis/rules") or "/.aegis/rules" in path
        or path.startswith(".aegis/governance") or "/.aegis/governance" in path
        or path.startswith(".aegis/locks") or "/.aegis/locks" in path
        or path == ".aegis/receipts.jsonl"
        or path.endswith("/.aegis/receipts.jsonl")
        or path == ".aegis/human_insights.jsonl"
        or path.endswith("/.aegis/human_insights.jsonl")
    ):
        return False
    # Ignore test runners and python cache artifacts
    if "__pycache__" in path or path.endswith(".pyc"):
        return False
    if ".pytest_cache" in path:
        return False
    return True


def verify_release_gate(repo_root: str) -> tuple[bool, str]:
    """Check Release Gate 4.5: assert latest arbitration evidence is a valid SHIP receipt.

    Returns:
        (passed, message) tuple.
    """
    from aegis_core.verification.review_adapter import get_latest_arbitration_evidence

    cycle_num, data = get_latest_arbitration_evidence(repo_root)
    if not data or cycle_num == 0:
        return False, "Release Gate 4.5 FAIL: No arbitration evidence found in .aegis/evidence/. Run 'aegis verify' first."

    verdict = str(data.get("verdict", "")).lower()
    if verdict != "ship":
        divergences = data.get("divergence_count", 0)
        return False, (
            f"Release Gate 4.5 FAIL: Latest arbitration cycle {cycle_num} verdict is '{verdict.upper()}' "
            f"with {divergences} divergence(s). Must achieve SHIP verdict before release."
        )

    # 1. Clean working tree requirement
    try:
        status_res = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True, text=True, cwd=repo_root, timeout=5,
        )
        if status_res.returncode != 0:
            return False, f"Release Gate 4.5 FAIL: git status check failed: {status_res.stderr.strip()}"

        dirty_lines = [line for line in status_res.stdout.splitlines() if line.strip() and _is_dirty(line)]
        if dirty_lines:
            return False, (
                f"Release Gate 4.5 FAIL: Working tree is dirty ({len(dirty_lines)} modified/untracked files). "
                f"Clean working tree required for release verification."
            )
    except Exception as e:
        return False, f"Release Gate 4.5 FAIL: git status execution failed: {e}"

    # 2. Cryptographic Tree Hash Assertion
    recorded_tree = data.get("tree_hash")
    if not recorded_tree:
        return False, f"Release Gate 4.5 FAIL: Arbitration cycle {cycle_num} missing cryptographic tree_hash binding."

    try:
        tree_res = subprocess.run(
            ["git", "rev-parse", "HEAD^{tree}"],
            capture_output=True, text=True, cwd=repo_root, timeout=5,
        )
        if tree_res.returncode != 0:
            return False, f"Release Gate 4.5 FAIL: git rev-parse HEAD^{{tree}} failed: {tree_res.stderr.strip()}"
        current_tree = tree_res.stdout.strip()
        if current_tree != recorded_tree:
            # Check if differences are strictly within evidence or rules (e.g. committing the receipt)
            diff_res = subprocess.run(
                ["git", "diff-tree", "--name-only", "-r", recorded_tree, current_tree],
                capture_output=True, text=True, cwd=repo_root, timeout=5,
            )
            if diff_res.returncode == 0:
                diff_files = [f.strip() for f in diff_res.stdout.splitlines() if f.strip()]
                non_evidence = [
                    f for f in diff_files
                    if not (
                        f.startswith(".aegis/evidence") or "/.aegis/evidence" in f
                        or f.startswith(".aegis/rules") or "/.aegis/rules" in f
                        or f.startswith(".aegis/governance") or "/.aegis/governance" in f
                    )
                ]
                if non_evidence:
                    return False, (
                        f"Release Gate 4.5 FAIL: Tree hash mismatch. Current tree '{current_tree}' does not match "
                        f"arbitration receipt tree '{recorded_tree}'. Code was modified after verification: "
                        f"{', '.join(non_evidence[:5])}"
                    )
            else:
                return False, (
                    f"Release Gate 4.5 FAIL: Tree hash mismatch. Current tree '{current_tree}' does not match "
                    f"arbitration receipt tree '{recorded_tree}'. Code was modified after verification."
                )
    except Exception as e:
        return False, f"Release Gate 4.5 FAIL: git tree hash resolution failed: {e}"

    # 3. Target File Coverage & Diff Resolution
    git_target = None
    try:
        for cand in ("origin/main...HEAD", "main...HEAD", "origin/develop...HEAD", "HEAD~1"):
            res = subprocess.run(
                ["git", "diff", "--name-only", "--diff-filter=ACMR", cand],
                capture_output=True, text=True, cwd=repo_root, timeout=5,
            )
            if res.returncode == 0:
                git_target = res.stdout.splitlines()
                break
    except Exception as e:
        return False, f"Release Gate 4.5 FAIL: git diff execution failed: {e}"

    if git_target is None:
        return False, "Release Gate 4.5 FAIL: Unable to resolve git diff against base branch."

    py_changed = [
        f.strip() for f in git_target
        if f.strip().endswith(".py")
        and not f.startswith("tests/")
        and not f.endswith("__init__.py")
    ]
    if not py_changed:
        return True, f"Release Gate 4.5 PASS: Arbitration cycle {cycle_num} verified with SHIP verdict (tree {recorded_tree[:8]})."

    recorded_targets = set(data.get("target_files", []))
    if not recorded_targets:
        return False, (
            f"Release Gate 4.5 FAIL: Arbitration cycle {cycle_num} has empty target_files, "
            f"but {len(py_changed)} non-test Python files were modified in branch diff."
        )

    uncovered = [f for f in py_changed if f not in recorded_targets]
    if uncovered:
        return False, (
            f"Release Gate 4.5 FAIL: Arbitration cycle {cycle_num} does not cover changed files: "
            f"{', '.join(uncovered)}"
        )

    return True, f"Release Gate 4.5 PASS: Arbitration cycle {cycle_num} verified with SHIP verdict (tree {recorded_tree[:8]})."

"""aegis_core.enforcement — Canonical enforcement, CI reporting, and invariant verification.

Consolidates:
- Cell enforcement artifact generators (formerly enzymes/cell_enforce.py)
- CI outcome and advisory reporter (formerly enzymes/ci_outcome_reporter.py)
- Bug registry verification gate (formerly enzymes/verify_bug_registry.py)
- README claim verification gate (formerly enzymes/verify_readme_claims.py)
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import fnmatch
import glob
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
from typing import Any, Dict, List, Optional, Tuple, Union

from aegis_core.workspace import Workspace, as_workspace, resolve_workspace

# ── Bug Registry Verification ─────────────────────────────────────────────

VALID_STATUSES = ("open", "fixed")
CORE_FIELDS = (
    "id",
    "title",
    "discovered_in",
    "root_cause",
    "severity",
    "affected_files",
)
FIX_FIELDS = ("fixed_in", "regression_test", "changelog_ref")


def load_registry(workspace: str | Path | Workspace = ".") -> Dict[str, Any]:
    """Load and parse BUG_REGISTRY.json."""
    ws = as_workspace(workspace)
    path = ws.root / "docs" / "project" / "BUG_REGISTRY.json"
    if not path.exists():
        raise FileNotFoundError(f"Bug registry not found at {path}")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


load_bug_registry = load_registry


def bug_status(bug: Dict[str, Any]) -> str:
    return bug.get("status", "fixed")


def _failed_node_ids(pytest_output: str) -> List[str]:
    """Node IDs from pytest's summary lines and error output."""
    nodes = []
    for line in pytest_output.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0] in ("FAILED", "ERROR"):
            nodes.append(parts[1])
        elif "ERROR: not found:" in line:
            nodes.append(line.split("ERROR: not found:")[-1].strip())
    return nodes


def _node_matches(node: str, test_ref: str) -> bool:
    if node == test_ref or node.endswith(test_ref) or node.startswith((test_ref + "[", test_ref + "::")):
        return True
    return "::" not in node and test_ref.split("::")[0] == node


def verify_schema(registry: Dict[str, Any]) -> List[str]:
    """Verify registry schema and required fields."""
    errors = []
    valid_categories = set(registry.get("root_cause_categories", {}).keys())
    valid_severities = set(registry.get("severity_levels", []))

    for bug in registry.get("bugs", []):
        bug_id = bug.get("id", "<unknown>")
        status = bug_status(bug)

        if status not in VALID_STATUSES:
            errors.append(f"{bug_id}: unknown status '{status}' (valid: {', '.join(VALID_STATUSES)})")

        required_fields = CORE_FIELDS if status == "open" else CORE_FIELDS + FIX_FIELDS
        for field in required_fields:
            if field not in bug or not bug[field]:
                errors.append(f"{bug_id}: missing required field '{field}'")

        if status == "open":
            for field in FIX_FIELDS:
                if bug.get(field):
                    errors.append(
                        f"{bug_id}: status is 'open' but '{field}' is set; mark it 'fixed' or remove the field"
                    )

        if bug.get("root_cause") and bug["root_cause"] not in valid_categories:
            errors.append(
                f"{bug_id}: unknown root_cause '{bug['root_cause']}' (valid: {', '.join(sorted(valid_categories))})"
            )

        if bug.get("severity") and bug["severity"] not in valid_severities:
            errors.append(
                f"{bug_id}: unknown severity '{bug['severity']}' (valid: {', '.join(sorted(valid_severities))})"
            )

    return errors


verify_bug_schema = verify_schema


def verify_unique_ids(registry: Dict[str, Any]) -> List[str]:
    """Verify all bug IDs are unique."""
    errors = []
    seen = set()
    for bug in registry.get("bugs", []):
        bug_id = bug.get("id", "")
        if bug_id in seen:
            errors.append(f"Duplicate bug ID: {bug_id}")
        seen.add(bug_id)
    return errors


def verify_regression_tests(registry: Dict[str, Any], workspace: str | Path | Workspace = ".") -> List[str]:
    """Verify each bug's regression test exists and can be run by pytest."""
    ws = as_workspace(workspace)
    ws_root = ws.root
    errors = []
    test_ids = []

    for bug in registry.get("bugs", []):
        if bug_status(bug) == "open":
            continue
        bug_id = bug.get("id", "<unknown>")
        test_ref = bug.get("regression_test", "")
        if not test_ref:
            errors.append(f"{bug_id}: no regression_test specified")
            continue

        test_file = test_ref.split("::")[0]
        full_path = ws_root / test_file
        if not full_path.exists():
            errors.append(f"{bug_id}: regression test file not found: {test_file}")
            continue

        test_ids.append((bug_id, test_ref))

    if test_ids:
        all_refs = [ref for _, ref in test_ids]
        budget = 60 + 5 * len(all_refs)
        from aegis_core.verification.test_runner import resolve_pytest_cmd
        pytest_cmd = resolve_pytest_cmd(workspace=ws_root)
        if not pytest_cmd:
            errors.append("Regression tests failed: no pytest runner discovered in environment")
        else:
            try:
                result = subprocess.run(
                    pytest_cmd + ["-q", "-rfE"] + all_refs,
                    capture_output=True,
                    text=True,
                    cwd=str(ws_root),
                    timeout=budget,
                )
                if result.returncode != 0:
                    errors.append(f"Regression tests failed (exit code {result.returncode})")
                    failed = _failed_node_ids((result.stdout or "") + "\n" + (result.stderr or ""))
                    matched_failure = False
                    for bug_id, test_ref in test_ids:
                        if any(_node_matches(node, test_ref) for node in failed):
                            errors.append(f"{bug_id}: regression test failed: {test_ref}")
                            matched_failure = True
                    if not matched_failure:
                        out = (result.stderr or "").strip() or (result.stdout or "").strip()
                        if out:
                            for line in out.splitlines()[-10:]:
                                errors.append(f"  pytest: {line}")
            except subprocess.TimeoutExpired:
                errors.append(f"Timeout running {len(all_refs)} regression tests (limit {budget} s)")
            except Exception as e:
                errors.append(f"Error running tests: {e}")

    return errors


verify_bug_tests = verify_regression_tests


def cli_verify_bug_registry(argv: Optional[List[str]] = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    parser = argparse.ArgumentParser(description="Verify Bug Registry")
    parser.add_argument("--workspace", default=None, help="Workspace root")
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])

    ws = args.workspace or resolve_workspace()
    try:
        registry = load_bug_registry(ws)
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    bugs = registry.get("bugs", [])
    print(f"Verifying {len(bugs)} bug entries...")

    all_errors = []
    all_errors.extend(verify_unique_ids(registry))
    all_errors.extend(verify_schema(registry))
    all_errors.extend(verify_regression_tests(registry, ws))

    if all_errors:
        print(f"\n❌ {len(all_errors)} verification error(s):")
        for err in all_errors:
            print(f"  • {err}")
        return 1

    # Summary
    categories: Dict[str, int] = {}
    for bug in bugs:
        cat = bug.get("root_cause", "unknown")
        categories[cat] = categories.get(cat, 0) + 1

    open_count = sum(1 for bug in bugs if bug_status(bug) == "open")
    print(f"\n=== All {len(bugs)} bugs verified ({open_count} open) ===")
    print("  Pattern distribution:")
    for cat, count in sorted(categories.items(), key=lambda x: -x[1]):
        print(f"    {cat}: {count}")

    return 0


# ── README Claim Verification ─────────────────────────────────────────────


def verify_readme_claims(workspace: str | Path | Workspace = ".") -> Tuple[bool, List[str]]:
    """Verify all README claims against CLAIM_REGISTRY.json."""
    ws = as_workspace(workspace)
    registry_path = ws.root / "docs" / "project" / "CLAIM_REGISTRY.json"
    readme_path = ws.root / "README.md"

    if not registry_path.exists():
        return False, [f"Claim registry not found: {registry_path}"]

    with open(registry_path, "r", encoding="utf-8") as f:
        registry = json.load(f)

    with open(readme_path, "r", encoding="utf-8") as f:
        readme = f.read()

    failures = []
    for claim_id, claim in registry.get("claims", {}).items():
        status = claim.get("status")
        if status == "unlocked":
            from aegis_core.verification.test_runner import resolve_pytest_cmd
            pytest_cmd = resolve_pytest_cmd(workspace=ws.root)
            if not pytest_cmd:
                failures.append(f"REGRESSION: {claim_id} — no pytest runner available to verify claim tests")
            else:
                for test in claim.get("required_tests", []):
                    res = subprocess.run(
                        pytest_cmd + [test, "-x", "-q", "--tb=short"],
                        capture_output=True,
                        text=True,
                        cwd=str(ws.root),
                    )
                    if res.returncode != 0:
                        failures.append(f"REGRESSION: {claim_id} — test {test} FAILED")
        elif status == "removed":
            if claim.get("readme_text") and claim["readme_text"] in readme:
                failures.append(f"OVERCLAIM: {claim_id} is marked 'removed' but text is in README")
        elif status == "locked":
            if claim.get("readme_text") and claim["readme_text"] in readme:
                failures.append(f"OVERCLAIM: {claim_id} is marked 'locked' but text is in README")

    return len(failures) == 0, failures


def cli_verify_readme_claims(argv: Optional[List[str]] = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    ws = resolve_workspace()
    ok, failures = verify_readme_claims(ws)
    if not ok:
        for f in failures:
            print(f"FAIL: {f}", file=sys.stderr)
        return 1
    print("PASS: All README claims verified.")
    return 0


def load_cells_for_enforcement(cells_dir: str | Path | Workspace) -> List[Dict[str, Any]]:
    """Load all cells for enforcement artifact generation."""
    cells = []
    from aegis_core.yaml import parse_frontmatter, _get_body

    if isinstance(cells_dir, Workspace):
        c_dir = str(cells_dir.cells_dir)
    else:
        c_dir = str(cells_dir)

    for cell_file in glob.glob(os.path.join(c_dir, "**", "*.md"), recursive=True):
        if os.path.basename(cell_file) == "README.md":
            continue
        try:
            with open(cell_file, "r", encoding="utf-8-sig") as f:
                content = f.read()
            fm = parse_frontmatter(content) or {}
            body = _get_body(content)
            fm["_path"] = cell_file
            fm["_name"] = os.path.splitext(os.path.basename(cell_file))[0]
            fm["_body"] = body.strip()
            cells.append(fm)
        except Exception as exc:
            sys.stderr.write(f"Warning: Failed to parse cell {cell_file}: {exc}\n")
    return cells


load_cells = load_cells_for_enforcement


def generate_precommit_check(cell: Dict[str, Any], workspace: str | Path | Workspace = ".") -> str:
    """Generate a pre-commit check script for a 'mechanical' cell."""
    name = cell.get("_name") or cell.get("id") or cell.get("name", "unnamed")
    cell_type = cell.get("type", "vacuole")
    hypothesis = cell.get("hypothesis", "")
    target_paths = cell.get("target_paths") or []

    clean_name = re.sub(r"[\r\n]+", " ", str(name)).strip()
    clean_hyp = re.sub(r"[\r\n]+", " ", str(hypothesis)).strip()

    quoted_name = shlex.quote(name)
    quoted_hyp = shlex.quote(hypothesis[:80])
    quoted_patterns = " ".join(shlex.quote(p) for p in target_paths)

    if cell_type == "wall":
        check = f"""#!/bin/bash
# Auto-generated enforcement artifact for: {clean_name}
# Type: {cell_type} | Tier: mechanical
# Hypothesis: {clean_hyp}
# Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}
#
# This check runs as part of the pre-commit hook.
# To disable: remove this file or demote the cell to advisory.

set -uo pipefail

CHANGED_FILES=$(git diff --cached --name-only 2>/dev/null)
if [ -z "$CHANGED_FILES" ]; then exit 0; fi

TARGET_PATTERNS=({quoted_patterns})
MATCHED=0

if [ ${{#TARGET_PATTERNS[@]}} -gt 0 ]; then
    while IFS= read -r file; do
        for pattern in "${{TARGET_PATTERNS[@]}}"; do
            case "$file" in
                $pattern) MATCHED=1; break 2 ;;
            esac
        done
    done <<< "$CHANGED_FILES"
fi

if [ "$MATCHED" -eq 1 ]; then
    echo -n "🛡️  ["
    echo -n {quoted_name}
    echo "] Cell triggered (mechanical enforcement)"
    echo -n "   Hypothesis: "
    echo {quoted_hyp}
    echo "   Files: $CHANGED_FILES"
    # Signal the cell via in-process python
    python3 -c "import sys; from aegis_core.telemetry import append_signal; append_signal('.', sys.argv[1], 'tp', 'mechanical')" {quoted_name} 2>/dev/null || true
    exit 1  # Mechanical: block commit
fi

exit 0  # No match: allow commit
"""
    elif cell_type == "membrane":
        check = f"""#!/bin/bash
# Auto-generated enforcement artifact for: {clean_name}
# Type: {cell_type} | Tier: mechanical
# Hypothesis: {clean_hyp}
# Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}

set -uo pipefail

CHANGED_FILES=$(git diff --cached --name-only 2>/dev/null)
if [ -z "$CHANGED_FILES" ]; then exit 0; fi

TARGET_PATTERNS=({quoted_patterns})
MATCHED=0

if [ ${{#TARGET_PATTERNS[@]}} -gt 0 ]; then
    while IFS= read -r file; do
        for pattern in "${{TARGET_PATTERNS[@]}}"; do
            case "$file" in
                $pattern) MATCHED=1; break 2 ;;
            esac
        done
    done <<< "$CHANGED_FILES"
fi

if [ "$MATCHED" -eq 1 ]; then
    echo -n "⚠️  ["
    echo -n {quoted_name}
    echo "] Membrane escalation triggered (mechanical enforcement)"
    echo -n "   Hypothesis: "
    echo {quoted_hyp}
    echo "   Recommend elevated review before merging."
    exit 1  # Mechanical: block commit
fi

exit 0  # No match: allow commit
"""
    else:
        check = f"""#!/bin/bash
# Auto-generated enforcement artifact for: {clean_name}
# Type: {cell_type} | Tier: mechanical
# Hypothesis: {clean_hyp}
# Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}

set -uo pipefail

CHANGED_FILES=$(git diff --cached --name-only 2>/dev/null)
if [ -z "$CHANGED_FILES" ]; then exit 0; fi

TARGET_PATTERNS=({quoted_patterns})
MATCHED=0

if [ ${{#TARGET_PATTERNS[@]}} -gt 0 ]; then
    while IFS= read -r file; do
        for pattern in "${{TARGET_PATTERNS[@]}}"; do
            case "$file" in
                $pattern) MATCHED=1; break 2 ;;
            esac
        done
    done <<< "$CHANGED_FILES"
fi

if [ "$MATCHED" -eq 1 ]; then
    echo -n "🔍  ["
    echo -n {quoted_name}
    echo "] Trap check triggered (mechanical enforcement)"
    echo -n "   Hypothesis: "
    echo {quoted_hyp}
    exit 1  # Mechanical: block commit
fi

exit 0  # No match: allow commit
"""
    return check


def generate_gate_assertion(cell: Dict[str, Any], workspace: str | Path | Workspace = ".") -> str:
    """Generate a runtime assertion for a 'gate' cell."""
    name = cell.get("_name") or cell.get("id") or cell.get("name", "unnamed")
    cell_type = cell.get("type", "vacuole")
    hypothesis = cell.get("hypothesis", "")
    target_paths = cell.get("target_paths") or []

    clean_name = re.sub(r"[\r\n]+", " ", str(name)).strip()
    clean_hyp = re.sub(r"[\r\n]+", " ", str(hypothesis)).strip()
    clean_hyp_doc = clean_hyp[:100].replace('"""', "'''")

    class_suffix = re.sub(r"[^a-zA-Z0-9]", "_", name)
    json_name = json.dumps(name)
    json_hyp = json.dumps(hypothesis)
    json_targets = json.dumps(target_paths)

    assertion = f'''# Auto-generated gate assertion for: {clean_name}
# Type: {cell_type} | Tier: gate
# Hypothesis: {clean_hyp}
# Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}

import os
import subprocess
import sys


class Gate_{class_suffix}:
    """Runtime gate for: {clean_hyp_doc}"""

    CELL_NAME = {json_name}
    HYPOTHESIS = {json_hyp}
    TARGET_PATHS = {json_targets}

    @classmethod
    def check(cls, context=None):
        try:
            from aegis_core.telemetry import append_signal
            append_signal(os.getcwd(), cls.CELL_NAME, "tp", "ci")
        except Exception:
            pass

    @classmethod
    def enforce(cls, condition, message=None):
        """Assert a condition. Halt on failure."""
        if not condition:
            msg = message or f"Gate violation: {{cls.HYPOTHESIS}}"
            try:
                from aegis_core.defects import record_escaped_defect
                cell_dict = {{"_name": cls.CELL_NAME, "name": cls.CELL_NAME, "type": "wall", "enforcement": "gate"}}
                record_escaped_defect(cell_dict, "crash", cls.TARGET_PATHS, "critical", os.getcwd())
            except Exception:
                pass
            raise RuntimeError(f"\U0001f6d1 GATE VIOLATION [{{cls.CELL_NAME}}]: {{msg}}")
'''
    return assertion


def update_cell_enforcement_artifact(cell: Dict[str, Any], artifact_path: str, workspace: str | Path | Workspace = ".") -> None:
    """Add enforcement_artifact field to cell YAML."""
    cell_path = cell.get("_path")
    if not cell_path or not os.path.exists(cell_path):
        return

    with open(cell_path, "r", encoding="utf-8") as f:
        content = f.read()

    if "enforcement_artifact:" in content:
        return

    ws = as_workspace(workspace)
    rel_path = os.path.relpath(artifact_path, str(ws.root))
    if not content.startswith("---"):
        return
    end_idx = content.find("---", 3)
    if end_idx == -1:
        return

    yaml_block = content[3:end_idx]
    body = content[end_idx:]

    lines = yaml_block.split("\n")
    new_lines = []
    inserted = False
    for line in lines:
        new_lines.append(line)
        if line.strip().startswith("enforcement:") and not inserted:
            new_lines.append(f"enforcement_artifact: {rel_path}")
            inserted = True

    if not inserted:
        new_lines.append(f"enforcement_artifact: {rel_path}")

    new_content = "---" + "\n".join(new_lines) + body
    with open(cell_path, "w", encoding="utf-8") as f:
        f.write(new_content)



# ── CI Outcome Reporter ───────────────────────────────────────────────────


def _parse_cell_frontmatter(filepath: str) -> Dict[str, Any]:
    """Parse YAML frontmatter from a cell markdown file using zero-dep parser."""
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception:
        return {}

    from aegis_core.yaml import parse_frontmatter
    try:
        return parse_frontmatter(content) or {}
    except Exception:
        return {}


def _match_cells(workspace: str | Path | Workspace, changed_files: List[str]) -> List[Dict[str, Any]]:
    """Match cells to changed files using target_paths fnmatch globs.

    Returns list of dicts with keys: cell, type, target_match, path.
    """
    from aegis_core.cell_inventory import find_matching_cells

    ws = as_workspace(workspace)
    cells_dir = str(ws.cells_dir)
    matches = find_matching_cells(cells_dir, changed_files, allow_basename_match=True)
    matched = []
    for m in matches:
        cell_name = os.path.splitext(os.path.basename(m.cell_path))[0]
        matched.append({
            "cell": cell_name,
            "type": m.cell_type,
            "target_match": m.first_matching_target or "",
            "path": m.cell_path,
        })
    return matched



def _compute_credit_weights(matched_cells: List[Dict[str, Any]], changed_files: List[str]) -> Dict[str, float]:
    """Compute per-cell credit weights with per-file conservation.

    For each changed file, cells matching that file share 1/N credit.
    A cell's total credit is the sum across all files it matches.
    """
    if not matched_cells or not changed_files:
        return {c["cell"]: 1.0 for c in matched_cells}

    # Build map: cell_name → target_paths
    cell_targets = {}
    for cell in matched_cells:
        cell_name = cell["cell"]
        cell_path = cell["path"]
        try:
            fm = _parse_cell_frontmatter(cell_path)
        except Exception:
            fm = {}
        tp = fm.get("target_paths", [])
        if isinstance(tp, str):
            tp = [tp]
        cell_targets[cell_name] = tp

    weights = {c["cell"]: 0.0 for c in matched_cells}

    for fpath in changed_files:
        # Find which cells match this specific file
        matching_for_file = []
        for cell_name, targets in cell_targets.items():
            for tp in targets:
                if fnmatch.fnmatch(fpath, tp) or fnmatch.fnmatch(
                    os.path.basename(fpath), tp
                ):
                    matching_for_file.append(cell_name)
                    break

        if matching_for_file:
            share = 1.0 / len(matching_for_file)
            for cell_name in matching_for_file:
                weights[cell_name] += share

    return weights


def _format_markdown(
    matched_cells: List[Dict[str, Any]],
    test_passed: bool,
    commit_sha: Optional[str],
    changed_files: List[str],
) -> str:
    """Format the report as a markdown summary."""
    status = "\u2705 Passed" if test_passed else "\u274c Failed"
    sha_display = commit_sha[:8] if commit_sha else "unknown"

    lines = [
        "## \U0001f52c Soma CI Outcome Report",
        "",
        f"**Commit**: `{sha_display}` | **Tests**: {status} "
        f"| **Cells matched**: {len(matched_cells)} "
        f"| **Files changed**: {len(changed_files)}",
        "",
    ]

    if matched_cells:
        lines.extend([
            "| Cell | Type | Target Match | Credit | Signal |",
            "|:-----|:-----|:-------------|:-------|:-------|",
        ])
        for cell in sorted(matched_cells, key=lambda c: c["cell"]):
            lines.append(
                f'| {cell["cell"]} | {cell["type"]} '
                f'| `{cell["target_match"]}` '
                f'| {cell["credit_weight"]:.2f} '
                f'| {cell["proposed_signal"]} |'
            )
    else:
        lines.append("No cells matched the changed files.")

    lines.append("")
    return "\n".join(lines)


def generate_ci_report(
    workspace: str | Path | Workspace = ".",
    changed_files: List[str] | None = None,
    test_passed: bool = True,
    commit_sha: Optional[str] = None,
) -> Dict[str, Any]:
    """Generate a CI outcome report.

    Args:
        workspace: Root workspace directory containing .soma/
        changed_files: List of changed file paths (relative to workspace)
        test_passed: Boolean — did the test suite pass?
        commit_sha: Optional commit SHA for the report header

    Returns:
        dict with keys:
          - matched_cells: list of dicts with cell, type, target_match,
                           credit_weight, proposed_signal
          - summary: markdown string for step summary
    """
    changed = changed_files or []
    matched = _match_cells(workspace, changed)
    weights = _compute_credit_weights(matched, changed)

    # Assign signals
    signal = "trigger" if test_passed else "fp"
    for cell in matched:
        cell["credit_weight"] = weights.get(cell["cell"], 1.0)
        cell["proposed_signal"] = signal

    # Generate markdown
    summary = _format_markdown(matched, test_passed, commit_sha, changed_files)

    return {
        "matched_cells": matched,
        "summary": summary,
    }


def cli_ci_outcome_reporter(argv: Optional[List[str]] = None) -> int:
    """CLI entrypoint for CI integration."""
    parser = argparse.ArgumentParser(description="Soma CI Outcome Reporter")
    parser.add_argument(
        "--changed-files",
        required=True,
        help="Space-separated list of changed files",
    )
    parser.add_argument(
        "--test-result",
        required=True,
        choices=["pass", "fail", "success", "failure", "skipped", "cancelled"],
        help="CI test result",
    )
    parser.add_argument("--commit-sha", default=None, help="Commit SHA")
    parser.add_argument(
        "--workspace",
        default=".",
        help="Workspace root (default: current directory)",
    )
    parser.add_argument(
        "--format",
        choices=["markdown", "json"],
        default="markdown",
        help="Output format",
    )

    args = parser.parse_args(argv if argv is not None else sys.argv[1:])

    changed = [f for f in args.changed_files.split() if f.strip()]
    test_passed = args.test_result in ("pass", "success")

    report = generate_ci_report(
        workspace=args.workspace,
        changed_files=changed,
        test_passed=test_passed,
        commit_sha=args.commit_sha,
    )

    if args.format == "json":
        print(json.dumps(report, indent=2))
    else:
        print(report["summary"])

    return 0


main = cli_ci_outcome_reporter

__all__ = [
    "VALID_STATUSES",
    "CORE_FIELDS",
    "FIX_FIELDS",
    "load_bug_registry",
    "load_registry",
    "bug_status",
    "verify_unique_ids",
    "verify_bug_schema",
    "verify_schema",
    "verify_bug_tests",
    "verify_regression_tests",
    "cli_verify_bug_registry",
    "verify_readme_claims",
    "cli_verify_readme_claims",
    "load_cells",
    "load_cells_for_enforcement",
    "generate_precommit_check",
    "generate_gate_assertion",
    "update_cell_enforcement_artifact",
    "generate_ci_report",
    "_match_cells",
    "cli_ci_outcome_reporter",
    "main",
]

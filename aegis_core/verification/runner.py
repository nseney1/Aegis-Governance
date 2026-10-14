"""Layer 1 Runner — orchestrates all deterministic verification tools.

Runs mandatory checks on changed files and produces a combined evidence package.
The output feeds directly into the Arbiter as Layer 1 evidence.
"""
from __future__ import annotations

import os
import sys
from typing import Optional

from . import ToolEvidence, ArbitrationResult
from . import persistence_checker
from . import call_graph
from . import import_guard
from . import mutation_tester
from . import branch_coverage


def _find_test_file(filepath: str, repo_root: str) -> Optional[str]:
    """Find the test file for a source file by convention.

    Searches in tests/ directory using canonical prefix and subdirectory conventions:
      1. tests/test_<stem>.py
      2. tests/test_<clean_parent>_<stem>.py (e.g. tests/test_cli_checkpoint.py)
      3. tests/test_<parent>_<stem>.py
      4. tests/<clean_parent>/test_<stem>.py
      5. tests/test_<clean_parent>/test_<stem>.py
      6. Domain mappings (e.g. runner.py -> test_verification/test_layer1.py)
    """
    norm = filepath.replace("\\", "/").replace("soma_", "aegis_")
    def _find_in_tests(*names: str) -> Optional[str]:
        for name in names:
            for prefix in ("", "unit/mcp", "unit/core", "unit/cli", "unit/verification", "unit/sdk", "integration"):
                p = os.path.join(repo_root, "tests", prefix, name) if prefix else os.path.join(repo_root, "tests", name)
                if os.path.isfile(p):
                    return p
        return None

    if "aegis_mcp/handlers" in norm:
        found = _find_in_tests("test_mcp_handlers.py")
        if found:
            return found
    if "aegis_core/outcomes/harvest.py" in norm:
        found = _find_in_tests("test_git_retro_harvest.py")
        if found:
            return found
    if "aegis_core/outcomes/insights.py" in norm:
        found = _find_in_tests("test_outcomes_insights.py")
        if found:
            return found
    if "aegis_core/outcomes/telemetry.py" in norm:
        found = _find_in_tests("test_outcomes_telemetry.py")
        if found:
            return found
    if "aegis_core/outcomes/engine.py" in norm:
        found = _find_in_tests("test_outcome_engine.py")
        if found:
            return found
    if "aegis_core/skills/slots.py" in norm:
        found = _find_in_tests("test_slots.py")
        if found:
            return found
    if "aegis_core/skills" in norm or "aegis_core/schemas/artifacts.py" in norm:
        found = _find_in_tests("test_skills_and_handoff.py")
        if found:
            return found

    stem = os.path.splitext(os.path.basename(filepath))[0]
    test_name = f"test_{stem}.py"
    parent = os.path.basename(os.path.dirname(filepath))
    clean_parent = parent[6:] if parent.startswith("aegis_") else (parent[5:] if parent.startswith("soma_") else parent)

    candidates = [
        test_name,
        f"test_{clean_parent}_{stem}.py",
        f"test_{parent}_{stem}.py",
        os.path.join(clean_parent, test_name),
        os.path.join(parent, test_name),
        os.path.join(f"test_{clean_parent}", test_name),
    ]

    # Domain specific mapping
    if stem == "runner" and clean_parent == "verification":
        found = _find_in_tests("test_layer1.py", "test_verification/test_layer1.py")
        if found:
            return found

    for cand_name in candidates:
        found = _find_in_tests(cand_name)
        if found:
            return found

    return None


def _discover_functions(filepath: str, target_lines: Optional[set[int]] = None) -> list[str]:
    """Extract top-level function names from a Python file via AST.

    If target_lines is provided, only functions intersecting target_lines are returned.
    """
    import ast
    try:
        with open(filepath) as f:
            tree = ast.parse(f.read())
    except (SyntaxError, OSError):
        return []
    funcs: list[str] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.FunctionDef)
            and not node.name.startswith('_')
            and not node.name.startswith('test_')
        ):
            if target_lines is not None:
                start = node.lineno
                end = getattr(node, "end_lineno", start)
                fn_lines = set(range(start, end + 1))
                if not (fn_lines & target_lines):
                    continue
            funcs.append(node.name)
    return funcs


def _get_modified_lines(filepath: str, repo_root: str, diff_base: Optional[str] = None) -> Optional[set[int]]:
    """Extract line numbers of additions/modifications in filepath via git diff."""
    import re
    import subprocess
    lines: set[int] = set()
    found_hunks = False

    diff_targets = []
    if diff_base:
        diff_targets.extend([
            ["git", "diff", "-U0", diff_base, "--", filepath],
            ["git", "diff", "-U0", f"{diff_base}...HEAD", "--", filepath],
        ])
    diff_targets.extend([
        ["git", "diff", "-U0", "HEAD", "--", filepath],
        ["git", "diff", "-U0", "--cached", "--", filepath],
    ])
    base_ref = os.environ.get("GITHUB_BASE_REF")
    if base_ref:
        diff_targets.extend([
            ["git", "diff", "-U0", f"origin/{base_ref}...HEAD", "--", filepath],
            ["git", "diff", "-U0", f"{base_ref}...HEAD", "--", filepath],
        ])
    diff_targets.extend([
        ["git", "diff", "-U0", "origin/develop...HEAD", "--", filepath],
        ["git", "diff", "-U0", "develop...HEAD", "--", filepath],
        ["git", "diff", "-U0", "origin/main...HEAD", "--", filepath],
        ["git", "diff", "-U0", "main...HEAD", "--", filepath],
        ["git", "diff", "-U0", "HEAD~1...HEAD", "--", filepath],
        ["git", "diff", "-U0", "HEAD~1", "--", filepath],
    ])
    for cmd in diff_targets:
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, cwd=repo_root, timeout=5)
            if res.returncode == 0 and res.stdout.strip():
                for line in res.stdout.splitlines():
                    if line.startswith("@@"):
                        found_hunks = True
                        m = re.search(r"\+(\d+)(?:,(\d+))?", line)
                        if m:
                            start = int(m.group(1))
                            count = int(m.group(2)) if m.group(2) is not None else 1
                            if count > 0:
                                lines.update(range(start, start + count))
                if found_hunks:
                    break
        except Exception:
            pass
    return lines if found_hunks else None



def run_layer1(
    changed_files: list[str],
    repo_root: str,
    persistence_targets: Optional[list[tuple[str, str]]] = None,
    mutation_targets: Optional[list[tuple[str, str, str]]] = None,
    coverage_targets: Optional[list[tuple[str, str]]] = None,
    max_mutations: int = 5,
    fast_mode: bool = False,
    diff_base: Optional[str] = None,
) -> list[ToolEvidence]:
    """Run all Layer 1 verification tools.

    Args:
        changed_files: List of file paths that were modified
        repo_root: Root of the repository
        persistence_targets: List of (filepath, dict_name) tuples for
            persistence checking. If None, auto-detects from changed_files.
        mutation_targets: List of (source_file, func_name, test_file) tuples.
            If None, auto-discovers from changed_files using convention.
        coverage_targets: List of (source_file, test_file) tuples.
            If None, auto-discovers from changed_files using convention.
        max_mutations: Maximum mutations per function (default: 5).

    Returns:
        List of ToolEvidence results for the Arbiter
    """
    results: list[ToolEvidence] = []

    def _is_test_or_support(fpath: str) -> bool:
        norm = fpath.replace('\\', '/')
        bname = os.path.basename(fpath)
        if norm.startswith(('soma_core/', 'soma_cli/', 'soma_sdk/', 'soma_mcp/')) and os.path.isdir(os.path.join(repo_root, 'aegis_core')):
            return True
        return (
            norm.startswith('tests/')
            or '/tests/' in norm
            or bname.startswith('test_')
            or bname.endswith(('_test.go', '_test.py', '.test.ts', '.spec.ts', '.test.js', '.spec.js'))
            or bname in ('__init__.py', 'conftest.py', 'harness.py', 'helpers_cell.py')
        )

    # ── Persistence Completeness ──────────────────────────────────────
    if persistence_targets:
        for filepath, dict_name in persistence_targets:
            full_path = os.path.join(repo_root, filepath)
            if os.path.exists(full_path):
                results.append(persistence_checker.check(full_path, dict_name))

    # ── Call Graph Completeness ───────────────────────────────────────
    from aegis_core.ast.runner import ASTDriverRunner
    ast_runner = ASTDriverRunner()

    for filepath in changed_files:
        full_path = os.path.join(repo_root, filepath)
        if not os.path.exists(full_path):
            continue
        if _is_test_or_support(filepath):
            continue
        ext = os.path.splitext(filepath)[1].lower()
        if ext == ".py":
            results.append(call_graph.check(
                full_path, repo_root,
                exclude_names={'main', '_parse_args', 'parse_args'},
                fast_mode=fast_mode,
            ))
        elif ast_runner.registry.resolve_driver(ext, workspace_root=repo_root):
            results.append(call_graph.check(
                full_path, repo_root,
                exclude_names={'main', '_parse_args', 'parse_args'},
                fast_mode=fast_mode,
                ast_runner=ast_runner,
            ))

    # ── Import Guards ─────────────────────────────────────────────────
    for filepath in changed_files:
        full_path = os.path.join(repo_root, filepath)
        if os.path.exists(full_path) and filepath.endswith('.py'):
            if _is_test_or_support(filepath):
                continue
            results.append(import_guard.check(full_path, project_root=repo_root))

    # ── Mutation Testing ───────────────────────────────────────────────
    if not fast_mode:
        if mutation_targets:
            for source, func, test in mutation_targets:
                src_path = os.path.join(repo_root, source)
                tst_path = os.path.join(repo_root, test)
                if os.path.exists(src_path) and os.path.exists(tst_path):
                    results.append(mutation_tester.check(
                        src_path, func, tst_path, max_mutations=max_mutations,
                    ))
        else:
            # Auto-discover: for each changed .py file, find test file and functions
            for filepath in changed_files:
                if not filepath.endswith('.py') or _is_test_or_support(filepath):
                    continue
                full_path = os.path.join(repo_root, filepath)
                if not os.path.exists(full_path):
                    continue
                test_file = _find_test_file(filepath, repo_root)
                if test_file is None:
                    continue
                mod_lines = _get_modified_lines(filepath, repo_root, diff_base=diff_base)
                funcs = _discover_functions(full_path, target_lines=mod_lines)
                for func_name in funcs[:3]:  # Limit auto-discovery to 3 functions
                    results.append(mutation_tester.check(
                        full_path, func_name, test_file,
                        max_mutations=max_mutations,
                        target_lines=mod_lines,
                    ))

    # ── Branch Coverage ───────────────────────────────────────────────
    if not fast_mode:
        if coverage_targets:
            for source, test in coverage_targets:
                src_path = os.path.join(repo_root, source)
                tst_path = os.path.join(repo_root, test)
                if os.path.exists(src_path) and os.path.exists(tst_path):
                    results.append(branch_coverage.check(src_path, tst_path))
        else:
            # Auto-discover: pair changed files with test files by convention
            for filepath in changed_files:
                if not filepath.endswith('.py') or _is_test_or_support(filepath):
                    continue
                full_path = os.path.join(repo_root, filepath)
                if not os.path.exists(full_path):
                    continue
                test_file = _find_test_file(filepath, repo_root)
                if test_file is None:
                    continue
                mod_lines = _get_modified_lines(filepath, repo_root, diff_base=diff_base)
                results.append(branch_coverage.check(full_path, test_file, target_lines=mod_lines))

    return results


# ── Layer 2: Adversarial Verification Orchestrator ────────────────────────


def _strip_code_fence(text: str) -> str:
    """Strip markdown code fences (```json ... ```) from LLM output."""
    import re
    match = re.search(r'```(?:json)?\s*\n?(.*?)\n?\s*```', text, re.DOTALL)
    if match:
        return match.group(1).strip()
    return text.strip()


def run_layer2(
    changed_files: list[str],
    repo_root: str,
    task_plan: str,
    layer1_evidence: list[ToolEvidence],
    llm_backend,
    test_names: Optional[list[str]] = None,
    test_results: Optional[str] = None,
) -> 'ArbitrationResult':
    """Run Layer 2 adversarial verification protocol.

    Thin backward-compatibility adapter delegating to AdversarialVerifier and Arbiter.
    """
    if llm_backend is None:
        raise TypeError("llm_backend must be a callable, got None")

    import warnings
    warnings.warn(
        "aegis_core.verification.runner.run_layer2 is deprecated; use VerificationPipeline",
        DeprecationWarning,
        stacklevel=2,
    )

    from .pipeline import VerificationPipeline

    pipeline = VerificationPipeline()
    res = pipeline.run(
        changed_files=changed_files,
        workspace=repo_root,
        task_plan=task_plan,
        backend=llm_backend,
        in_band=False,
        test_names=test_names,
        test_results=test_results,
        layer1_evidence=layer1_evidence,
    )
    return res.arbitration_result or ArbitrationResult(
        divergences=[],
        convergences=[],
        verdict=res.verdict,
        layer1_results=layer1_evidence or [],
        predictions=[],
        claims=[],
    )


def gate_verdict(results: list[ToolEvidence]) -> bool:
    """Simple gate: PASS if all tools pass. Empty results (no changed files) is a clean pass."""
    if not results:
        return True
    return all(r.verdict for r in results)


def format_summary(results: list[ToolEvidence]) -> str:
    """One-line summary of Layer 1 results."""
    if not results:
        return "Layer 1: No changed files to verify (0 checks run, PASSED)"
    passed = sum(1 for r in results if r.verdict)
    failed = sum(1 for r in results if not r.verdict)
    total = len(results)
    if failed:
        return f"Layer 1: {failed}/{total} FAILED — {', '.join(r.tool for r in results if not r.verdict)}"
    return f"Layer 1: {passed}/{total} PASSED"


if __name__ == '__main__':
    # A cp1252 stdout can't encode this script's symbols (BUG-038).
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(errors='replace')
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <repo_root> [file1 file2 ...]")
        sys.exit(1)

    repo_root = sys.argv[1]
    changed = sys.argv[2:] if len(sys.argv) > 2 else []

    results = run_layer1(changed, repo_root)
    for r in results:
        icon = "✅" if r.verdict else "🔴"
        print(f"{icon} {r.tool}: {r.target} — {r.detail}")

    print(f"\n{format_summary(results)}")
    sys.exit(0 if gate_verdict(results) else 1)

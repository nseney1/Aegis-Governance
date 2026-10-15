"""Layer 1 Runner — orchestrates all deterministic verification tools.

Runs mandatory checks on changed files and produces a combined evidence package.
The output feeds directly into the Arbiter as Layer 1 evidence.
"""
from __future__ import annotations

import os
from pathlib import Path
import sys
from aegis_core.match import is_test_path
from aegis_core.workspace.layout import RULES_RELDIR
from typing import Any, Optional

from . import ToolEvidence
from . import persistence_checker
from . import call_graph
from . import import_guard
from . import mutation_tester

VerificationResult = ToolEvidence


_FORBID_AST_KEYS = ("imports", "calls", "decorators")


def _forbid_ast_spec_error(spec: object) -> Optional[str]:
    """Why a declared ``forbid_ast`` would enforce nothing as written; None when it is well-formed.

    evaluate_forbid_ast ignores what it cannot use (a list, a string where a list belongs,
    a misspelt key), so a gate rule in such a shape would pass every file.
    """
    if not isinstance(spec, dict):
        return f"forbid_ast must map imports/calls/decorators to lists, not {type(spec).__name__}"
    unknown = sorted(str(key) for key in spec if key not in _FORBID_AST_KEYS)
    if unknown:
        listed = ", ".join(repr(key) for key in unknown)
        return f"unknown forbid_ast key {listed} (allowed: {', '.join(_FORBID_AST_KEYS)})"
    patterns = 0
    for key, value in spec.items():
        if not isinstance(value, list) or not all(isinstance(p, str) and p.strip() for p in value):
            return f"forbid_ast.{key} must be a list of non-empty strings, not {type(value).__name__}"
        patterns += len(value)
    return None if patterns else "forbid_ast declares no patterns"


def _discover_forbid_ast_rules(
    repo_root: str,
) -> tuple[list[tuple[Any, dict]], list[tuple[str, str]]]:
    """The workspace rules (aegis_core.rules, .aegis/rules/<type>/) that declare forbid_ast.

    Returns (rules, broken): a rule file that cannot be loaded and names forbid_ast, or
    whose forbid_ast is malformed, would enforce nothing, so each is returned as
    (relative path, reason) for the caller to fail closed on instead of being dropped.
    An unsafe rules tree raises (RuleInventoryError), which the caller also fails on.
    """
    from aegis_core.rules import load_rules, workspace_root

    ruleset = load_rules(workspace_root(repo_root))
    discovered: list[tuple[Any, dict]] = []
    broken: list[tuple[str, str]] = []
    for rule in ruleset.rules:
        if not rule.ok:
            # Only a file that names the key can declare it: a damaged note does not gate.
            if b"forbid_ast" in rule.raw:
                broken.append((rule.path, rule.error or "cannot be loaded"))
            continue
        if rule.expired or "forbid_ast" not in rule.meta:
            continue
        spec = rule.meta.get("forbid_ast")
        spec_error = _forbid_ast_spec_error(spec)
        if spec_error:
            broken.append((rule.path, spec_error))
            continue
        discovered.append((rule, spec))
    return discovered, broken


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
    if "aegis_core/skills" in norm:
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
    """1-based lines of ``filepath``'s working copy that are new or changed against a base.

    Bases, in order: ``diff_base`` (``REF...HEAD`` means its merge base with HEAD), HEAD,
    the merge base with the pull request's base branch, then HEAD~1. The first base the
    file differs from wins. Returns None when no base shows a change or git cannot answer.
    Old contents come from ``gitsafe.read_blob``; the comparison is done here, so no
    porcelain diff (and no repository fsmonitor or diff driver) is involved.
    """
    import difflib

    from aegis_core import gitsafe

    try:
        current = (Path(repo_root) / filepath).read_bytes().decode("utf-8", "replace").splitlines()
    except OSError:
        return None
    rel = Path(os.path.relpath(Path(repo_root) / filepath, repo_root)).as_posix()

    bases: list[Optional[str]] = []
    if diff_base:
        if diff_base.endswith("...HEAD"):
            bases.append(gitsafe.merge_base(repo_root, diff_base[: -len("...HEAD")]))
        else:
            bases.append(gitsafe.resolve_commit(repo_root, diff_base))
    bases.append(gitsafe.head_commit(repo_root))
    pr_base = gitsafe.resolve_base_ref(repo_root)
    if pr_base:
        bases.append(gitsafe.merge_base(repo_root, pr_base))
    bases.append(gitsafe.resolve_commit(repo_root, "HEAD~1"))

    seen: set[str] = set()
    for base in bases:
        if not base or base in seen:
            continue
        seen.add(base)
        try:
            old = gitsafe.read_blob(repo_root, base, rel)
        except gitsafe.GitError:
            return None
        before = old.decode("utf-8", "replace").splitlines() if old is not None else []
        lines: set[int] = set()
        matcher = difflib.SequenceMatcher(None, before, current, autojunk=False)
        for tag, _i1, _i2, j1, j2 in matcher.get_opcodes():
            if tag in ("replace", "insert"):
                lines.update(range(j1 + 1, j2 + 1))
        if lines:
            return lines
    return None


def _tool_failure(tool: str, target: str, exc: Exception) -> ToolEvidence:
    """A Layer 1 tool that raised fails the gate; it must never abort the run or pass silently."""
    return ToolEvidence(
        tool=tool,
        target=target,
        verdict=False,
        detail=f"{tool}: cannot verify {target}: {type(exc).__name__}: {exc}",
    )


def run_layer1(
    changed_files: list[str],
    repo_root: str,
    persistence_targets: Optional[list[tuple[str, str]]] = None,
    mutation_targets: Optional[list[tuple[str, str, str]]] = None,
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
        max_mutations: Maximum mutations per function (default: 5).

    Returns:
        List of ToolEvidence results for the Arbiter
    """
    results: list[ToolEvidence] = []
    repo_root_str = str(getattr(repo_root, "root", repo_root))

    def _is_test_or_support(fpath: str) -> bool:
        return is_test_path(fpath) or os.path.basename(fpath) == '__init__.py'

    # ── Persistence Completeness ──────────────────────────────────────
    if persistence_targets:
        for filepath, dict_name in persistence_targets:
            full_path = os.path.join(repo_root_str, filepath)
            if os.path.exists(full_path):
                results.append(persistence_checker.check(full_path, dict_name))

    # ── Call Graph Completeness ───────────────────────────────────────
    from aegis_core.ast.runner import ASTDriverRunner
    ast_runner = ASTDriverRunner()

    for filepath in changed_files:
        full_path = os.path.join(repo_root_str, filepath)
        if not os.path.exists(full_path):
            continue
        if _is_test_or_support(filepath):
            continue
        ext = os.path.splitext(filepath)[1].lower()
        try:
            if ext == ".py":
                results.append(call_graph.check(
                    full_path, repo_root_str,
                    exclude_names={'main', '_parse_args', 'parse_args'},
                    fast_mode=fast_mode,
                ))
            elif ast_runner.registry.resolve_driver(ext, workspace_root=repo_root_str):
                results.append(call_graph.check(
                    full_path, repo_root_str,
                    exclude_names={'main', '_parse_args', 'parse_args'},
                    fast_mode=fast_mode,
                    ast_runner=ast_runner,
                ))
        except Exception as exc:
            results.append(_tool_failure("call_graph", filepath, exc))

    # ── Import Guards ─────────────────────────────────────────────────
    for filepath in changed_files:
        full_path = os.path.join(repo_root_str, filepath)
        if os.path.exists(full_path) and filepath.endswith('.py'):
            if _is_test_or_support(filepath):
                continue
            try:
                results.append(import_guard.check(full_path, project_root=repo_root_str))
            except Exception as exc:
                results.append(_tool_failure("import_guard", filepath, exc))

    # ── Declarative Rule-Level forbid_ast ─────────────────────────────
    from aegis_core.ast.policy import ASTExtractionError, evaluate_forbid_ast, extract_normalized_ast

    try:
        forbid_rules, broken_rules = _discover_forbid_ast_rules(repo_root_str)
    except Exception as exc:
        # The rules are gate rules: if they cannot be read, nothing may pass unchecked.
        forbid_rules, broken_rules = [], []
        results.append(ToolEvidence(
            tool="forbid_ast",
            target=RULES_RELDIR,
            verdict=False,
            detail=f"forbid_ast: cannot load rules: {type(exc).__name__}: {exc}",
        ))
    for rule_path, reason in broken_rules:
        results.append(ToolEvidence(
            tool="forbid_ast",
            target=rule_path,
            verdict=False,
            detail=f"forbid_ast: cannot load rule {rule_path}: {reason}",
        ))
    if forbid_rules:
        ast_cache: dict[str, object] = {}
        for filepath in changed_files:
            full_path = filepath if os.path.isabs(filepath) else os.path.join(repo_root_str, filepath)
            if not os.path.isfile(full_path):
                continue
            try:
                rel_path = os.path.relpath(full_path, repo_root_str).replace("\\", "/")
            except ValueError:
                rel_path = filepath.replace("\\", "/")
            for rule, forbid_spec in forbid_rules:
                rule_id = rule.id
                # Rule.applies_to: target_paths ("**" when a forbid_ast rule names none),
                # and test files only when the patterns name tests. Scan, telemetry and
                # coverage ask the same question.
                if not rule.applies_to(rel_path):
                    continue

                try:
                    if full_path not in ast_cache:
                        try:
                            ast_cache[full_path] = extract_normalized_ast(
                                full_path, workspace_root=repo_root_str, ast_runner=ast_runner
                            )
                        except ASTExtractionError as exc:
                            ast_cache[full_path] = exc
                    norm_ast = ast_cache[full_path]
                    if norm_ast is None:  # no AST driver for this file type: rule does not apply
                        continue
                    violations: list[str] = []
                    if not isinstance(norm_ast, ASTExtractionError):
                        try:
                            violations = evaluate_forbid_ast(norm_ast, forbid_spec)
                        except ASTExtractionError as exc:  # decorators had to be re-read from disk
                            norm_ast = exc
                except Exception as exc:
                    results.append(_tool_failure(f"forbid_ast:{rule_id}", rel_path, exc))
                    continue
                if isinstance(norm_ast, ASTExtractionError):
                    # Fail closed: a gate rule that cannot read the file must not pass it.
                    results.append(
                        VerificationResult(
                            tool=f"forbid_ast:{rule_id}",
                            target=rel_path,
                            verdict=False,
                            detail=f"forbid_ast: cannot verify {rel_path}: {norm_ast.reason}",
                        )
                    )
                    continue
                if violations:
                    results.append(
                        VerificationResult(
                            tool=f"forbid_ast:{rule_id}",
                            target=rel_path,
                            verdict=False,
                            detail="; ".join(violations),
                        )
                    )

    # ── Mutation Testing ───────────────────────────────────────────────
    if not fast_mode:
        if mutation_targets:
            for source, func, test in mutation_targets:
                src_path = os.path.join(repo_root_str, source)
                tst_path = os.path.join(repo_root_str, test)
                if os.path.exists(src_path) and os.path.exists(tst_path):
                    results.append(mutation_tester.check(
                        src_path, func, tst_path, max_mutations=max_mutations,
                    ))
        else:
            # Auto-discover: for each changed .py file, find test file and functions
            for filepath in changed_files:
                if not filepath.endswith('.py') or _is_test_or_support(filepath):
                    continue
                full_path = os.path.join(repo_root_str, filepath)
                if not os.path.exists(full_path):
                    continue
                test_file = _find_test_file(filepath, repo_root_str)
                if test_file is None:
                    continue
                mod_lines = _get_modified_lines(filepath, repo_root_str, diff_base=diff_base)
                funcs = _discover_functions(full_path, target_lines=mod_lines)
                for func_name in funcs[:3]:  # Limit auto-discovery to 3 functions
                    results.append(mutation_tester.check(
                        full_path, func_name, test_file,
                        max_mutations=max_mutations,
                        target_lines=mod_lines,
                    ))

    return results


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

"""The engine behind `aegis check`: target files, Layer 1 and the opt-in Layer 2.

Layer 1 is the workspace checkpoint (aegis_cli.checkpoint) plus call_graph,
import_guard and forbid_ast on the target files. With --hook (the git pre-commit
hook) and no FILES, the targets are the staged files and Layer 1 reads their
staged content: what the commit records, whatever the working tree holds. Layer 2 (--full, or a plan)
adds the adversarial Spec/Code agent pair and the deterministic Arbiter, run
by one model command (--llm-cmd or AEGIS_LLM_CMD).

Exit codes: 0 pass, 1 findings or a failed run, 2 usage error.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any

from aegis_cli.checkpoint import is_blocking, run_checkpoint
from aegis_cli.formatters.report import (
    format_layer1_json_payload,
    format_layer2_json,
    format_layer2_summary,
)
from aegis_core.workspace.layout import AEGIS_DIRNAME

__all__ = [
    "discover_test_evidence",
    "resolve_target_files",
    "resolve_task_plan",
    "run_verify",
    "verdict_to_exit_code",
]


def verdict_to_exit_code(verdict: Any) -> int:
    """SHIP is 0; BLOCK, REVISE and anything else are 1 (fail closed)."""
    from aegis_core.verification import Verdict

    return 0 if verdict == Verdict.SHIP else 1


def _resolve_git_cwd(args: argparse.Namespace) -> str:
    if getattr(args, "ws", None) is not None:
        return str(args.ws.root)
    return str(
        getattr(args, "workspace", None)
        or getattr(args, "repo_root", None)
        or getattr(args, "_project_root", None)
        or getattr(args, "_root", None)
        or os.getcwd()
    )


def _files_under(directory: str, git_cwd: str) -> list[str] | None:
    """Tracked and untracked, not ignored, files under *directory*; None outside a git work tree."""
    from aegis_core import gitsafe

    listed = gitsafe.list_files(git_cwd, [directory])
    if listed is None:
        return None
    # A tracked file deleted from the working tree is listed too; there is nothing to check.
    return [f for f in listed if os.path.isfile(os.path.join(git_cwd, f))]


def _workspace_relative(paths: list[str], git_cwd: str) -> list[str]:
    """``paths`` as git diff names them (from the top of the work tree) made relative to
    the workspace at ``git_cwd``; a path outside the workspace is not its to check."""
    from aegis_core import gitsafe

    top = gitsafe.toplevel(git_cwd)
    if top is None:
        return paths
    try:
        prefix = Path(os.path.relpath(os.path.realpath(git_cwd), os.path.realpath(str(top)))).as_posix()
    except ValueError:  # another drive on Windows
        return paths
    if prefix == "." or prefix.startswith(".."):
        return paths
    lead = prefix + "/"
    return [p[len(lead):] for p in paths if p.startswith(lead)]


def resolve_target_files(args: argparse.Namespace) -> list[str]:
    """Resolve target files from FILES (a directory means the files under it) or git changes.

    With ``--hook`` and no FILES the targets are the staged files, what the commit records;
    ``args._staged_unreadable`` is set when git cannot list them. Otherwise, without FILES,
    sets ``args._diff_base`` to the base ref the changes came from, or
    ``args._no_diff_base`` when nothing changed and no base ref could be diffed against
    (a shallow clone, a repository with no main branch), so a clean tree is not assumed.
    """
    git_cwd = _resolve_git_cwd(args)
    explicit = getattr(args, "files", None)
    if explicit:
        from aegis_cli import sanitize_display

        repo_root = os.path.realpath(git_cwd)
        safe_files = []
        for f in explicit:
            resolved = os.path.realpath(os.path.join(repo_root, f))
            if not resolved.startswith(repo_root + os.sep) and resolved != repo_root:
                print(f"Warning: skipping out-of-tree file: {sanitize_display(f)}", file=sys.stderr)
                continue
            if os.path.isdir(resolved):
                listed = _files_under(f, git_cwd)
                if listed is None:
                    # Fail closed: a named target that cannot be expanded is not checked.
                    print(
                        f"Error: cannot list the files under {sanitize_display(f)}: not a git work tree; "
                        "name the files instead",
                        file=sys.stderr,
                    )
                    return []
                if not listed:
                    print(f"Warning: no files to check under {sanitize_display(f)}", file=sys.stderr)
                for g in listed:
                    real = os.path.realpath(os.path.join(repo_root, g))
                    if real.startswith(repo_root + os.sep):
                        safe_files.append(g)
                    else:
                        print(f"Warning: skipping out-of-tree file: {sanitize_display(g)}", file=sys.stderr)
                continue
            safe_files.append(f)
        if not safe_files:
            print("Error: none of the specified files can be checked (outside the repository or empty)",
                  file=sys.stderr)
        return list(dict.fromkeys(safe_files))

    from aegis_core import gitsafe

    if getattr(args, "hook", False):
        staged = gitsafe.changed_files(git_cwd, "staged")
        if staged is None:
            setattr(args, "_staged_unreadable", True)
            return []
        return _workspace_relative(staged, git_cwd)

    # `git diff HEAD` plus `git diff --cached`: what a commit of the working tree would add.
    files = _workspace_relative(gitsafe.changed_files(git_cwd, "working") or [], git_cwd)
    if not files:
        # Nothing uncommitted: check what this branch adds to its base, else the last commit.
        diffed = False
        base = gitsafe.resolve_base_ref(git_cwd)
        candidates = [("range", base)] if base else []
        if gitsafe.resolve_commit(git_cwd, "HEAD~1"):  # a root commit has no parent to diff against
            candidates.append(("head", "HEAD~1"))
        for mode, ref in candidates:
            found = gitsafe.changed_files(git_cwd, mode, base=ref if mode == "range" else None)
            if found is None:
                continue
            diffed = True
            if found:
                files = _workspace_relative(found, git_cwd)
                setattr(args, "_diff_base", f"{ref}...HEAD" if mode == "range" else ref)
                break
        if not diffed:
            setattr(args, "_no_diff_base", True)
    return files


def discover_test_evidence(target_files: list[str], repo_root: str) -> tuple[list[str], str]:
    """Discover matching test files, parse test names via AST, and execute tests."""
    from aegis_core.verification.test_runner import discover_test_evidence as _core_discover
    return _core_discover(target_files, repo_root)


def resolve_task_plan(args: argparse.Namespace, repo_root: str) -> str | None:
    """Resolve task plan from --plan, --plan-file, or standard plan conventions.

    An explicit --plan is returned as given (stripped), even when empty: the caller
    rejects an empty plan rather than falling back to a plan file nobody named.
    """
    if getattr(args, "plan", None) is not None:
        return args.plan.strip()

    plan_file = getattr(args, "plan_file", None)
    if plan_file:
        plan_path = plan_file if os.path.isabs(plan_file) else os.path.join(repo_root, plan_file)
        if not os.path.isfile(plan_path):
            print(f"Error: plan file not found: {plan_file}", file=sys.stderr)
            return None
        try:
            with open(plan_path, encoding="utf-8") as f:
                return f.read().strip()
        except OSError as e:
            print(f"Error: could not read plan file {plan_file}: {e}", file=sys.stderr)
            return None

    real_root = os.path.realpath(repo_root)
    for default_name in ("docs/plan.md", f"{AEGIS_DIRNAME}/plan.md", "PLAN.md"):
        cand = os.path.join(repo_root, default_name)
        if not os.path.lexists(cand):
            continue
        # Nobody named this file, and its text goes to the model: a branch must not be
        # able to route a secret from outside the repository into the prompt.
        if os.path.islink(cand) or not os.path.realpath(cand).startswith(real_root + os.sep):
            print(f"Warning: ignoring {default_name}: it is a symlink or leaves the repository", file=sys.stderr)
            continue
        if os.path.isfile(cand):
            try:
                with open(cand, encoding="utf-8") as f:
                    content = f.read().strip()
                    if content:
                        return content
            except OSError:
                pass
    return None


def _usage_error(message: str) -> int:
    print(f"Error: {message}", file=sys.stderr)
    return 2


def _print_checkpoint(issues: list[dict], strict: bool) -> None:
    if not issues:
        print("checkpoint: all checks passed")
    for issue in issues:
        label = "[FAIL]" if is_blocking(issue, strict) else "[WARN]"
        print(f"{label} {issue['message']}")


def run_verify(args: argparse.Namespace) -> int:
    """Run `aegis check` for *args*. Returns 0, 1 or 2 (see the module docstring)."""
    from aegis_core.inference_provider import MISSING_BACKEND, LLMCommandError, resolve_backend
    from aegis_core.verification.pipeline import VerificationPipeline
    from aegis_core.verification import runner
    from aegis_core.workspace.base import Workspace

    hook = bool(getattr(args, "hook", False))
    plan = getattr(args, "plan", None)
    plan_file = getattr(args, "plan_file", None)
    # Presence, not truthiness: `--plan "$PLAN"` with PLAN unset still asked for Layer 2.
    layer2 = bool(getattr(args, "full", False)) or plan is not None or plan_file is not None
    if hook and layer2:
        return _usage_error("--hook runs Layer 1 only; drop --full, --plan and --plan-file")
    if plan is not None and not plan.strip():
        return _usage_error("Layer 2 needs a task plan: --plan is empty")
    if plan_file is not None and not plan_file.strip():
        return _usage_error("Layer 2 needs a task plan: --plan-file is empty")

    backend = None
    if layer2:
        # Fail before any work: a Layer 2 run without a model must never pass as Layer 1 only.
        try:
            backend = resolve_backend(getattr(args, "llm_cmd", None))
        except LLMCommandError as exc:
            return _usage_error(str(exc))
        if backend is None:
            return _usage_error(MISSING_BACKEND)

    raw_ws = (
        getattr(args, "workspace", None)
        or getattr(args, "repo_root", None)
        or getattr(args, "_project_root", None)
        or getattr(args, "_root", None)
    )
    if getattr(args, "ws", None) is None and raw_ws and not os.path.isdir(str(raw_ws)):
        # Workspace.resolve walks up to an existing parent; checking that instead fails open.
        print(f"Error: workspace does not exist: {raw_ws}", file=sys.stderr)
        return 1
    ws_obj = getattr(args, "ws", None) or Workspace.resolve(raw_ws)
    repo_root = str(ws_obj.root)
    if not os.path.isdir(repo_root):
        print(f"Error: repo root does not exist: {repo_root}", file=sys.stderr)
        return 1

    task_plan = None
    if layer2:
        task_plan = resolve_task_plan(args, repo_root)
        if plan_file and task_plan is None:
            return 1
        if not task_plan:
            return _usage_error("Layer 2 needs a task plan: pass --plan or --plan-file (or add docs/plan.md)")

    fmt = str(getattr(args, "format", None) or "text").lower()
    use_json = bool(getattr(args, "json", False) or fmt == "json")
    strict = bool(getattr(args, "strict", False))
    mode = "Layer 1 + Layer 2" if layer2 else "Layer 1"

    target_files = resolve_target_files(args)
    if getattr(args, "files", None) and not target_files:
        return 1
    staged = hook and not getattr(args, "files", None)
    if staged and getattr(args, "_staged_unreadable", False):
        # Fail closed: a commit whose content cannot be listed is not checked.
        print("Error: cannot read the staged changes (not a git work tree, or git failed); nothing was checked",
              file=sys.stderr)
        return 1
    no_diff_base = not target_files and bool(getattr(args, "_no_diff_base", False))
    if layer2 and no_diff_base:
        return _usage_error(
            "Layer 2 has nothing to review: no changed files, and no base commit found to diff "
            "against (a shallow clone?); pass the files to review"
        )
    if getattr(args, "files", None) and not getattr(args, "dry_run", False):
        missing = [f for f in target_files if not os.path.exists(os.path.join(repo_root, f))]
        if missing:
            for f in missing:
                print(f"Error: file not found: {f}", file=sys.stderr)
            return 1

    if getattr(args, "dry_run", False):
        if use_json:
            print(json.dumps({"dry_run": True, "mode": mode, "repo_root": repo_root, "files": target_files}, indent=2))
            return 0
        print(f"Dry run — {mode}\nRepo root: {repo_root}\nFiles to verify ({len(target_files)}):")
        for f in target_files:
            print(f"  {f}")
        return 0

    # ── Layer 1: workspace checkpoint, then the per-file tools ────────────
    issues, blocking = run_checkpoint(Path(repo_root), strict=strict)
    if not use_json:
        _print_checkpoint(issues, strict)

    if not target_files:
        if staged:
            summary = "Layer 1: 0 files staged (nothing to check)"
        elif no_diff_base:
            summary = "Layer 1: 0 files changed (no base commit found to diff against; pass the files to check)"
        else:
            summary = "Layer 1: 0 files changed (clean repository)"
        # Say so: a Layer 2 run that reviewed nothing must not read like a Layer 1-only pass.
        layer2_summary = "Layer 2: no changed files to review"
        if use_json:
            payload = format_layer1_json_payload(not blocking, [], [], summary)
            payload["checkpoint_issues"] = issues
            if layer2:
                payload["layer2"] = {"verdict": None, "summary": layer2_summary}
            print(json.dumps(payload, indent=2))
        else:
            print(summary)
            if layer2:
                print(layer2_summary)
        return 1 if blocking else 0

    try:
        if staged:
            # What `git commit` records is the index, not the working tree.
            results = runner.run_layer1_on_index(target_files, repo_root)
        else:
            # Mutation testing is slow; it runs only behind --full (fast_mode otherwise).
            results = runner.run_layer1(
                changed_files=target_files,
                repo_root=repo_root,
                fast_mode=not layer2,
                diff_base=getattr(args, "_diff_base", None),
            )
    except Exception as exc:
        print(f"Error: Layer 1 could not run: {exc}", file=sys.stderr)
        return 1

    tools_pass = runner.gate_verdict(results)
    layer1_pass = tools_pass and not blocking
    if results:
        summary = runner.format_summary(results)
    else:
        n = len(target_files)
        summary = f"Layer 1: no check applies to the {n} target file{'' if n == 1 else 's'} (0 checks run, PASSED)"
    if not use_json:
        for r in results:
            if not r.verdict:
                print(f"🔴 {r.tool}: {r.target} — {r.detail}")
        print(summary)

    def _record_telemetry(passed: bool, verdict: Any) -> None:
        # Advisory rule-trigger telemetry: it must never change the verdict.
        try:
            from aegis_core.outcomes.telemetry import record_verification_telemetry
            record_verification_telemetry(
                workspace=repo_root,
                target_files=target_files,
                passed=passed,
                verdict=verdict,
                layer1_evidence=results,
                source="session",
            )
        except Exception:
            pass

    def _emit_json(passed: bool, layer2_result: Any = None) -> None:
        payload = format_layer1_json_payload(passed, target_files, results, summary)
        payload["checkpoint_issues"] = issues
        if layer2_result is not None:
            payload["layer2"] = format_layer2_json(layer2_result.arbitration_result, layer2_result.verdict)
        print(json.dumps(payload, indent=2))

    if not layer2:
        _record_telemetry(tools_pass, "PASS" if tools_pass else "FAIL")
        if use_json:
            _emit_json(layer1_pass)
        return 0 if layer1_pass else 1

    # ── Layer 2: adversarial pair + Arbiter ───────────────────────────────
    try:
        test_names, test_results = discover_test_evidence(target_files, repo_root)
    except Exception as e:
        print(f"Error: Test discovery and execution failed: {e}", file=sys.stderr)
        _record_telemetry(False, "BLOCK")
        return 1

    try:
        pipeline_res = VerificationPipeline().run(
            changed_files=target_files,
            workspace=ws_obj,
            task_plan=task_plan,
            backend=backend,
            test_names=test_names,
            test_results=test_results,
            layer1_evidence=results,
        )
    except Exception as e:
        print(f"Error: Layer 2 failed: {e}", file=sys.stderr)
        _record_telemetry(False, "BLOCK")
        return 1

    passed = layer1_pass and verdict_to_exit_code(pipeline_res.verdict) == 0
    _record_telemetry(tools_pass and pipeline_res.passed, pipeline_res.verdict)
    if use_json:
        _emit_json(passed, pipeline_res)
    elif pipeline_res.arbitration_result:
        print(format_layer2_summary(pipeline_res.arbitration_result))
    return 0 if passed else 1

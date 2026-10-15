"""The engine behind `aegis check`: target files, Layer 1 and the opt-in Layer 2.

Layer 1 is the workspace checkpoint (aegis_cli.checkpoint) plus call_graph,
import_guard and forbid_ast on the target files. Layer 2 (--full, or a plan)
adds the adversarial Spec/Code agent pair and the deterministic Arbiter, run
by one model command (--llm-cmd or AEGIS_LLM_CMD).

Exit codes: 0 pass, 1 findings or a failed run, 2 usage error.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any

from aegis_cli.checkpoint import is_blocking, run_checkpoint
from aegis_cli.formatters.report import (
    format_layer1_json_payload,
    format_layer2_json,
    format_layer2_summary,
)

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


def resolve_target_files(args: argparse.Namespace) -> list[str]:
    """Resolve target files from --files flag or git staged/changed files."""
    git_cwd = _resolve_git_cwd(args)
    if args.files:
        repo_root = os.path.realpath(git_cwd)
        safe_files = []
        for f in args.files:
            resolved = os.path.realpath(os.path.join(repo_root, f))
            if not resolved.startswith(repo_root + os.sep) and resolved != repo_root:
                from aegis_cli import sanitize_display
                print(f"Warning: skipping out-of-tree file: {sanitize_display(f)}", file=sys.stderr)
                continue
            safe_files.append(f)
        if not safe_files:
            print("Error: all specified files are outside the repository", file=sys.stderr)
        return safe_files

    files: list[str] = []
    for cmd in (
        ["git", "diff", "--name-only", "--diff-filter=ACMR", "HEAD"],
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"],
    ):
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=10, cwd=git_cwd)
            found = [f.strip() for f in res.stdout.splitlines() if f.strip()]
            files = list(dict.fromkeys(files + found))
        except (subprocess.SubprocessError, FileNotFoundError):
            pass

    if not files:
        base_candidates = []
        if os.environ.get("GITHUB_BASE_REF"):
            base_ref = os.environ["GITHUB_BASE_REF"]
            base_candidates.extend([f"origin/{base_ref}...HEAD", f"{base_ref}...HEAD"])
        base_candidates.extend(["origin/main...HEAD", "main...HEAD", "origin/develop...HEAD", "develop...HEAD", "HEAD~1"])
        for ref in base_candidates:
            try:
                res = subprocess.run(
                    ["git", "diff", "--name-only", "--diff-filter=ACMR", ref],
                    capture_output=True, text=True, timeout=10, cwd=git_cwd,
                )
                if res.returncode == 0:
                    cand_files = [f.strip() for f in res.stdout.splitlines() if f.strip()]
                    if cand_files:
                        files = cand_files
                        setattr(args, "_diff_base", ref)
                        break
            except (subprocess.SubprocessError, FileNotFoundError):
                pass
    return files


def discover_test_evidence(target_files: list[str], repo_root: str) -> tuple[list[str], str]:
    """Discover matching test files, parse test names via AST, and execute tests."""
    from aegis_core.verification.test_runner import discover_test_evidence as _core_discover
    return _core_discover(target_files, repo_root)


def resolve_task_plan(args: argparse.Namespace, repo_root: str) -> str | None:
    """Resolve task plan from --plan, --plan-file, or standard plan conventions."""
    if getattr(args, "plan", None):
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

    for default_name in ("docs/plan.md", ".aegis/plan.md", "PLAN.md"):
        cand = os.path.join(repo_root, default_name)
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
    from aegis_core.verification import VerificationPipeline, runner
    from aegis_core.workspace import Workspace

    hook = bool(getattr(args, "hook", False))
    layer2 = bool(getattr(args, "full", False) or getattr(args, "plan", None) or getattr(args, "plan_file", None))
    if hook and layer2:
        return _usage_error("--hook runs Layer 1 only; drop --full, --plan and --plan-file")

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
        if getattr(args, "plan_file", None) and task_plan is None:
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
        summary = "Layer 1: 0 files changed (clean repository)"
        if use_json:
            payload = format_layer1_json_payload(not blocking, [], [], summary)
            payload["checkpoint_issues"] = issues
            print(json.dumps(payload, indent=2))
        else:
            print(summary)
        return 1 if blocking else 0

    try:
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
    summary = runner.format_summary(results)
    if not use_json:
        for r in results:
            if not r.verdict:
                print(f"🔴 {r.tool}: {r.target} — {r.detail}")
        print(summary)

    def _record_telemetry(passed: bool, verdict: Any) -> None:
        # Advisory rule-trigger telemetry: it must never change the verdict.
        try:
            from aegis_core.outcomes import record_verification_telemetry
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

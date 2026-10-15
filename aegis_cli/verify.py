"""soma verify — run verification on changed files.

Supports Layer 1 (deterministic tools) and Layer 2 (adversarial LLM pair).
Maps Verdict outcomes to exit codes: SHIP=0, BLOCK=1, REVISE=1.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any

from aegis_cli.base import CommandCategory, AegisCommand
from aegis_cli.formatters import (
    format_in_band_charge_sheet,
    format_layer1_json_payload,
    format_layer2_summary,
)

__all__ = [
    "run_verify",
    "VerifyCommand",
    "format_layer2_summary",
]


def _get_verification():
    from aegis_core.verification import runner, Verdict
    return runner, Verdict


def _lazy_verdict():
    from aegis_core.verification import Verdict
    return Verdict


class _VerdictExitCodesProxy(dict):
    """Lazy dict proxy for VERDICT_EXIT_CODES."""
    _loaded = False

    def _ensure(self):
        if not self._loaded:
            V = _lazy_verdict()
            super().__setitem__(V.SHIP, 0)
            super().__setitem__(V.BLOCK, 1)
            super().__setitem__(V.REVISE, 1)
            self._loaded = True

    def __getitem__(self, key):
        self._ensure()
        return super().__getitem__(key)

    def __contains__(self, key):
        self._ensure()
        return super().__contains__(key)

    def __len__(self):
        self._ensure()
        return super().__len__()

    def __iter__(self):
        self._ensure()
        return super().__iter__()


VERDICT_EXIT_CODES = _VerdictExitCodesProxy()


def verdict_to_exit_code(verdict) -> int:
    """Map a Verdict enum to an exit code."""
    VERDICT_EXIT_CODES._ensure()
    return VERDICT_EXIT_CODES[verdict]


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


def is_usable_provider(provider) -> bool:
    """Return True if provider can perform programmatic generation."""
    if provider is None:
        return False
    try:
        from aegis_core.inference_provider import PromptOnlyProvider
        if isinstance(provider, PromptOnlyProvider):
            return False
    except ImportError:
        pass
    return hasattr(provider, "generate") or callable(provider)


def resolve_cli_provider(args: argparse.Namespace, repo_root: str):
    """Resolve configured inference provider or return None if none available."""
    try:
        from aegis_core.inference_provider import resolve_key, resolve_provider
    except ImportError:
        return None

    explicit_provider = getattr(args, "provider", None) or resolve_key(repo_root, ["AEGIS_INFERENCE_PROVIDER"])
    if not explicit_provider:
        has_key = any(
            resolve_key(repo_root, [k])
            for k in ["GEMINI_API_KEY", "GOOGLE_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY"]
        )
        if not has_key:
            return None

    try:
        provider = resolve_provider(workspace=repo_root, provider_name=explicit_provider)
        if not is_usable_provider(provider) and explicit_provider not in ("prompt-only", "prompt"):
            return None
        return provider
    except Exception as e:
        print(f"Warning: could not initialize inference provider: {e}", file=sys.stderr)
        return None


def run_verify(args: argparse.Namespace) -> int:
    """Run verification on target files. Returns 0 for SHIP, 1 for BLOCK/REVISE or errors."""
    runner, Verdict = _get_verification()
    from aegis_core.workspace import Workspace

    ws_obj = getattr(args, "ws", None) or Workspace.resolve(
        getattr(args, "workspace", None)
        or getattr(args, "repo_root", None)
        or getattr(args, "_project_root", None)
        or getattr(args, "_root", None)
    )
    repo_root = str(ws_obj.root)
    if not os.path.isdir(repo_root):
        print(f"Error: repo root does not exist: {repo_root}", file=sys.stderr)
        return 1

    fmt = str(getattr(args, "format", None) or "text").lower()
    use_json = bool(getattr(args, "json", False) or fmt == "json")

    if getattr(args, "hook", False):
        from aegis_cli.check import run_check
        return run_check(args)

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
        layer_mode = "Layer 1 only" if getattr(args, "layer1_only", False) else "Layer 1 + Layer 2"
        if use_json:
            print(json.dumps({"dry_run": True, "mode": layer_mode, "repo_root": repo_root, "files": target_files}, indent=2))
            return 0
        print(f"Dry run — {layer_mode}\nRepo root: {repo_root}\nFiles to verify ({len(target_files)}):")
        for f in target_files:
            print(f"  {f}")
        return 0

    if not target_files:
        if use_json:
            print(json.dumps({"passed": True, "files": [], "layer1": [], "summary": "Layer 1: 0 files changed (clean repository)"}, indent=2))
            return 0
        print("Layer 1: 0 files changed (clean repository)")
        return 0

    fast_mode = getattr(args, "fast", False) or getattr(args, "fast_mode", False) or getattr(args, "hook", False)
    results = runner.run_layer1(
        changed_files=target_files,
        repo_root=repo_root,
        fast_mode=fast_mode,
        diff_base=getattr(args, "_diff_base", None),
    )

    layer1_pass = runner.gate_verdict(results)
    summary = runner.format_summary(results)
    if not use_json:
        if not layer1_pass:
            for r in results:
                if not r.verdict:
                    print(f"🔴 {r.tool}: {r.target} — {r.detail}")
        print(summary)

    def _record_telemetry(passed: bool, verdict: Any):
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

    if getattr(args, "layer1_only", False):
        _record_telemetry(layer1_pass, "PASS" if layer1_pass else "FAIL")
        if use_json:
            print(json.dumps(format_layer1_json_payload(layer1_pass, target_files, results, summary), indent=2))
        return 0 if layer1_pass else 1

    if getattr(args, "in_band", False):
        from aegis_core.verification import VerificationPipeline
        pipeline = VerificationPipeline()
        pipeline_res = pipeline.run(
            changed_files=target_files,
            workspace=ws_obj,
            task_plan=resolve_task_plan(args, repo_root) or "Interactive in-band verification",
            in_band=True,
            rebuttal=None,
        )
        if pipeline_res.charge_sheet:
            print(format_in_band_charge_sheet(pipeline_res.charge_sheet))
            _record_telemetry(False, "REVISE")
            return 1

    provider = resolve_cli_provider(args, repo_root)
    if provider is None:
        _record_telemetry(layer1_pass, "PASS" if layer1_pass else "FAIL")
        if not layer1_pass:
            return 1
        print("Notice: No inference provider configured. Layer 2 skipped (Layer 1 deterministic checks passed).", file=sys.stderr)
        return 0

    task_plan = resolve_task_plan(args, repo_root)
    if getattr(args, "plan_file", None) and task_plan is None:
        return 1

    if not task_plan:
        _record_telemetry(layer1_pass, "PASS" if layer1_pass else "FAIL")
        if not layer1_pass:
            return 1
        print("Notice: No task plan provided (--plan or --plan-file). Layer 2 skipped (Layer 1 deterministic checks passed).", file=sys.stderr)
        return 0

    llm_backend = provider.generate if hasattr(provider, "generate") else provider
    try:
        test_names, test_results = discover_test_evidence(target_files, repo_root)
    except Exception as e:
        print(f"Error: Test discovery and execution failed: {e}", file=sys.stderr)
        _record_telemetry(False, "BLOCK")
        return 1

    from aegis_core.verification import VerificationPipeline
    pipeline = VerificationPipeline()
    try:
        pipeline_res = pipeline.run(
            changed_files=target_files,
            workspace=ws_obj,
            task_plan=task_plan,
            backend=llm_backend,
            test_names=test_names,
            test_results=test_results,
            layer1_evidence=results,
        )
    except Exception as e:
        print(f"Error: Layer 2 verification failed: {e}", file=sys.stderr)
        _record_telemetry(False, "BLOCK")
        return 1

    if pipeline_res.arbitration_result:
        print(format_layer2_summary(pipeline_res.arbitration_result))

    l2_exit = verdict_to_exit_code(pipeline_res.verdict)
    overall_passed = bool(layer1_pass and l2_exit == 0)
    _record_telemetry(overall_passed, pipeline_res.verdict)
    return 0 if (layer1_pass and l2_exit == 0) else 1


class VerifyCommand(AegisCommand):
    """Command to run verification on changed files."""

    name = "verify"
    aliases = ("check",)
    category = CommandCategory.WORKFLOW
    help = "Run verification on changed files"

    def configure_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--files", nargs="*", default=None, help="Explicit list of files to verify")
        parser.add_argument("--hook", action="store_true", help="Run pre-commit fast gate (used by git pre-commit hook)")
        parser.add_argument("--layer1-only", action="store_true", help="Skip Layer 2 (fast deterministic checks only)")
        parser.add_argument("--dry-run", action="store_true", help="Show what would be checked without running")
        parser.add_argument("--plan", default=None, help="Task plan or prompt context for Layer 2 adversarial verification")
        parser.add_argument("--plan-file", default=None, help="Path to file containing task plan or prompt context")
        parser.add_argument("--provider", default=None, help="Inference provider to use (gemini, anthropic, openai, keyring, prompt)")
        parser.add_argument("--in-band", action="store_true", help="Generate an in-band charge sheet for conversational rebuttal (zero external API keys)")
        existing_fmt = parser._option_string_actions.pop("--format", None)
        if existing_fmt is not None:
            if existing_fmt in parser._actions:
                parser._actions.remove(existing_fmt)
            for group in getattr(parser, "_action_groups", ()):
                if existing_fmt in group._group_actions:
                    group._group_actions.remove(existing_fmt)
        parser.add_argument("--format", choices=["text", "json"], default="text", help="Output format (text, json)")

    def execute(self, args: argparse.Namespace) -> int:
        return run_verify(args)


if __name__ == "__main__":  # pragma: no cover
    from aegis_cli.cli import main
    sys.exit(main(["verify"] + sys.argv[1:]))



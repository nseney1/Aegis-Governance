"""Lifecycle hook runtime execution: pre-commit, pre-invocation, session-close, and unified dispatch."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any

from aegis_cli.hooks.management import (
    run_hook_install,
    run_hook_status,
    run_hook_uninstall,
)
from aegis_cli.hooks.safety import _find_gate_log_dir, run_safety_gate
from aegis_cli.base import CommandCategory, SomaCommand

__all__ = ["run_hook", "HookCommand", "run_pre_commit", "run_pre_invocation", "run_session_close"]


def run_pre_invocation(
    payload: dict[str, Any] | None = None,
    workspace: Path | None = None,
) -> tuple[int, dict[str, Any]]:
    """Run pre-invocation checks on session start and periodically.

    - Detects coding projects and suggests session-preflight.
    - Checks for pending critical proposals and rotates them.
    """
    data = payload or {}
    invocation_num = int(data.get("invocationNum", 1))

    # Run on first invocation and every 100th invocation
    if invocation_num != 1 and (invocation_num % 100) != 0:
        return 0, {}

    ws_list = data.get("workspacePaths", [])
    target_str = ws_list[0] if ws_list else (str(workspace) if workspace else os.getcwd())
    target = Path(target_str)

    response: dict[str, Any] = {}
    steps: list[dict[str, Any]] = []

    # Project detection (invocation 1 only)
    is_gov = any(k in target_str.lower() for k in ["soma", "ai-conversation-logs"])
    if invocation_num == 1 and target.is_dir() and not is_gov:
        markers: list[str] = []
        if any((target / f).exists() for f in ["venv", ".venv", "requirements.txt", "pyproject.toml"]):
            markers.append("python")
        if (target / "package.json").exists():
            markers.append("node")
        if (target / "Makefile").exists():
            markers.append("Makefile")
        if (target / "tests").is_dir():
            markers.append("tests/")

        if "python" in markers or "node" in markers:
            marker_str = ", ".join(markers)
            steps.append({
                "ephemeralMessage": (
                    f"⚡ PREFLIGHT: Coding project detected at {target_str} ({marker_str}). "
                    "Per session-preflight skill, verify venv health, git status, and test suite "
                    "before modifying files."
                )
            })

    # Critical proposals check
    log_dir = _find_gate_log_dir(target)
    pending_crit = log_dir / "pending_critical.md"
    last_crit = log_dir / "last_critical.md"

    if pending_crit.is_file():
        try:
            content = pending_crit.read_text(encoding="utf-8")
            pending_crit.replace(last_crit)
            steps.append({
                "criticalMessage": f"🔴 CRITICAL GOVERNANCE ALERT:\n{content}"
            })
        except OSError:
            pass

    if steps:
        response["injectSteps"] = steps
        response["steps"] = steps

    return 0, response


def run_session_close(workspace: Path | None = None) -> tuple[int, dict[str, Any]]:
    """Run session close lifecycle tasks (outcome evaluation, cell evolution, and consolidation)."""
    import random

    root = workspace or Path.cwd()

    # 1. Outcome engine (in-process ACE reflector)
    try:
        from aegis_core.telemetry import run_outcome_engine

        run_outcome_engine(workspace=str(root))
    except Exception:
        pass

    # 2. Cell fitness calculation
    try:
        from aegis_core.lifecycle import compute_cells_fitness

        compute_cells_fitness(workspace=str(root))
    except Exception:
        pass

    # 3. Cell selection pressure (archive extinct cells)
    try:
        from aegis_core.lifecycle import run_cell_selection

        run_cell_selection(workspace=root, execute=True)
    except Exception:
        pass

    return 0, {}


def run_pre_commit(
    workspace: Path | None = None,
    strict: bool = False,
    use_json: bool = False,
) -> int:
    """Run pre-commit checks: checkpoint quality, cell triggers, and enforcement."""
    import fnmatch

    root = workspace or Path.cwd()
    repo_root = root

    # 1. Deterministic quality checkpoint
    try:
        from aegis_core.verification.checkpoint_checks import run_all_checks

        issues = run_all_checks(root)
    except ImportError:
        issues = []

    has_checkpoint_issues = len(issues) > 0

    # 2. Check staged files against cell target paths
    staged_files: list[str] = []
    try:
        out = subprocess.check_output(
            ["git", "diff", "--name-only", "--cached"],
            cwd=repo_root,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        staged_files = [line.strip() for line in out.splitlines() if line.strip()]
    except Exception:
        pass

    cells_dir = repo_root / ".soma" / "cells"
    all_target_patterns: list[str] = []
    triggered_cells: list[str] = []

    if cells_dir.is_dir() and staged_files:
        from aegis_sdk.cells import parse_cell_file

        for cell_file in cells_dir.glob("**/*.md"):
            if cell_file.name == "README.md":
                continue
            try:
                fm, _ = parse_cell_file(cell_file)
                targets = fm.get("target_paths", [])
                all_target_patterns.extend(targets)
                hypothesis = fm.get("hypothesis", "")

                matched = False
                for sf in staged_files:
                    for tp in targets:
                        if fnmatch.fnmatch(sf, tp) or fnmatch.fnmatch(sf, f"*{tp}*"):
                            matched = True
                            break
                    if os.path.basename(sf) in hypothesis:
                        matched = True
                    if matched:
                        break
                if matched:
                    triggered_cells.append(cell_file.stem)
            except Exception:
                continue

    info_file = sys.stderr if use_json else sys.stdout

    if triggered_cells:
        print(f"🧬 Soma: {len(triggered_cells)} governance cell(s) triggered by this commit ({', '.join(triggered_cells)})", file=info_file)

    # 3. Mechanical enforcement scripts
    mechanical_failed = False
    enforcement_dir = repo_root / ".soma" / "enforcement"
    if enforcement_dir.is_dir():
        for check in sorted(enforcement_dir.glob("check-*")):
            if check.is_file():
                try:
                    if check.suffix == ".py":
                        cmd = [sys.executable, str(check)]
                    elif check.suffix in [".sh", ""] and os.name != "nt":
                        cmd = ["bash", str(check)]
                    elif check.suffix in [".bat", ".cmd"]:
                        cmd = [str(check)]
                    else:
                        continue
                    res = subprocess.run(cmd, cwd=repo_root, capture_output=True, text=True)
                    if res.returncode != 0:
                        mechanical_failed = True
                        print(f"❌ Mechanical enforcement check failed: {check.name}", file=sys.stderr)
                        if res.stderr:
                            print(res.stderr.strip(), file=sys.stderr)
                except Exception as exc:
                    mechanical_failed = True
                    print(f"❌ Failed to run mechanical check {check.name}: {exc}", file=sys.stderr)

    # 4. Uncovered new files check
    new_files: list[str] = []
    try:
        out_new = subprocess.check_output(
            ["git", "diff", "--cached", "--diff-filter=A", "--name-only"],
            cwd=repo_root,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        new_files = [line.strip() for line in out_new.splitlines() if line.strip()]
    except Exception:
        pass

    uncovered_files = [
        nf for nf in new_files
        if all_target_patterns and not any(fnmatch.fnmatch(nf, p) for p in all_target_patterns)
    ]
    if uncovered_files:
        print("🔴 New files without governance coverage:", file=info_file)
        for uf in uncovered_files:
            print(f"  ⚠️  {uf}", file=info_file)

    if mechanical_failed:
        print("❌ Commit blocked by mechanical enforcement gates.", file=sys.stderr)
        if use_json:
            print(json.dumps({
                "status": "blocked",
                "reason": "mechanical_enforcement_failed",
                "triggered_cells": triggered_cells,
                "uncovered_files": uncovered_files,
                "checkpoint_issues": issues,
            }))
        return 1

    if has_checkpoint_issues:
        if strict:
            print("❌ Commit blocked: quality checkpoint failed in strict mode.", file=sys.stderr)
            if use_json:
                print(json.dumps({
                    "status": "blocked",
                    "reason": "checkpoint_failed",
                    "triggered_cells": triggered_cells,
                    "uncovered_files": uncovered_files,
                    "checkpoint_issues": issues,
                }))
            return 1
        else:
            print(f"⚠️  Quality checkpoint found {len(issues)} issue(s) (warn mode; commit allowed).", file=info_file)

    # 5. Non-Bypassable Layer 1 Deterministic Verification on staged files
    staged_py_files = [
        sf for sf in staged_files
        if sf.endswith(".py") and os.path.exists(os.path.join(repo_root, sf))
    ]
    if staged_py_files:
        try:
            from aegis_core.verification import runner

            l1_results = runner.run_layer1(
                changed_files=staged_py_files,
                repo_root=str(repo_root),
                fast_mode=True,
            )
            l1_passed = runner.gate_verdict(l1_results)
            if not l1_passed:
                print("❌ Staged-file Layer 1 deterministic verification failed:", file=sys.stderr)
                for r in l1_results:
                    if not r.verdict:
                        print(f"  🔴 {r.tool}: {r.target} — {r.detail}", file=sys.stderr)
                if use_json:
                    print(json.dumps({
                        "status": "blocked",
                        "reason": "layer1_failed",
                        "layer1_evidence": [
                            {"tool": r.tool, "target": r.target, "verdict": r.verdict, "detail": r.detail}
                            for r in l1_results
                        ],
                    }))
                return 1
            elif not use_json:
                print(f"🛡️ Soma: Layer 1 deterministic verification passed ({len(staged_py_files)} staged file(s))", file=info_file)
        except Exception as exc:
            if strict:
                print(f"❌ Failed to execute Layer 1 verification in strict mode: {exc}", file=sys.stderr)
                return 1

    if use_json:
        print(json.dumps({
            "status": "ok",
            "triggered_cells": triggered_cells,
            "uncovered_files": uncovered_files,
            "checkpoint_issues": issues,
        }))

    return 0


def run_hook(args: Any) -> int:
    """Hybrid dispatcher routing porcelain commands or legacy lifecycle phases."""
    action = getattr(args, "hook_action", None) or getattr(args, "phase", None)

    if action == "install":
        return run_hook_install(args)
    elif action == "status":
        return run_hook_status(args)
    elif action == "uninstall":
        return run_hook_uninstall(args)
    elif action is None:
        return run_hook_status(args)

    phase = action
    workspace = Path(args.workspace) if getattr(args, "workspace", None) else Path.cwd()

    if phase == "safety-gate":
        cmd = getattr(args, "cmd", None)
        payload = None
        if cmd is None and not sys.stdin.isatty():
            try:
                raw = sys.stdin.read().strip()
                if raw:
                    payload = json.loads(raw)
            except Exception:
                pass
        rc, res = run_safety_gate(cmd=cmd, payload=payload, workspace=workspace)
        print(json.dumps(res))
        return rc

    elif phase in ("pre-invocation", "governance-monitor", "immune-init"):
        payload = None
        if not sys.stdin.isatty():
            try:
                raw = sys.stdin.read().strip()
                if raw:
                    payload = json.loads(raw)
            except Exception:
                pass
        rc, res = run_pre_invocation(payload=payload, workspace=workspace)
        print(json.dumps(res))
        return rc

    elif phase == "post-session":
        from aegis_core.sync import run_post_session_hook

        transcript_arg = getattr(args, "transcript", None)
        transcript_path = Path(transcript_arg) if transcript_arg else None
        use_json = getattr(args, "json", False)
        if not transcript_path and not sys.stdin.isatty():
            try:
                raw = sys.stdin.read().strip()
                if raw:
                    data = json.loads(raw)
                    t_str = data.get("transcript_path") or data.get("transcript")
                    if t_str:
                        transcript_path = Path(t_str)
            except Exception:
                pass

        if transcript_path and transcript_path.is_file():
            if use_json:
                rc = run_post_session_hook(transcript_path=transcript_path, repo_root=workspace, use_json=True)
            else:
                rc = run_post_session_hook(transcript_path=transcript_path, repo_root=workspace)
            return rc
        else:
            if use_json:
                print(json.dumps({"status": "skipped", "reason": "transcript not provided"}))
            else:
                print("Skipping post-session hook: transcript file not provided or does not exist", file=sys.stderr)
            return 0

    elif phase in ("session-close", "stop"):
        rc, res = run_session_close(workspace=workspace)
        print(json.dumps(res))
        return rc

    elif phase == "pre-commit":
        strict = getattr(args, "strict", False)
        use_json = getattr(args, "json", False)
        return run_pre_commit(workspace=workspace, strict=strict, use_json=use_json)

    else:
        print(f"Unknown hook command or phase: {phase}", file=sys.stderr)
        return 1


class HookCommand(SomaCommand):
    """Command to manage and run cross-platform lifecycle hooks."""

    name = "hook"
    category = CommandCategory.PLUMBING
    help = "Manage and run cross-platform lifecycle hooks"

    def configure_parser(self, parser: Any, parents: Any = None) -> None:
        p_hook_sub = parser.add_subparsers(dest="hook_action")
        p_parents = parents or []

        # Porcelain subcommands
        p_hook_install = p_hook_sub.add_parser("install", parents=p_parents, help="Install pre-commit hook into git repository")
        p_hook_install.add_argument("--force", action="store_true", help="Overwrite symlinks pointing outside repository")
        p_hook_install.add_argument("--dry-run", action="store_true", help="Preview without creating or modifying hook")

        p_hook_sub.add_parser("status", parents=p_parents, help="Inspect pre-commit hook and interpreter status")

        p_hook_uninstall = p_hook_sub.add_parser("uninstall", parents=p_parents, help="Safely remove Soma pre-commit hook")
        p_hook_uninstall.add_argument("--force", action="store_true", help="Force removal")
        p_hook_uninstall.add_argument("--dry-run", action="store_true", help="Preview without modifying disk")

        # Lifecycle phases
        p_h_precommit = p_hook_sub.add_parser("pre-commit", parents=p_parents, help="Run pre-commit quality check")
        p_h_precommit.add_argument("--strict", action="store_true", help="In pre-commit, exit 1 on issues")

        p_h_safety = p_hook_sub.add_parser("safety-gate", parents=p_parents, help="PreToolUse safety check")
        p_h_safety.add_argument("--cmd", type=str, default=None, help="Command line string for safety-gate check")

        p_hook_sub.add_parser("pre-invocation", parents=p_parents, help="PreInvocation monitor")
        p_hook_sub.add_parser("session-close", parents=p_parents, help="Post-session close")

        p_h_post = p_hook_sub.add_parser("post-session", parents=p_parents, help="Post-session hook")
        p_h_post.add_argument("--transcript", default=None, help="Path to transcript.jsonl for post-session hook")

        for alias in ("governance-monitor", "immune-init", "stop"):
            p_hook_sub.add_parser(alias, parents=p_parents, help=f"Hook phase {alias}")

    def execute(self, args: Any) -> int:
        return run_hook(args)

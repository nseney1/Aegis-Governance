"""`aegis hook`: manage the git pre-commit hook, run the agent-host PreToolUse hook,
and the isolated safety gate.

The commit gate itself is `aegis check --hook`, which the installed hook runs.
`aegis hook run pre-tool --host <h>` is what the per-host hook registrations call
(aegis_cli/hooks/pretool.py); ``cli.main`` dispatches that form before it parses or
attaches a workspace, so the parser below serves its help and a form with global
options first (``aegis --plain hook run ...``). Agent-side lifecycle phases (pre-invocation,
session-close, post-session, ...) were cut in v4 (ADR 0005 D15). `safety-gate`
stays as a manual check of one command (it fails closed: it asks).
"""
from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Any

from aegis_cli.base import AegisCommand, CommandCategory
from aegis_cli.hooks.management import (
    run_hook_install,
    run_hook_status,
    run_hook_uninstall,
)
from aegis_cli.hooks.safety import run_safety_gate

__all__ = ["run_hook", "HookCommand"]


def _run_safety_gate(args: Any) -> int:
    workspace = Path(args.workspace) if getattr(args, "workspace", None) else Path.cwd()
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


def run_hook(args: Any) -> int:
    """Dispatch `aegis hook <action>`; no action shows the hook status."""
    action = getattr(args, "hook_action", None)
    if action == "install":
        return run_hook_install(args)
    if action == "uninstall":
        return run_hook_uninstall(args)
    if action == "safety-gate":
        return _run_safety_gate(args)
    if action == "run":
        # Imported here: every aegis command loads this module, and only hooks need the
        # guard, the payload normalization and the events log.
        from aegis_cli.hooks.pretool import run_hook_run

        return run_hook_run(args)
    return run_hook_status(args)


class HookCommand(AegisCommand):
    """Manage the git pre-commit hook."""

    name = "hook"
    category = CommandCategory.PLUMBING
    help = "Install, inspect or remove the git pre-commit hook"

    def configure_parser(self, parser: Any, parents: Any = None) -> None:
        p_hook_sub = parser.add_subparsers(dest="hook_action")
        p_parents = parents or []

        p_hook_install = p_hook_sub.add_parser("install", parents=p_parents, help="Install the pre-commit hook into the git repository")
        p_hook_install.add_argument("--force", action="store_true", help="Overwrite symlinks pointing outside repository")
        p_hook_install.add_argument("--dry-run", action="store_true", help="Preview without creating or modifying hook")

        p_hook_sub.add_parser("status", parents=p_parents, help="Inspect the pre-commit hook and the interpreter it runs")

        p_hook_uninstall = p_hook_sub.add_parser("uninstall", parents=p_parents, help="Remove the aegis block from the pre-commit hook")
        p_hook_uninstall.add_argument("--force", action="store_true", help="Force removal")
        p_hook_uninstall.add_argument("--dry-run", action="store_true", help="Preview without modifying disk")

        p_h_run = p_hook_sub.add_parser(
            "run", parents=p_parents,
            help="Run the agent-host hook on the payload on stdin (what host hook registrations call)",
            description=(
                "Reads the host's PreToolUse JSON on stdin and never prints on stdout. Exit 0 allows, "
                "and also follows any error, a timeout, an unknown host or event and an ungoverned "
                "workspace: the hooks fail open. Exit 2 blocks on claude-code and codex-cli (reason on "
                "stderr); exit 75 blocks on antigravity, whose registration maps it to 1."
            ),
        )
        p_h_run.add_argument("event", nargs="?", default=None, metavar="EVENT", help="The hook event: pre-tool")
        p_h_run.add_argument("--host", default=None, metavar="HOST",
                             help="The host whose payload is on stdin: claude-code, codex-cli or antigravity")

        p_h_safety = p_hook_sub.add_parser("safety-gate", parents=p_parents, help="Check a shell command against the safety gate (prints a JSON decision)")
        p_h_safety.add_argument("--cmd", type=str, default=None, help="Command line to check (default: JSON payload on stdin)")

    def execute(self, args: Any) -> int:
        return run_hook(args)

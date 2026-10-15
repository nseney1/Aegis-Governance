"""aegis system — System diagnostics, driver management, and platform integrations.

Subcommands:
  aegis system doctor     Environmental, platform adapter, and AST driver health audit
  aegis system hook       Git pre-commit hook installation, removal, and status
  aegis system drivers    Zero-dependency AST driver inspection, provisioning, and testing
  aegis system skills     Agent skill and horizontal capability discovery and inspection
"""
from __future__ import annotations

import argparse
import sys
from typing import Any, List, Optional

from aegis_cli.base import CommandCategory, AegisCommand

__all__ = ["run_system", "SystemCommand"]


def run_system(args: argparse.Namespace) -> int:
    """Entrypoint for aegis system subcommands."""
    action = getattr(args, "system_action", None)
    if not action:
        # Default behavior: run doctor
        from aegis_cli.doctor import run_doctor
        return run_doctor(args)

    if action == "doctor":
        from aegis_cli.doctor import run_doctor
        return run_doctor(args)

    elif action == "hook":
        from aegis_cli.hooks import run_hook
        # Map sub-action if parsed under system hook
        sub_act = getattr(args, "hook_subaction", None)
        if sub_act:
            args.hook_action = sub_act
        return run_hook(args)

    elif action in ("drivers", "detect"):
        from aegis_cli.detect import run_detect
        return run_detect(args)

    elif action in ("skills", "skill"):
        from aegis_cli.skills import run_skill
        sub_act = getattr(args, "skill_subaction", None)
        if sub_act:
            args.skill_action = sub_act
        return run_skill(args)

    elif action == "compact":
        import json
        from aegis_core.telemetry import compact_signals

        ws = getattr(args, "workspace", None)
        days = int(getattr(args, "days", 30))
        dry_run = bool(getattr(args, "dry_run", False))
        use_json = bool(getattr(args, "json", False) or getattr(args, "format", None) == "json")
        result = compact_signals(workspace=ws, retention_days=days, dry_run=dry_run)
        if use_json:
            print(json.dumps(result, indent=2))
        else:
            mode_str = " (DRY RUN)" if dry_run else ""
            print(
                f"Telemetry compaction{mode_str}: {result['expired_count']} expired, "
                f"{result['retained_count']} retained (retention={days}d)"
            )
        return 0

    print(f"Unknown system subcommand: {action}", file=sys.stderr)
    return 1


class SystemCommand(AegisCommand):
    """System diagnostics, driver management, and platform integrations."""

    name = "system"
    aliases = ("sys",)
    category = CommandCategory.SETUP
    help = "Diagnostics, driver management, and platform integrations (doctor, hook, drivers, skills, compact)"

    def configure_parser(self, parser: argparse.ArgumentParser, parents: Optional[List[argparse.ArgumentParser]] = None) -> None:
        sub = parser.add_subparsers(dest="system_action", metavar="ACTION")
        p_parents = parents or []

        # doctor
        p_doc = sub.add_parser("doctor", parents=p_parents, help="Environmental and driver health check")
        p_doc.add_argument("--fix-path", action="store_true", help="Fix user PATH shell dotfiles")
        p_doc.add_argument("--fix", action="store_true", help="Auto-repair detected issues")
        p_doc.add_argument("--drivers", action="store_true", help="Check AST drivers only")
        p_doc.add_argument("--yes", "-y", action="store_true", help="Bypass confirmation prompts")
        if not any(a.dest == "json" for a in p_doc._actions):
            p_doc.add_argument("--json", action="store_true", help="Emit JSON output")
        if not any(a.dest == "workspace" for a in p_doc._actions):
            p_doc.add_argument("--workspace", default=None, help="Target workspace path")

        # hook
        p_hook = sub.add_parser("hook", parents=p_parents, help="Manage git pre-commit hooks")
        p_hook_sub = p_hook.add_subparsers(dest="hook_subaction", metavar="HOOK_ACTION")
        
        p_h_inst = p_hook_sub.add_parser("install", parents=p_parents, help="Install pre-commit hook")
        p_h_inst.add_argument("--force", action="store_true", help="Overwrite existing hooks or symlinks")
        p_h_inst.add_argument("--dry-run", action="store_true", help="Preview changes without writing")

        p_h_uninst = p_hook_sub.add_parser("uninstall", parents=p_parents, help="Uninstall pre-commit hook")
        p_h_uninst.add_argument("--force", action="store_true", help="Force removal")
        p_h_uninst.add_argument("--dry-run", action="store_true", help="Preview changes without writing")

        p_h_stat = p_hook_sub.add_parser("status", parents=p_parents, help="Inspect git hook status")

        # drivers
        p_drv = sub.add_parser("drivers", aliases=["detect"], parents=p_parents, help="Inspect and provision AST drivers")
        p_drv.add_argument("--fix", action="store_true", help="Auto-provision missing AST drivers")
        p_drv.add_argument("--dry-run", action="store_true", help="Simulate provisioning without writing")
        if not any(a.dest == "workspace" for a in p_drv._actions):
            p_drv.add_argument("--workspace", default=None, help="Target workspace path")

        # skills
        p_skl = sub.add_parser("skills", parents=p_parents, help="Inspect agent skills and slots")
        p_skl_sub = p_skl.add_subparsers(dest="skill_subaction", metavar="SKILL_ACTION")
        
        p_s_list = p_skl_sub.add_parser("list", parents=p_parents, help="List available skills")

        p_s_insp = p_skl_sub.add_parser("inspect", parents=p_parents, help="Inspect a specific skill")
        p_s_insp.add_argument("target_skill", help="ID of skill to inspect")

        p_s_slots = p_skl_sub.add_parser("slots", parents=p_parents, help="List active skill slots")

        # compact
        p_cmp = sub.add_parser("compact", parents=p_parents, help="Compact expired telemetry signals into compressed archives")
        p_cmp.add_argument("--days", type=int, default=30, help="Retention window in days (default: 30)")
        p_cmp.add_argument("--dry-run", action="store_true", help="Preview compaction without modifying files")
        if not any(a.dest == "json" for a in p_cmp._actions):
            p_cmp.add_argument("--json", action="store_true", help="Emit JSON output")
        if not any(a.dest == "workspace" for a in p_cmp._actions):
            p_cmp.add_argument("--workspace", default=None, help="Target workspace path")

    def execute(self, args: argparse.Namespace) -> int:
        return run_system(args)


if __name__ == "__main__":  # pragma: no cover
    from aegis_cli.cli import main
    sys.exit(main(["system"] + sys.argv[1:]))

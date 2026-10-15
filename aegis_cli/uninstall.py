"""aegis uninstall — remove a platform's Aegis rules, the git hook, and optionally .aegis/."""
from __future__ import annotations

import argparse
import sys

from aegis_cli.base import CommandCategory, AegisCommand

__all__ = ["run_uninstall", "UninstallCommand"]


def run_uninstall(args: argparse.Namespace) -> int:
    """Uninstall Aegis rules and configuration for the given platform."""
    from pathlib import Path
    import shutil
    from aegis_cli.hooks import uninstall_hook
    from aegis_cli.platforms import get_adapter

    platform = getattr(args, "platform", None) or "gemini"
    local = getattr(args, "local", False)
    dry_run = getattr(args, "dry_run", False)
    purge = getattr(args, "purge", False)
    workspace = getattr(args, "_project_root", None)
    ws_path = Path(workspace) if workspace else Path.cwd()

    try:
        adapter = get_adapter(platform, workspace=ws_path)
        res = adapter.uninstall(local=local, dry_run=dry_run)

        # 1. Clean pre-commit hook
        try:
            if uninstall_hook(project_root=ws_path, dry_run=dry_run):
                action = "[dry-run] Would remove" if dry_run else "Removed"
                res.messages.append(f"{action} pre-commit hook")
        except Exception as e:
            res.errors.append(f"Failed to remove pre-commit hook: {e}")

        # 2. Clean .aegis directory if --purge requested
        if purge:
            aegis_dir = ws_path / ".aegis"
            if aegis_dir.is_dir():
                if dry_run:
                    res.messages.append(f"[dry-run] Would remove {aegis_dir}")
                else:
                    try:
                        shutil.rmtree(aegis_dir)
                        res.messages.append(f"Purged {aegis_dir}")
                    except Exception as e:
                        res.errors.append(f"Failed to purge {aegis_dir}: {e}")
                        res.success = False

        for msg in res.messages:
            print(msg)
        for err in res.errors:
            print(f"Error: {err}", file=sys.stderr)
        return 0 if res.success else 1
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


class UninstallCommand(AegisCommand):
    """Command to uninstall Aegis governance rules and configuration."""

    name = "uninstall"
    category = CommandCategory.SETUP
    help = "Uninstall Aegis governance rules and configuration"

    def configure_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--platform",
            "-p",
            choices=["gemini", "kiro", "copilot", "claude", "mcp"],
            default=None,
            help="Target platform (default: auto-detected or gemini)",
        )
        parser.add_argument(
            "--local",
            action="store_true",
            help="Uninstall from project-local directory",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be uninstalled without deleting files",
        )
        parser.add_argument(
            "--purge",
            action="store_true",
            help="Purge .aegis directory and local governance state",
        )

    def execute(self, args: argparse.Namespace) -> int:
        return run_uninstall(args)

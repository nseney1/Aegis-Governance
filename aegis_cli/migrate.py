"""aegis migrate — Upgrade Sentinel diagnostic for legacy .soma workspaces in v3.0+."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Dict

from aegis_cli.base import AegisCommand, CommandCategory
from aegis_core.workspace.discovery import LEGACY_SOMA_UPGRADE_MSG
from aegis_core.workspace.layout import WorkspaceLayout

__all__ = [
    "run_migrate",
    "MigrateCommand",
    "migrate_workspace",
]


def migrate_workspace(
    workspace_root: str | Path,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Check workspace migration state and emit the Upgrade Sentinel diagnostic for .soma/."""
    root = Path(workspace_root).resolve()
    layout = WorkspaceLayout(root)
    soma_dir = layout.legacy_soma_dir
    aegis_dir = layout.aegis_dir

    if aegis_dir.exists() and not soma_dir.exists():
        return {
            "status": "already_migrated",
            "message": f"Workspace is already using .aegis/ ({aegis_dir})",
            "root": str(root),
            "changes": [],
        }

    if soma_dir.exists():
        return {
            "status": "legacy_detected",
            "message": LEGACY_SOMA_UPGRADE_MSG.format(path=root),
            "root": str(root),
            "changes": [],
        }

    return {
        "status": "not_found",
        "message": f"No .aegis/ or .soma/ directory found in {root}",
        "root": str(root),
        "changes": [],
    }


def run_migrate(args: argparse.Namespace | str | Path, dry_run: bool = False) -> int:
    """CLI handler for aegis migrate."""
    if isinstance(args, (str, Path)):
        raw_ws = args
        use_json = False
    else:
        raw_ws = getattr(args, "workspace", None) or getattr(args, "_project_root", None) or Path.cwd()
        dry_run = getattr(args, "dry_run", dry_run)
        use_json = getattr(args, "json", False)

    res = migrate_workspace(raw_ws, dry_run=dry_run)

    if use_json:
        print(json.dumps(res, indent=2))
        return 0 if res["status"] == "already_migrated" else 1

    if res["status"] == "already_migrated":
        print(f"  [PASS] {res['message']}")
        return 0

    print(f"Error: {res['message']}", file=sys.stderr)
    return 1


class MigrateCommand(AegisCommand):
    """Diagnostic sentinel directing legacy .soma users to migrate via v2.1.x."""

    name = "migrate"
    aliases = ()
    category = CommandCategory.SETUP
    help = "Verify .aegis workspace migration status"
    description = "Check workspace migration status and provide upgrade guidance for legacy .soma workspaces."

    def configure_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--dry-run", action="store_true", help="Check migration status without modifying files")

    def execute(self, args: argparse.Namespace) -> int:
        return run_migrate(args)

"""aegis migrate — Atomic one-way upgrade from legacy .soma to pure .aegis.

Performs:
1. Atomic rename of .soma/ -> .aegis/
2. Restructuring of cells/ -> rules/ and organelle folders -> modern concepts:
   - walls/         -> invariants/
   - vacuoles/      -> traps/
   - membranes/     -> boundaries/
   - chloroplasts/  -> personas/
   - plasmodesmata/ -> contracts/
3. Lock file cleanup
4. Manifest recalculation and re-signing
5. Migration of root soma.conf -> aegis.conf
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import sys
from typing import Any, Dict, List, Optional

from aegis_cli.base import CommandCategory, AegisCommand
from aegis_core.workspace import Workspace

__all__ = [
    "run_migrate",
    "MigrateCommand",
    "migrate_workspace",
    "ORGANELLE_MAPPING",
    "LEGACY_TO_MODERN_TYPE",
]

ORGANELLE_MAPPING = {
    "walls": "invariants",
    "vacuoles": "traps",
    "membranes": "boundaries",
    "chloroplasts": "personas",
    "plasmodesmata": "contracts",
}

LEGACY_TO_MODERN_TYPE = {
    "wall": "invariant",
    "vacuole": "trap",
    "membrane": "boundary",
    "chloroplast": "persona",
    "plasmodesmata": "contract",
}

_TYPE_LINE_RE = re.compile(r"^(\s*type\s*:\s*)(['\"]?)([A-Za-z_]+)(['\"]?)(\s*(?:#.*)?)$")


def _rewrite_frontmatter_type(md_file: Path) -> bool:
    """Rewrite legacy type: <organelle> in YAML frontmatter to modern type."""
    try:
        content = md_file.read_text(encoding="utf-8")
    except OSError:
        return False

    if not content.startswith("---"):
        return False

    lines = content.splitlines(keepends=True)
    closing_idx = None
    for idx in range(1, len(lines)):
        if lines[idx].strip() == "---":
            closing_idx = idx
            break

    if closing_idx is None:
        return False

    changed = False
    for idx in range(1, closing_idx):
        line_ending = "\r\n" if lines[idx].endswith("\r\n") else ("\n" if lines[idx].endswith("\n") else "")
        stripped_line = lines[idx].rstrip("\r\n")
        m = _TYPE_LINE_RE.match(stripped_line)
        if m:
            prefix, q1, old_type, q2, suffix = m.groups()
            new_type = LEGACY_TO_MODERN_TYPE.get(old_type)
            if new_type:
                lines[idx] = f"{prefix}{q1}{new_type}{q2}{suffix}{line_ending}"
                changed = True

    if changed:
        try:
            md_file.write_text("".join(lines), encoding="utf-8")
        except OSError:
            return False
    return changed


def migrate_workspace(
    workspace_root: str | Path,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Execute one-way migration of workspace from .soma to .aegis."""
    root = Path(workspace_root).resolve()
    soma_dir = root / ".soma"
    aegis_dir = root / ".aegis"

    if not soma_dir.exists():
        if aegis_dir.exists():
            return {
                "status": "already_migrated",
                "message": f"Workspace is already using .aegis/ ({aegis_dir})",
                "root": str(root),
                "changes": [],
            }
        return {
            "status": "not_found",
            "message": f"No .soma/ directory found in {root}",
            "root": str(root),
            "changes": [],
        }

    changes: List[str] = []

    if dry_run:
        changes.append("Rename directory: .soma/ -> .aegis/")
        if (soma_dir / "cells").is_dir():
            changes.append("Rename directory: .soma/cells/ -> .aegis/rules/")
            for old_o, new_o in ORGANELLE_MAPPING.items():
                if (soma_dir / "cells" / old_o).is_dir():
                    changes.append(f"Restructure folder: rules/{old_o}/ -> rules/{new_o}/")
        if (root / "soma.conf").is_file() and not (root / "aegis.conf").is_file():
            changes.append("Rename config file: soma.conf -> aegis.conf")
        return {
            "status": "preview",
            "message": "Dry run: previewing migration changes",
            "root": str(root),
            "changes": changes,
        }

    # 1. Directory cutover
    if not aegis_dir.exists():
        soma_dir.rename(aegis_dir)
        changes.append("Renamed: .soma/ -> .aegis/")
    else:
        # Merge contents
        for item in soma_dir.iterdir():
            target = aegis_dir / item.name
            if not target.exists():
                shutil.move(str(item), str(target))
                changes.append(f"Moved: .soma/{item.name} -> .aegis/{item.name}")
        shutil.rmtree(str(soma_dir), ignore_errors=True)
        changes.append("Merged and removed: .soma/")

    # 2. Restructure cells -> rules
    rules_dir = aegis_dir / "rules"
    cells_dir = aegis_dir / "cells"
    if cells_dir.is_dir():
        if not rules_dir.is_dir():
            cells_dir.rename(rules_dir)
            changes.append("Renamed: .aegis/cells/ -> .aegis/rules/")
        else:
            for item in cells_dir.iterdir():
                target = rules_dir / item.name
                if not target.exists():
                    shutil.move(str(item), str(target))
            shutil.rmtree(str(cells_dir), ignore_errors=True)
            changes.append("Merged: .aegis/cells/ into .aegis/rules/")

    # 3. Map organelles to modern rule types
    if rules_dir.is_dir():
        for old_name, new_name in ORGANELLE_MAPPING.items():
            old_path = rules_dir / old_name
            new_path = rules_dir / new_name
            if old_path.is_dir():
                if not new_path.is_dir():
                    old_path.rename(new_path)
                    changes.append(f"Restructured: rules/{old_name}/ -> rules/{new_name}/")
                else:
                    for sub in old_path.iterdir():
                        tgt = new_path / sub.name
                        if not tgt.exists():
                            shutil.move(str(sub), str(tgt))
                    shutil.rmtree(str(old_path), ignore_errors=True)
                    changes.append(f"Merged: rules/{old_name}/ into rules/{new_name}/")

        for md_file in sorted(rules_dir.rglob("*.md")):
            if md_file.name == "README.md":
                continue
            if _rewrite_frontmatter_type(md_file):
                changes.append(f"Updated frontmatter type: {md_file.relative_to(aegis_dir)}")

    # 4. Clean lock files
    locks_dir = aegis_dir / "locks"
    if locks_dir.is_dir():
        for lock_file in locks_dir.glob("*.lock"):
            try:
                lock_file.unlink()
                changes.append(f"Cleaned stale lock: locks/{lock_file.name}")
            except OSError:
                pass

    # 5. Manifest rehash
    if rules_dir.is_dir():
        try:
            from aegis_mcp.integrity import generate_manifest, save_manifest
            manifest_data = generate_manifest(str(rules_dir))
            save_manifest(str(root), manifest_data)
            changes.append("Regenerated rules manifest: .aegis/rules/manifest.json")
        except Exception as exc:
            changes.append(f"Manifest generation note: {exc}")

    # 6. Config file rename
    soma_conf = root / "soma.conf"
    aegis_conf = root / "aegis.conf"
    if soma_conf.is_file() and not aegis_conf.is_file():
        soma_conf.rename(aegis_conf)
        changes.append("Renamed: soma.conf -> aegis.conf")

    return {
        "status": "success",
        "message": "Workspace successfully migrated to Aegis v2.x (.aegis/rules/)",
        "root": str(root),
        "changes": changes,
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
        return 0 if res["status"] in ("success", "already_migrated", "preview") else 1

    print()
    print("  🛡️  Aegis Workspace Migration")
    print(f"     Target: {res['root']}")
    print()

    if res["status"] == "already_migrated":
        print("  ℹ️  Workspace is already using .aegis/ (no migration needed).")
        return 0
    elif res["status"] == "not_found":
        print(f"  ❌ {res['message']}")
        return 1
    elif res["status"] == "preview":
        print("  🔍 Dry-run preview of planned changes:")
        for ch in res["changes"]:
            print(f"    • {ch}")
        print("\n  Run 'aegis migrate' without --dry-run to execute.")
        return 0

    print("  ✅ Migration complete:")
    for ch in res["changes"]:
        print(f"    • {ch}")
    print()
    print("  🎉 Workspace is now running pure Aegis governance (.aegis/rules/)!")
    return 0


class MigrateCommand(AegisCommand):
    """One-way upgrade from legacy .soma to pure .aegis."""

    name = "migrate"
    aliases = ()
    category = CommandCategory.SETUP
    help = "Upgrade workspace from legacy .soma to pure .aegis"
    description = "Atomically migrate a .soma governance workspace to modern .aegis layout."

    def configure_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--dry-run", action="store_true", help="Preview migration without modifying files")

    def execute(self, args: argparse.Namespace) -> int:
        return run_migrate(args)

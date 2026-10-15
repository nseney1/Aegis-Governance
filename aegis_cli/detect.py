"""soma detect — Project language detection and AST driver inspection/provisioning."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Dict

from aegis_core.ast.detect import (
    detect_project_languages,
    provision_ast_driver_slots,
    resolve_recommended_drivers,
    LANGUAGE_DEFINITIONS,
)
from aegis_core.skills.slots import SlotRegistry
from aegis_core.workspace import Workspace
from aegis_cli.base import CommandCategory, AegisCommand

__all__ = ["run_detect", "DetectCommand"]


def run_detect(args: argparse.Namespace) -> int:
    """Detect project languages, inspect AST drivers, and optionally provision slots."""
    ws_obj = getattr(args, "ws", None) or Workspace.resolve(
        getattr(args, "workspace", None) or getattr(args, "_project_root", None)
    )
    ws_root = ws_obj.root
    dry_run = getattr(args, "dry_run", False)
    fix = getattr(args, "fix", False) or getattr(args, "provision", False)
    as_json = getattr(args, "json", False)

    detected = detect_project_languages(ws_root)
    slots_reg = SlotRegistry.load(ws_root)
    configured_exts = slots_reg.get_configured_extensions()

    created_files: list[str] = []
    if fix:
        new_slots, created_files = provision_ast_driver_slots(
            ws_root,
            detected,
            copy_drivers=True,
            dry_run=dry_run,
        )
        slots_reg = SlotRegistry.load(ws_root)
        configured_exts = slots_reg.get_configured_extensions()

    active_slots = slots_reg.to_dict()

    if as_json:
        payload = {
            "workspace": str(ws_root),
            "languages": detected,
            "configured_slots": active_slots,
            "searchable_extensions": sorted(configured_exts),
            "created_files": created_files,
        }
        print(json.dumps(payload, indent=2))
        return 0

    print(f"aegis detect — Language & AST Driver Inspection ({ws_root}):\n")

    if not detected:
        print("  ℹ️  No known programming language manifests or source files detected.")
        return 0

    print("  Discovered Languages:")
    for lang, info in sorted(detected.items()):
        exts_list = info.get("extensions", [])
        exts_str = ", ".join(exts_list)
        fcount = info.get("file_count", 0)
        toolchains = info.get("toolchains", [])
        tc_str = f", toolchains=[{', '.join(toolchains)}]" if toolchains else ""
        manifests = info.get("manifests", [])
        m_str = f"manifests=[{', '.join(manifests)}]" if manifests else ""

        # Check driver slot binding
        slot_key = f"ast_driver_{exts_list[0].lstrip('.')}" if exts_list else f"ast_driver_{lang}"
        slot_val = active_slots.get(slot_key) or active_slots.get("ast_driver")
        if lang == "python":
            status_str = "✅ native Python stdlib (in-process)"
        elif slot_val:
            status_str = f"✅ configured: {slot_val}"
        else:
            status_str = "⚠️  unconfigured (run 'aegis detect --fix' to provision)"

        meta_parts = [p for p in (f"{fcount} files" if fcount else "", m_str, tc_str.lstrip(", ")) if p]
        meta_desc = f" ({'; '.join(meta_parts)})" if meta_parts else ""
        print(f"    • {lang.title()}{meta_desc}: {status_str}")

    print("\n  Dynamically Configured Source Extensions:")
    print(f"    {', '.join(sorted(configured_exts))}")

    if fix:
        if dry_run:
            print("\n  [dry-run] AST driver slots and recipes simulated without writing to disk.")
        elif created_files:
            print(f"\n  ✅ Provisioned {len(created_files)} file(s) in .aegis/drivers/ and updated .aegis/slots.yaml")
        else:
            print("\n  ✅ AST driver slots are up-to-date in .aegis/slots.yaml")
    else:
        unconfigured = [
            lang for lang, info in detected.items()
            if lang != "python" and not any(
                active_slots.get(f"ast_driver_{e.lstrip('.')}") or active_slots.get("ast_driver")
                for e in info.get("extensions", [])
            )
        ]
        if unconfigured:
            print(f"\n  💡 Run 'aegis detect --fix' to auto-provision AST driver slots for {', '.join(u.title() for u in unconfigured)}")

    return 0


class DetectCommand(AegisCommand):
    """Command to inspect project languages and AST driver configuration."""

    name = "detect"
    aliases = ("languages", "drivers")
    category = CommandCategory.SETUP
    help = "Inspect project languages and AST driver configuration"

    def configure_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--fix",
            "--provision",
            action="store_true",
            dest="fix",
            help="Automatically provision .aegis/slots.yaml and stage driver recipes",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Preview provisioning without writing files to disk",
        )

    def execute(self, args: argparse.Namespace) -> int:
        return run_detect(args)

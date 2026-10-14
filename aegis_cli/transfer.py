"""Soma CLI — Cell Transfer command.

Copies a cell from the current project to another project with fitness reset
and lineage incrementation.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from aegis_core.somayaml import dump_frontmatter, parse_frontmatter
from aegis_core.workspace import Workspace, resolve_workspace_path as resolve_workspace
from aegis_cli.base import CommandCategory, SomaCommand

__all__ = ["run_transfer", "TransferCommand", "transfer_cell"]

CELL_TYPE_DIRS: dict[str, str] = {
    "vacuole": "vacuoles",
    "chloroplast": "chloroplasts",
    "wall": "walls",
    "membrane": "membranes",
    "plasmodesmata": "plasmodesmata",
}


def transfer_cell(
    cell_id: str,
    target_dir_str: str,
    source_workspace: Workspace | Path | None = None,
) -> int:
    """Transfer a cell from source workspace to target directory with fitness reset."""
    try:
        ws = source_workspace if isinstance(source_workspace, Workspace) else (
            Workspace.resolve(source_workspace) if source_workspace is not None else Workspace.resolve()
        )
        repo_dir = ws.root
    except Exception:
        repo_dir = None

    if repo_dir is None or not (repo_dir / ".soma" / "cells").is_dir():
        print(
            f"Error: No Soma project found: no .soma/cells/ in {repo_dir or os.getcwd()} or any parent directory.",
            file=sys.stderr,
        )
        print("Run from inside the source project, or set SOMA_ROOT to its root.", file=sys.stderr)
        return 1

    target_dir = Path(target_dir_str).resolve()
    if not (target_dir / ".soma").is_dir():
        print("Error: Target directory does not have a .soma/ directory.", file=sys.stderr)
        print("Suggest running 'install --local' in the target directory first.", file=sys.stderr)
        return 1

    cells_dir = repo_dir / ".soma" / "cells"
    matches = list(cells_dir.rglob(f"*{cell_id}*.md"))
    if not matches:
        print(f"Error: Cell matching '{cell_id}' not found in {cells_dir}/", file=sys.stderr)
        return 1

    source_cell = matches[0]
    filename = source_cell.name
    target_basename = target_dir.name
    source_basename = repo_dir.name

    try:
        content = source_cell.read_text(encoding="utf-8-sig")
    except Exception as e:
        print(f"Error reading {source_cell}: {e}", file=sys.stderr)
        return 1

    clean_content = content.lstrip("\ufeff")
    if not clean_content.startswith("---"):
        print("Error: Cell does not have YAML frontmatter.", file=sys.stderr)
        return 1

    end_idx = clean_content.find("---", 3)
    if end_idx == -1:
        print("Error: Cell has malformed YAML frontmatter.", file=sys.stderr)
        return 1

    metadata = parse_frontmatter(clean_content)
    if metadata is None:
        print("Error: Cell has malformed YAML frontmatter.", file=sys.stderr)
        return 1

    body_str = clean_content[end_idx + 3:]

    cell_type = metadata.get("type")
    if not cell_type:
        parent_name = source_cell.parent.name
        if "vacuoles" in parent_name:
            cell_type = "vacuole"
        elif "chloroplasts" in parent_name:
            cell_type = "chloroplast"
        elif "walls" in parent_name:
            cell_type = "wall"
        elif "membranes" in parent_name:
            cell_type = "membrane"
        elif "plasmodesmata" in parent_name:
            cell_type = "plasmodesmata"
        else:
            cell_type = "vacuole"

    plural_type = CELL_TYPE_DIRS.get(
        str(cell_type),
        str(cell_type) if str(cell_type).endswith("s") else f"{cell_type}s",
    )
    target_cell_dir = target_dir / ".soma" / "cells" / plural_type
    target_cell_dir.mkdir(parents=True, exist_ok=True)
    dest_file = target_cell_dir / filename

    if "fitness" not in metadata or not isinstance(metadata["fitness"], dict):
        metadata["fitness"] = {}
    metadata["fitness"]["triggers"] = 0
    metadata["fitness"]["true_positives"] = 0
    metadata["fitness"]["false_positives"] = 0
    metadata["fitness"]["score"] = None
    metadata["expiry_sessions"] = 5

    metadata["transferred_from"] = source_basename
    metadata["transfer_date"] = datetime.now(timezone.utc).isoformat() + "Z"

    gen = (
        metadata.get("lineage", {}).get("generation", 0)
        if isinstance(metadata.get("lineage"), dict)
        else 0
    )
    metadata["lineage"] = {
        "parent_id": source_cell.stem,
        "created_by": "transfer",
        "generation": gen + 1,
        "siblings": [],
    }

    try:
        new_frontmatter = dump_frontmatter(metadata)
        clean_body = body_str[1:] if body_str.startswith("\n") else body_str
        dest_file.write_text(f"---\n{new_frontmatter}---\n{clean_body}", encoding="utf-8")
    except Exception as e:
        print(f"Error writing destination file {dest_file}: {e}", file=sys.stderr)
        return 1

    metrics_dir = repo_dir / ".soma" / "metrics"
    metrics_dir.mkdir(parents=True, exist_ok=True)
    transfers_log = metrics_dir / "transfers.jsonl"
    log_entry = {
        "timestamp": datetime.now(timezone.utc).isoformat() + "Z",
        "cell": filename,
        "target_project": target_basename,
    }
    try:
        with open(transfers_log, "a", encoding="utf-8") as f:
            f.write(json.dumps(log_entry) + "\n")
    except Exception as e:
        print(f"Warning: Failed to write transfers log: {e}", file=sys.stderr)

    print(f"Transferred: {cell_id} -> {target_basename} (fitness reset, 5-session probation)")
    return 0


def export_cell(
    cell_id: str,
    tags: str | list[str] = "",
    output_path: str | Path | None = None,
    source_workspace: Workspace | Path | None = None,
) -> int:
    """Export a cell as a portable, self-contained JSON packet with tags."""
    try:
        ws = source_workspace if isinstance(source_workspace, Workspace) else (
            Workspace.resolve(source_workspace) if source_workspace is not None else Workspace.resolve()
        )
        repo_dir = ws.root
    except Exception:
        repo_dir = None

    if repo_dir is None or not (repo_dir / ".soma" / "cells").is_dir():
        print(
            f"Error: No Soma project found: no .soma/cells/ in {repo_dir or os.getcwd()} or any parent directory.",
            file=sys.stderr,
        )
        return 1

    cells_dir = repo_dir / ".soma" / "cells"
    clean_id = cell_id[:-3] if cell_id.endswith(".md") else cell_id
    matches = list(cells_dir.rglob(f"*{clean_id}*.md"))
    if not matches:
        print(f"Error: Cell matching '{cell_id}' not found in {cells_dir}/", file=sys.stderr)
        return 1

    source_cell = matches[0]
    try:
        content = source_cell.read_text(encoding="utf-8-sig")
    except Exception as e:
        print(f"Error reading {source_cell}: {e}", file=sys.stderr)
        return 1

    clean_content = content.lstrip("\ufeff")
    if not clean_content.startswith("---"):
        print("Error: Cell does not have YAML frontmatter.", file=sys.stderr)
        return 1

    end_idx = clean_content.find("---", 3)
    if end_idx == -1:
        print("Error: Cell has malformed YAML frontmatter.", file=sys.stderr)
        return 1

    metadata = parse_frontmatter(clean_content) or {}
    body_str = clean_content[end_idx + 3:].lstrip("\n")

    cell_type = metadata.get("type", "wall")
    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if isinstance(tags, str) else list(tags)

    export_meta = dict(metadata)
    export_meta["fitness"] = {
        "triggers": 0,
        "true_positives": 0,
        "false_positives": 0,
        "score": None,
    }
    export_meta["expiry_sessions"] = 5
    gen = metadata.get("lineage", {}).get("generation", 0) if isinstance(metadata.get("lineage"), dict) else 0
    export_meta["lineage"] = {
        "parent_id": source_cell.stem,
        "created_by": "hgt_export",
        "generation": gen + 1,
        "siblings": [],
    }

    packet = {
        "schema_version": "1.0",
        "cell_id": source_cell.stem,
        "type": cell_type,
        "tags": tag_list,
        "metadata": export_meta,
        "content": body_str,
        "exported_at": datetime.now(timezone.utc).isoformat() + "Z",
    }

    packet_json = json.dumps(packet, indent=2) + "\n"
    if output_path:
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(packet_json, encoding="utf-8")
        print(f"Exported: {source_cell.stem} -> {out} (tags: {tag_list})")
    else:
        print(packet_json)
    return 0


def import_cell(
    packet_path: str | Path,
    target_workspace: Workspace | Path | None = None,
) -> int:
    """Import a cell from a portable JSON packet into target workspace."""
    p = Path(packet_path)
    if not p.is_file():
        print(f"Error: Packet file '{packet_path}' not found.", file=sys.stderr)
        return 1

    try:
        packet = json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"Error parsing packet JSON: {e}", file=sys.stderr)
        return 1

    cell_id = packet.get("cell_id")
    cell_type = packet.get("type", "wall")
    metadata = packet.get("metadata", {})
    body_str = packet.get("content", "")

    if not cell_id:
        print("Error: Invalid packet: missing cell_id", file=sys.stderr)
        return 1

    try:
        ws = target_workspace if isinstance(target_workspace, Workspace) else (
            Workspace.resolve(target_workspace) if target_workspace is not None else Workspace.resolve()
        )
        target_dir = ws.root
    except Exception:
        target_dir = None

    if target_dir is None or not (target_dir / ".soma").is_dir():
        print("Error: Target workspace does not have a .soma/ directory.", file=sys.stderr)
        return 1

    plural_type = CELL_TYPE_DIRS.get(str(cell_type), f"{cell_type}s")
    dest_dir = target_dir / ".soma" / "cells" / plural_type
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_file = dest_dir / f"{cell_id}.md"

    metadata["fitness"] = {
        "triggers": 0,
        "true_positives": 0,
        "false_positives": 0,
        "score": None,
    }
    metadata["expiry_sessions"] = 5
    metadata["imported_date"] = datetime.now(timezone.utc).isoformat() + "Z"

    frontmatter = dump_frontmatter(metadata)
    full_content = f"---\n{frontmatter}---\n\n{body_str}" if body_str else f"---\n{frontmatter}---\n"
    dest_file.write_text(full_content, encoding="utf-8")

    metrics_dir = target_dir / ".soma" / "metrics"
    metrics_dir.mkdir(parents=True, exist_ok=True)
    transfers_log = metrics_dir / "transfers.jsonl"
    log_entry = {
        "timestamp": datetime.now(timezone.utc).isoformat() + "Z",
        "cell": dest_file.name,
        "action": "hgt_import",
        "tags": packet.get("tags", []),
    }
    try:
        with open(transfers_log, "a", encoding="utf-8") as f:
            f.write(json.dumps(log_entry) + "\n")
    except Exception:
        pass

    print(f"Imported: {cell_id} -> {dest_file} (fitness reset, 5-session probation)")
    return 0


def run_transfer(args: argparse.Namespace) -> int:
    """Entry point called from soma CLI dispatcher."""
    action_or_cell_id = getattr(args, "action_or_cell_id", None) or getattr(args, "cell_id", "")
    extra_cell_id = getattr(args, "extra_cell_id", "")
    target_dir = getattr(args, "target_dir", "")
    output_path = getattr(args, "output", "")
    tags = getattr(args, "tags", "")
    ws = getattr(args, "ws", None) or getattr(args, "workspace", None) or getattr(args, "_project_root", None)

    # Subcommand: export
    if action_or_cell_id == "export":
        cell_id = extra_cell_id
        if not cell_id:
            print("Error: Missing cell_id for export", file=sys.stderr)
            print("Usage: soma transfer export <cell_id> --tags 'python,pytest' --output rule.soma.json", file=sys.stderr)
            return 1
        return export_cell(cell_id=cell_id, tags=tags, output_path=output_path, source_workspace=ws)

    # Subcommand: import
    if action_or_cell_id == "import":
        packet_path = extra_cell_id
        if not packet_path:
            print("Error: Missing packet_path for import", file=sys.stderr)
            print("Usage: soma transfer import <packet.soma.json> [--to /path/to/target]", file=sys.stderr)
            return 1
        return import_cell(packet_path=packet_path, target_workspace=target_dir or ws)

    # Direct flag export: soma transfer <cell_id> --output ...
    if output_path or getattr(args, "export", False):
        return export_cell(cell_id=action_or_cell_id, tags=tags, output_path=output_path, source_workspace=ws)

    # Direct transfer to another repo: soma transfer <cell_id> --to /path/to/target
    if not action_or_cell_id or not target_dir:
        print("Error: Missing cell_id or --to directory", file=sys.stderr)
        print("Usage: soma transfer <cell_id> --to /path/to/target/project", file=sys.stderr)
        print("   or: soma transfer export <cell_id> --tags 'tag1,tag2' --output rule.soma.json", file=sys.stderr)
        print("   or: soma transfer import <rule.soma.json>", file=sys.stderr)
        return 1

    return transfer_cell(cell_id=action_or_cell_id, target_dir_str=target_dir, source_workspace=ws)


class TransferCommand(SomaCommand):
    """Command to transfer a cell to another project or export/import for HGT."""

    name = "transfer"
    category = CommandCategory.PLUMBING
    help = "Transfer a cell to another project or export/import for HGT"

    def configure_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("action_or_cell_id", nargs="?", default="", help="Subcommand ('export'/'import') or ID of cell to transfer")
        parser.add_argument("extra_cell_id", nargs="?", default="", help="ID of cell or path to packet file")
        parser.add_argument("--to", dest="target_dir", default="", help="Path to target project")
        parser.add_argument("--tags", type=str, default="", help="Comma-separated compatibility tags (e.g. 'python,pytest')")
        parser.add_argument("--output", "-o", type=str, default="", help="Output path for exported JSON rule (e.g. 'rule.soma.json')")

    def execute(self, args: argparse.Namespace) -> int:
        return run_transfer(args)

"""CLI porcelain commands for soma skill and soma handoff."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional

from aegis_core.skills.graph import SkillGraph
from aegis_core.skills.handoff import soma_handoff
from aegis_core.skills.slots import SlotRegistry
from aegis_cli.base import CommandCategory, AegisCommand

__all__ = ["run_skill", "run_handoff", "SkillCommand", "HandoffCommand"]


def run_skill(args: argparse.Namespace) -> int:
    """Manage and inspect horizontal skills and slots."""
    action = getattr(args, "skill_action", "list") or "list"
    ws = getattr(args, "ws", None)
    ws_root = Path(ws.root) if ws else Path.cwd()

    if action == "slots":
        reg = SlotRegistry.load(ws_root)
        slots = reg.to_dict()
        if getattr(args, "json", False):
            print(json.dumps(slots, indent=2))
        else:
            print(f"Aegis Skill Slots ({len(slots)} configured):")
            for k, v in sorted(slots.items()):
                print(f"  {k}: {v}")
        return 0

    # Discover skills
    graph = SkillGraph.discover(SkillGraph.default_search_paths(ws_root))

    if action == "list":
        if getattr(args, "json", False):
            print(json.dumps(graph.to_dict(), indent=2))
        else:
            print(f"Discovered Skills ({len(graph)} available):")
            for skill_id in sorted(graph):
                node = graph[skill_id]
                consumes_str = f" consumes=[{', '.join(node.consumes)}]" if node.consumes else ""
                produces_str = f" produces=[{', '.join(node.produces)}]" if node.produces else ""
                print(f"  • {node.id} ({node.tier}){consumes_str}{produces_str}")
        return 0

    if action == "inspect":
        target = getattr(args, "target_skill", None)
        if not target:
            print("Error: skill ID required for inspect", file=sys.stderr)
            return 1
        node = graph.get(target)
        if not node:
            print(f"Error: skill '{target}' not found", file=sys.stderr)
            return 1
        if getattr(args, "json", False):
            d = node.to_dict()
            d["instructions"] = node.load_instructions(workspace_root=ws_root)
            print(json.dumps(d, indent=2))
        else:
            print(f"Skill: {node.id} (tier: {node.tier})")
            if node.description:
                print(f"Description: {node.description}")
            if node.consumes:
                print(f"Consumes: {', '.join(node.consumes)}")
            if node.produces:
                print(f"Produces: {', '.join(node.produces)}")
            if node.handoff_targets:
                print(f"Handoff Targets: {', '.join(node.handoff_targets)}")
            inst = node.load_instructions(workspace_root=ws_root)
            if inst:
                print("\nInstructions:")
                print(inst)
        return 0

    print(f"Unknown action: {action}", file=sys.stderr)
    return 1


def run_handoff(args: argparse.Namespace) -> int:
    """Execute typed handoff between swarm skills and emit compact ticket."""
    ws = getattr(args, "ws", None)
    if not ws:
        print("Error: Workspace resolution required for handoff", file=sys.stderr)
        return 1

    payload_arg = getattr(args, "payload", "{}") or "{}"
    # Check if payload_arg is a path to a file
    payload_path = Path(payload_arg)
    if payload_path.exists() and payload_path.is_file():
        try:
            payload_data = json.loads(payload_path.read_text(encoding="utf-8"))
        except Exception:
            payload_data = {"raw": payload_path.read_text(encoding="utf-8")}
    else:
        try:
            payload_data = json.loads(payload_arg)
        except Exception:
            payload_data = {"summary": payload_arg}

    try:
        ticket = soma_handoff(
            workspace=ws,
            from_skill=args.from_skill,
            to_skill=args.to_skill,
            artifact_type=args.artifact,
            payload=payload_data,
            cycle_id=getattr(args, "cycle_id", None),
        )
        if getattr(args, "json", False):
            print(json.dumps(ticket.to_dict(), indent=2))
        else:
            print(ticket.format_prompt_block())
        return 0
    except Exception as exc:
        print(f"Handoff Error: {exc}", file=sys.stderr)
        return 1


class SkillCommand(AegisCommand):
    """Command to manage and inspect horizontal skills and slots."""

    name = "skill"
    category = CommandCategory.PLUMBING
    help = "Manage and inspect horizontal skills and slots"

    def configure_parser(
        self,
        parser: argparse.ArgumentParser,
        parents: Optional[List[argparse.ArgumentParser]] = None,
    ) -> None:
        sub = parser.add_subparsers(dest="skill_action", help="Skill command")
        sub.add_parser("list", parents=parents or [], help="List discovered skills")
        p_inspect = sub.add_parser("inspect", parents=parents or [], help="Inspect skill details")
        p_inspect.add_argument("target_skill", type=str, help="Target skill ID")
        sub.add_parser("slots", parents=parents or [], help="View slot definitions")

    def execute(self, args: argparse.Namespace) -> int:
        return run_skill(args)


class HandoffCommand(AegisCommand):
    """Command to execute file-buffered swarm handoff between skills."""

    name = "handoff"
    category = CommandCategory.PLUMBING
    help = "Execute file-buffered swarm handoff between skills"

    def configure_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--from", "-f", dest="from_skill", required=True, type=str, help="Origin skill ID")
        parser.add_argument("--to", "-t", dest="to_skill", required=True, type=str, help="Target skill ID")
        parser.add_argument("--artifact", "-a", required=True, type=str, help="Artifact type (e.g. ChargeSheet, DiffProposal)")
        parser.add_argument("--payload", "-p", type=str, default="{}", help="Artifact payload JSON or file path")
        parser.add_argument("--cycle-id", type=str, default=None, help="Optional arbitration cycle ID")

    def execute(self, args: argparse.Namespace) -> int:
        return run_handoff(args)

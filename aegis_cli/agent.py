"""aegis agent — Headless machine-to-machine subcommands for agents and MCP.

Subcommands:
  aegis agent scan        Run fast JIT scan on files and print JSON
  aegis agent grade       Calculate workspace grade and print JSON
  aegis agent receipt     Issue cryptographic gate receipt
  aegis agent record      Record outcome signal into telemetry ledger
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, List, Optional

from aegis_cli.base import CommandCategory, AegisCommand
from aegis_core.workspace import Workspace

__all__ = ["run_agent", "AgentCommand"]


def run_agent(args: argparse.Namespace) -> int:
    """Entrypoint for aegis agent subcommands."""
    action = getattr(args, "agent_action", None)
    if not action:
        print("Usage: aegis agent <scan|grade|receipt|record>", file=sys.stderr)
        return 1

    ws_root = getattr(args, "workspace", None) or getattr(args, "_project_root", None)
    ws = Workspace.resolve(ws_root)

    if action == "scan":
        return _run_agent_scan(args, ws)
    elif action == "grade":
        return _run_agent_grade(args, ws)
    elif action == "receipt":
        return _run_agent_receipt(args, ws)
    elif action == "record":
        return _run_agent_record(args, ws)

    print(f"Unknown agent subcommand: {action}", file=sys.stderr)
    return 1


def _run_agent_scan(args: argparse.Namespace, ws: Workspace) -> int:
    from aegis_mcp.jit_engine import express as jit_express

    files = getattr(args, "files", None) or getattr(args, "target_files", None)
    result = jit_express(ws, changed_files=files)
    print(json.dumps(result, indent=2))
    return 0 if result.get("status") != "FAIL" else 1


def _run_agent_grade(args: argparse.Namespace, ws: Workspace) -> int:
    import aegis_core.metrics as _metrics
    import aegis_core.telemetry as _telemetry

    grade_fn = _telemetry.calculate_governance_grade
    if (
        grade_fn is _metrics.calculate_governance_grade
        and _telemetry.calculate_immune_grade is not _metrics.calculate_governance_grade
    ):
        grade_fn = _telemetry.calculate_immune_grade
    result = grade_fn(ws)
    print(json.dumps(result, indent=2))
    return 0


def _run_agent_receipt(args: argparse.Namespace, ws: Workspace) -> int:
    from aegis_core.receipts import (
        compute_file_digest,
        issue_receipt,
    )
    try:
        from aegis_core.receipts import compute_rule_digest
    except ImportError:
        from aegis_core.receipts import compute_cell_digest as compute_rule_digest
    from aegis_core.taxonomy import INTERACTIVE_SESSION_TTL_SECONDS

    operation = getattr(args, "operation", "verify")
    session_id = getattr(args, "session_id", "local-session")
    file_digest = compute_file_digest(ws.root, [])
    rule_digest = compute_rule_digest(ws.root)

    try:
        receipt_id = issue_receipt(
            session_id=session_id,
            workspace=str(ws.root),
            operation=operation,
            args={},
            file_digest=file_digest,
            rule_digest=rule_digest,
            ttl_seconds=INTERACTIVE_SESSION_TTL_SECONDS,
        )
    except TypeError:
        receipt_id = issue_receipt(
            session_id=session_id,
            workspace=str(ws.root),
            operation=operation,
            args={},
            file_digest=file_digest,
            cell_digest=rule_digest,
            ttl_seconds=INTERACTIVE_SESSION_TTL_SECONDS,
        )
    print(json.dumps({"status": "ISSUED", "receipt": receipt_id, "operation": operation}, indent=2))
    return 0


def _run_agent_record(args: argparse.Namespace, ws: Workspace) -> int:
    from aegis_core.telemetry import append_signals, read_generation

    outcome = getattr(args, "outcome", "tp")
    key = getattr(args, "key", "cli-agent-record")
    rules = getattr(args, "rules", []) or []
    if isinstance(rules, str):
        rules = [r.strip() for r in rules.split(",") if r.strip()]

    events = [
        {
            "cell_name": r,
            "signal_type": outcome,
            "source": "cli_agent",
            "metadata": {"notes": getattr(args, "notes", "")},
            "principal": "agent",
            "idempotency_scope": "report_outcome",
            "idempotency_key": key,
        }
        for r in rules
    ]

    generation = read_generation(ws)
    records = append_signals(ws, events, expected_generation=generation)
    print(json.dumps({"status": "recorded", "records": records}, indent=2))
    return 0


class AgentCommand(AegisCommand):
    """Headless machine-to-machine subcommands for agents and MCP."""

    name = "agent"
    aliases = ()
    category = CommandCategory.PLUMBING
    help = "Headless machine-to-machine subcommands (scan, grade, receipt, record)"

    def configure_parser(self, parser: argparse.ArgumentParser) -> None:
        sub = parser.add_subparsers(dest="agent_action", metavar="ACTION")

        # scan
        p_scan = sub.add_parser("scan", help="Run fast JIT scan on files")
        p_scan.add_argument("target_files", nargs="*", help="Files to scan")
        p_scan.add_argument("--files", nargs="*", help="Files to scan")

        # grade
        p_grade = sub.add_parser("grade", help="Calculate workspace health grade")

        # receipt
        p_rcpt = sub.add_parser("receipt", help="Issue cryptographic gate receipt")
        p_rcpt.add_argument("--operation", default="verify", help="Operation name")
        p_rcpt.add_argument("--session-id", default="local-session", help="Session ID")

        # record
        p_rec = sub.add_parser("record", help="Record outcome telemetry signal")
        p_rec.add_argument("--outcome", default="tp", choices=["tp", "fp", "trigger", "pass", "fail"], help="Signal outcome")
        p_rec.add_argument("--key", default="cli-record", help="Idempotency key")
        p_rec.add_argument("--rules", nargs="*", help="Rule names/IDs associated with signal")
        p_rec.add_argument("--notes", default="", help="Optional notes")

    def execute(self, args: argparse.Namespace) -> int:
        return run_agent(args)


if __name__ == "__main__":  # pragma: no cover
    from aegis_cli.cli import main
    sys.exit(main(["agent"] + sys.argv[1:]))

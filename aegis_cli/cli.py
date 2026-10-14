#!/usr/bin/env python3
"""Soma CLI — governance commands for AI coding agents.

User-facing interface uses plain language (rules, automations, etc).
Internal code retains biological naming (genome, enzymes, cells).
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import List, Optional

from aegis_cli.base import CommandCategory, SomaCommand
from aegis_cli.registry import get_default_registry

__all__ = ["main", "SomaParser", "COMMANDS"]


def _version() -> str:
    version_file = Path(__file__).resolve().parent.parent / "VERSION"
    if version_file.is_file():
        try:
            val = version_file.read_text(encoding="utf-8").strip()
            if val:
                return val
        except OSError:
            pass
    try:
        from importlib.metadata import PackageNotFoundError, version
        try:
            return version("aegis-governance")
        except PackageNotFoundError:
            try:
                return version("soma-governance")
            except PackageNotFoundError:
                pass
    except ImportError:
        pass
    return "unknown"


class SomaParser(argparse.ArgumentParser):
    """ArgumentParser ensuring global flags like plumbing default properly."""

    def format_help(self) -> str:
        if self.prog in ("soma", "aegis"):
            return get_default_registry().format_categorized_help(prog=self.prog) + "\n"
        return super().format_help()

    def parse_args(self, args=None, namespace=None):
        ns = super().parse_args(args=args, namespace=namespace)
        if not hasattr(ns, "plumbing"):
            ns.plumbing = False
        if not hasattr(ns, "plain"):
            ns.plain = False
        if not hasattr(ns, "no_emoji"):
            ns.no_emoji = False
        if getattr(ns, "no_emoji", False):
            ns.plain = True
        if not hasattr(ns, "verbose"):
            ns.verbose = False
        if not hasattr(ns, "quiet"):
            ns.quiet = False
        if not hasattr(ns, "format"):
            ns.format = None
        if not hasattr(ns, "workspace"):
            ns.workspace = None
        return ns


def _build_parser(prog: str = "soma") -> argparse.ArgumentParser:
    common_parser = argparse.ArgumentParser(add_help=False)
    common_parser.add_argument("--plumbing", "--internal", action="store_true",
                               default=argparse.SUPPRESS,
                               help="Display raw internal biological terms")
    common_parser.add_argument("--plain", action="store_true",
                               default=argparse.SUPPRESS,
                               help="Strip ANSI styling and Unicode emojis for plain logs")
    common_parser.add_argument("--no-emoji", action="store_true",
                               default=argparse.SUPPRESS,
                               help="Strip Unicode emojis from output (alias for --plain)")
    common_parser.add_argument("--format", choices=["text", "json", "mermaid"],
                               default=argparse.SUPPRESS,
                               help="Output format")
    common_parser.add_argument("--json", action="store_true",
                               default=False,
                               help="Emit machine-readable JSON output (shortcut for --format json)")
    common_parser.add_argument("-v", "--verbose", action="store_true",
                               default=argparse.SUPPRESS,
                               help="Verbose diagnostic output")
    common_parser.add_argument("-q", "--quiet", action="store_true",
                               default=argparse.SUPPRESS,
                               help="Suppress informational messages")
    common_parser.add_argument("--workspace", type=str,
                               default=argparse.SUPPRESS,
                               help="Target workspace root")

    prog_title = "Aegis" if prog == "aegis" else "Soma"
    parser = SomaParser(
        prog=prog,
        description=f"{prog_title} Governance — make AI coding agents trustworthy",
        parents=[common_parser],
    )
    parser.add_argument("--version", action="version",
                        version=f"{prog} {_version()}")

    sub = parser.add_subparsers(dest="command", parser_class=SomaParser)
    get_default_registry().populate_subparsers(sub, common_parser=common_parser)
    return parser


# ── Backward-compatible command handlers ────────────────────────────────────

def cmd_init(args: argparse.Namespace) -> int:
    from aegis_cli.init import run_init
    return run_init(args)

def cmd_status(args: argparse.Namespace) -> int:
    from aegis_cli.status import run_status
    return run_status(args)

def cmd_report(args: argparse.Namespace) -> int:
    from aegis_cli.report import run_report
    return run_report(args)

def cmd_doctor(args: argparse.Namespace) -> int:
    from aegis_cli.doctor import run_doctor
    return run_doctor(args)

cmd_audit = cmd_doctor

def cmd_detect(args: argparse.Namespace) -> int:
    from aegis_cli.detect import run_detect
    return run_detect(args)

def cmd_verify(args: argparse.Namespace) -> int:
    from aegis_cli.verify import run_verify
    return run_verify(args)

cmd_check = cmd_verify

def cmd_checkpoint(args: argparse.Namespace) -> int:
    from aegis_cli.checkpoint import run_checkpoint
    return run_checkpoint(args)

def cmd_sync(args: argparse.Namespace) -> int:
    from aegis_cli.sync import run_sync
    return run_sync(args)

def cmd_oracle(args: argparse.Namespace) -> int:
    from aegis_cli.oracle import run_oracle
    return run_oracle(args)

def cmd_promote(args: argparse.Namespace) -> int:
    from aegis_cli.promote import run_promote
    return run_promote(args)

def cmd_demote(args: argparse.Namespace) -> int:
    from aegis_cli.demote import run_demote
    return run_demote(args)

def cmd_harvest(args: argparse.Namespace) -> int:
    from aegis_cli.harvest import run_harvest
    return run_harvest(args)

def cmd_genesis(args: argparse.Namespace) -> int:
    from aegis_cli.genesis import run_genesis
    return run_genesis(args)

cmd_analyze = cmd_genesis

def cmd_completion(args: argparse.Namespace) -> int:
    from aegis_cli.completion import run_completion
    return run_completion(args)

def cmd_hook(args: argparse.Namespace) -> int:
    from aegis_cli.hooks import run_hook
    return run_hook(args)

def cmd_transfer(args: argparse.Namespace) -> int:
    from aegis_cli.transfer import run_transfer
    return run_transfer(args)

def cmd_quarantine(args: argparse.Namespace) -> int:
    from aegis_cli.quarantine import run_quarantine
    return run_quarantine(args)

def cmd_prune(args: argparse.Namespace) -> int:
    from aegis_cli.prune import run_prune
    return run_prune(args)

def cmd_install(args: argparse.Namespace) -> int:
    from aegis_cli.install import run_install
    return run_install(args)

def cmd_uninstall(args: argparse.Namespace) -> int:
    from aegis_cli.install import run_uninstall
    return run_uninstall(args)

def cmd_clean_global_rules(args: argparse.Namespace) -> int:
    from aegis_cli.clean_rules import run_clean_rules
    return run_clean_rules(args)

def cmd_capture_insight(args: argparse.Namespace) -> int:
    from aegis_cli.capture_insight import run_capture_insight
    return run_capture_insight(args)

def cmd_skill(args: argparse.Namespace) -> int:
    from aegis_cli.skills import run_skill
    return run_skill(args)

def cmd_handoff(args: argparse.Namespace) -> int:
    from aegis_cli.skills import run_handoff
    return run_handoff(args)


COMMANDS = {
    "init": cmd_init,
    "status": cmd_status,
    "rules": cmd_status,
    "report": cmd_report,
    "doctor": cmd_doctor,
    "audit": cmd_audit,
    "detect": cmd_detect,
    "languages": cmd_detect,
    "drivers": cmd_detect,
    "verify": cmd_verify,
    "check": cmd_check,
    "checkpoint": cmd_checkpoint,
    "sync": cmd_sync,
    "oracle": cmd_oracle,
    "promote": cmd_promote,
    "demote": cmd_demote,
    "harvest": cmd_harvest,
    "genesis": cmd_genesis,
    "analyze": cmd_genesis,
    "completion": cmd_completion,
    "hook": cmd_hook,
    "transfer": cmd_transfer,
    "quarantine": cmd_quarantine,
    "prune": cmd_prune,
    "install": cmd_install,
    "uninstall": cmd_uninstall,
    "clean-global-rules": cmd_clean_global_rules,
    "capture-insight": cmd_capture_insight,
    "skill": cmd_skill,
    "handoff": cmd_handoff,
}


def main(argv: list[str] | None = None, prog: str | None = None) -> int:
    # Output uses emoji. On a cp1252 stdout (Windows, redirected) printing
    # one raised UnicodeEncodeError and the command exited 1 (BUG-012).
    # stderr already defaults to errors="backslashreplace".
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    if prog is None:
        if sys.argv:
            base = os.path.basename(sys.argv[0])
            if "aegis" in base or "aegis_cli" in sys.argv[0]:
                prog = "aegis"
            else:
                prog = "soma"
        else:
            prog = "soma"
    parser = _build_parser(prog=prog)
    args = parser.parse_args(argv)
    args.prog = prog
    if not hasattr(args, "plumbing"):
        args.plumbing = False

    fmt = getattr(args, "format", None)
    is_json = getattr(args, "json", False) or fmt == "json"
    args.json = is_json
    if is_json and not fmt:
        args.format = "json"

    if args.command is None:
        parser.print_help()
        return 0

    handler = COMMANDS.get(args.command)
    if handler is None:
        cmd_obj = get_default_registry().get(args.command)
        if cmd_obj is not None:
            handler = cmd_obj.execute
        else:
            parser.print_help()
            return 1

    try:
        from aegis_core.workspace import Workspace

        if args.command == "completion":
            args.ws = None
        elif args.command == "init":
            raw_ws = getattr(args, "workspace", None) or Path.cwd()
            args.ws = Workspace.for_init(raw_ws)
        else:
            raw_ws = getattr(args, "workspace", None)
            args.ws = Workspace.resolve(raw_ws)

        if args.ws is not None:
            args._project_root = args.ws.root
            args.workspace = str(args.ws.root)

        func = globals().get(getattr(handler, "__name__", ""), handler)
        return func(args)
    except KeyboardInterrupt:
        return 130
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

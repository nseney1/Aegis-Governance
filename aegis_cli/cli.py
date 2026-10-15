#!/usr/bin/env python3
"""aegis — governance commands for AI coding agents.

Dispatch goes through the command registry only. Commands and aliases cut in
v4 (ADR 0005 D5, H1 hard cut) are not parsed at all: each removed name exits 2
with one line on stderr naming its replacement.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Dict, List, Optional

from aegis_cli.registry import get_default_registry

__all__ = ["main", "AegisParser", "REMOVED_COMMANDS"]

PROG = "aegis"

_HOST_HOOK = "no replacement; remove it from your agent host's hook config"

# "name" or "name action" -> what to use instead. The longest match wins, so
# `aegis agent scan` gets its own pointer, and a removed action of a live
# command (`aegis hook session-close`, still called by v3 host hook configs)
# gets one too.
REMOVED_COMMANDS: Dict[str, str] = {
    "install": "use aegis init --host",
    "system": "use aegis doctor",
    "sys": "use aegis doctor",
    "system doctor": "use aegis doctor",
    "system drivers": "use aegis doctor",
    "system hook": "use aegis hook",
    "detect": "use aegis doctor",
    "languages": "use aegis doctor",
    "drivers": "use aegis doctor",
    "audit": "use aegis doctor",
    "rules": "use aegis status",
    "agent": "use aegis scan to see which rules apply; record outcomes with the MCP tool aegis_report_outcome",
    "agent scan": "use aegis scan",
    "agent record": "use aegis_report_outcome (MCP)",
    "report": (
        "aegis status shows rule trigger counts; "
        "outcomes are recorded with the MCP tool aegis_report_outcome"
    ),
    "completion": "no replacement",
    "skill": "no replacement",
    "handoff": "no replacement",
    "verify": "use aegis check",
    "checkpoint": "use aegis check",
    "rule clean": "no replacement; remove leaked global rule copies by hand",
    "hook pre-commit": "use aegis check --hook",
    "hook pre-invocation": _HOST_HOOK,
    "hook governance-monitor": _HOST_HOOK,
    "hook immune-init": _HOST_HOOK,
    "hook session-close": _HOST_HOOK,
    "hook stop": _HOST_HOOK,
    "hook post-session": _HOST_HOOK,
}

# Global options that take a value, so the removed-name scan can skip it.
_VALUE_OPTIONS = ("--workspace",)


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
            return version("aegis-guardrails")
        except PackageNotFoundError:
            pass
    except ImportError:
        pass
    return "unknown"


def _positionals(argv: List[str]) -> List[str]:
    out: List[str] = []
    skip = False
    for token in argv:
        if skip:
            skip = False
        elif token == "--":
            break
        elif token in _VALUE_OPTIONS:
            skip = True
        elif not token.startswith("-"):
            out.append(token)
    return out


def removed_command_pointer(argv: List[str]) -> Optional[str]:
    """The one-line pointer for a removed command in argv, or None.

    A name the registry still resolves is not removed: a command whose alias
    is cut in another module keeps working until that module drops it.
    """
    words = _positionals(argv)
    if not words:
        return None
    pair = " ".join(words[:2])
    if len(words) > 1 and pair in REMOVED_COMMANDS:
        name = pair
    elif words[0] in REMOVED_COMMANDS and get_default_registry().get(words[0]) is None:
        name = words[0]
    else:
        return None
    return f"{PROG} {name} was removed in v4: {REMOVED_COMMANDS[name]}"


class AegisParser(argparse.ArgumentParser):
    """ArgumentParser with the categorized top-level help and an attached OutputContext."""

    def format_help(self) -> str:
        if self.prog == PROG:
            return get_default_registry().format_categorized_help(prog=self.prog) + "\n"
        return super().format_help()

    def parse_args(self, args=None, namespace=None):
        ns = super().parse_args(args=args, namespace=namespace)
        if not hasattr(ns, "json"):
            ns.json = False
        # Only `check` keeps --format; its json value must reach code (and the
        # OutputContext below) that reads args.json alone.
        if getattr(ns, "format", None) == "json":
            ns.json = True
        if not hasattr(ns, "plain"):
            ns.plain = False
        if not hasattr(ns, "workspace"):
            ns.workspace = None
        from aegis_cli.ui.theme import OutputContext
        ns.ui = OutputContext.from_env_and_args(ns)
        return ns


def _build_parser(prog: str = PROG) -> argparse.ArgumentParser:
    common_parser = argparse.ArgumentParser(add_help=False)
    # SUPPRESS, not False: a subparser writes its defaults over the namespace
    # the top-level parser filled, so a False default here drops a `--json`
    # given before the command. parse_args sets the False fallback once.
    common_parser.add_argument("--json", action="store_true", default=argparse.SUPPRESS,
                               help="Emit machine-readable JSON output")
    common_parser.add_argument("--plain", action="store_true", default=argparse.SUPPRESS,
                               help="Strip ANSI styling and emoji")
    common_parser.add_argument("--workspace", type=str, default=argparse.SUPPRESS,
                               help="Target workspace root")

    parser = AegisParser(
        prog=prog,
        description="Aegis Governance — make AI coding agents trustworthy",
        parents=[common_parser],
    )
    parser.add_argument("--version", action="version", version=f"{prog} {_version()}")

    sub = parser.add_subparsers(dest="command", parser_class=AegisParser)
    get_default_registry().populate_subparsers(sub, common_parser=common_parser)
    return parser


def _attach_workspace(args: argparse.Namespace) -> None:
    """Resolve the workspace the command acts on (``args.ws``, ``args._project_root``)."""
    from aegis_core.workspace.base import Workspace

    raw_ws = getattr(args, "workspace", None)
    if args.command == "scan":
        # scan resolves its own workspace so that a workspace error exits 2.
        args.ws = None
        return
    if args.command == "init":
        args._allow_home_fallback = True
        args.ws = Workspace.for_init(raw_ws or Path.cwd())
    elif args.command == "migrate":
        args.ws = None
        start_dir = Path(raw_ws).resolve() if raw_ws else Path.cwd().resolve()
        target_root = start_dir
        curr = start_dir
        while curr != curr.parent:
            if (curr / ".aegis").is_dir() or (curr / ".soma").is_dir():
                target_root = curr
                break
            curr = curr.parent
        args._project_root = target_root
        args.workspace = str(target_root)
        return
    elif args.command == "uninstall":
        try:
            args.ws = Workspace.resolve(raw_ws)
        except Exception:
            # Uninstall must work in a directory that no longer resolves
            # (for example one holding only a legacy .soma/).
            args.ws = None
            p = Path(raw_ws).resolve() if raw_ws else Path.cwd().resolve()
            args._project_root = p
            args.workspace = str(p)
            return
    else:
        args.ws = Workspace.resolve(raw_ws)
    args._project_root = args.ws.root
    args.workspace = str(args.ws.root)


def main(argv: Optional[List[str]] = None, prog: str = PROG) -> int:
    # Output uses emoji. On a cp1252 stdout (Windows, redirected) printing
    # one raised UnicodeEncodeError and the command exited 1 (BUG-012).
    # stderr already defaults to errors="backslashreplace".
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    argv = list(sys.argv[1:] if argv is None else argv)

    pointer = removed_command_pointer(argv)
    if pointer is not None:
        print(pointer, file=sys.stderr)
        return 2

    parser = _build_parser(prog=prog)
    args = parser.parse_args(argv)
    args.prog = prog
    if args.command is None:
        parser.print_help()
        return 0

    command = get_default_registry().get(args.command)
    try:
        _attach_workspace(args)
        return command.execute(args)
    except KeyboardInterrupt:
        return 130
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

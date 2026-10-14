"""CLI entrypoint for execution via `python -m aegis_cli.hooks <phase>`."""
from __future__ import annotations

import argparse
import sys

from aegis_cli.hooks.runtime import run_hook


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint for standalone hook runner."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")

    parser = argparse.ArgumentParser(
        prog="soma hook",
        description="Manage and run cross-platform Soma lifecycle hooks",
    )
    parser.add_argument(
        "phase",
        nargs="?",
        default="status",
        choices=[
            "install",
            "status",
            "uninstall",
            "pre-commit",
            "safety-gate",
            "pre-invocation",
            "session-close",
            "post-session",
            "governance-monitor",
            "immune-init",
            "stop",
        ],
        help="Hook command or lifecycle phase to execute (default: status)",
    )
    parser.add_argument(
        "--cmd",
        type=str,
        default=None,
        help="Command line string for safety-gate check",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="In pre-commit, exit 1 on issues",
    )
    parser.add_argument(
        "--workspace",
        default=None,
        help="Target workspace path",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force install or uninstall",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview without modifying disk",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON output",
    )
    parser.add_argument(
        "--transcript",
        default=None,
        help="Path to transcript.jsonl for post-session hook",
    )
    args = parser.parse_args(argv)
    return run_hook(args)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    sys.exit(main())

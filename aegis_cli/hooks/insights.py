"""Lazy ``UserPromptSubmit`` hook entrypoint for human insight capture (v4.3 T8).

Invoked by Claude Code (``~/.claude/settings.json``) or Codex CLI (``~/.codex/hooks.json``)
when opt-in enabled via ``aegis rule insight enable --host <claude-code|codex-cli> [--excerpts]``.

Contract:
- Target latency: ``<= 40 ms`` on routine prompts.
- Always exits ``0`` so host prompt submission is never blocked.
- Never writes to ``stdout`` (host hook runners parse ``stdout``); diagnostics go to ``stderr``.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import Any, Dict, Optional, Sequence

from aegis_core.insights import (
    SUPPORTED_INSIGHT_HOSTS,
    enable_host_hook as enable_insight_hook,
    host_capture_status as insight_hook_status,
    record_hook_prompt,
)

__all__ = [
    "SUPPORTED_INSIGHT_HOSTS",
    "enable_insight_hook",
    "insight_hook_status",
    "main",
    "run_insight_hook",
]


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="aegis_cli.hooks.insights",
        add_help=False,
    )
    parser.add_argument("--host", default="claude-code")
    parser.add_argument("--workspace", default=None)
    parser.add_argument("--excerpts", dest="excerpts", action="store_true", default=True)
    parser.add_argument("--no-excerpts", dest="excerpts", action="store_false")
    return parser


def run_insight_hook(
    argv: Optional[Sequence[str]] = None,
    stdin: Optional[str] = None,
    *,
    home: Optional[Path] = None,
) -> int:
    """Execute the ``UserPromptSubmit`` insight hook; always returns ``0``."""
    try:
        parser = _build_parser()
        args, _unknown = parser.parse_known_args(list(argv) if argv is not None else sys.argv[1:])
        raw = stdin if stdin is not None else ("" if sys.stdin.isatty() else sys.stdin.read())
        record_hook_prompt(
            args.host,
            raw,
            workspace=args.workspace,
            excerpts=bool(args.excerpts),
            home=home,
        )
    except Exception as exc:
        try:
            sys.stderr.write(f"aegis insight hook error: {exc}\n")
        except Exception:
            pass
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    return run_insight_hook(argv=argv)


if __name__ == "__main__":
    raise SystemExit(main())

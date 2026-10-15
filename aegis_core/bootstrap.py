"""The one instruction every host receives (ADR 0005 H2, AD-9).

Rule text is never inlined into instruction files. Hosts get this short
bootstrap in AGENTS.md and the same guidance as the MCP ``instructions``
string, which editing files cannot remove; the rules themselves arrive just in
time through ``aegis_scan``.
"""
from __future__ import annotations

BOOTSTRAP_ID = "bootstrap"

_BOOTSTRAP = """\
## Aegis guardrails

This repository uses [Aegis](https://github.com/nseney1/Aegis-Guardrails) rules for AI coding agents.

- Before editing files, call the `aegis_scan` MCP tool with the files you plan to change, and follow the rules it returns.
- After you verify a change (tests or checks), call `aegis_report_outcome` with the rules you used.
- No MCP tools? Run `aegis scan FILE...` in a shell instead.
- Rules live in `.aegis/rules/`. `aegis check` runs before commit and in CI.
"""

_INSTRUCTIONS = (
    "Aegis serves this repository's coding rules just in time. Before editing files, call "
    "aegis_scan with the paths you plan to change and follow the rules it returns. After "
    "verifying a change with tests or checks, call aegis_report_outcome with the rules you "
    "used and the outcome. Rules live in .aegis/rules/; aegis check enforces the deterministic "
    "ones before commit and in CI."
)


def bootstrap_text() -> str:
    """Markdown body of the managed AGENTS.md block (about 500 bytes, no rule bodies)."""
    return _BOOTSTRAP


def instructions_text() -> str:
    """The MCP ``initialize`` instructions; the first 512 characters stand alone."""
    return _INSTRUCTIONS

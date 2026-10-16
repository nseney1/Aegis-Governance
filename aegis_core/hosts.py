"""The agent hosts Aegis knows about, as data (host-matrix spec v2, section 3.3).

A *host* is a product whose surfaces share one configuration plane: the Codex
CLI, IDE extension and desktop app all read ``~/.codex``, so they are one host.
Vendor is metadata only. Installers, the doctor and the MCP server read this
table; a host gets real code only when it needs logic the table cannot express.

Rows marked ``verified=False`` describe documented behaviour that has not been
checked on a real install; ``aegis init`` warns before using them.
"""
from __future__ import annotations

__all__ = ["GENERIC", "HOSTS", "INSTRUCTION_MODES", "HostSpec", "Registration", "all_hosts", "get", "identify"]

from dataclasses import dataclass, field
from typing import Optional, Tuple

#: Instruction-file behaviour of a host.
#: ``agents_md``                  reads AGENTS.md natively.
#: ``agents_md_unless_claude_md`` reads AGENTS.md only when no CLAUDE.md exists
#:                                (Claude Code >= 2.1.277); a CLAUDE.md needs an
#:                                ``@AGENTS.md`` import block.
#: ``gemini_md``                  reads GEMINI.md unless settings list AGENTS.md.
#: ``none``                       has no instruction file (identity-only host).
INSTRUCTION_MODES = ("agents_md", "agents_md_unless_claude_md", "gemini_md", "none")

GENERIC = "generic"


@dataclass(frozen=True)
class Registration:
    """How ``aegis init`` registers the MCP server for a host.

    ``native_cli``: run ``argv`` (``{command}`` is replaced by the absolute
    ``aegis-mcp`` command). ``json_file``: merge an ``aegis`` entry into
    ``path`` under ``key`` (``~`` is the user's home directory).
    """

    kind: str  # "native_cli" | "json_file"
    argv: Tuple[str, ...] = ()
    path: str = ""
    key: str = "mcpServers"


@dataclass(frozen=True)
class HostSpec:
    id: str
    display_name: str
    vendor: str
    client_names: Tuple[str, ...] = ()
    client_prefixes: Tuple[str, ...] = ()
    binaries: Tuple[str, ...] = ()
    user_dirs: Tuple[str, ...] = ()
    instructions: str = "none"
    budget_bytes: Optional[int] = None
    registration: Optional[Registration] = None
    slot_profile: str = GENERIC
    phase: int = 1
    verified: bool = True
    notes: Tuple[str, ...] = field(default_factory=tuple)


HOSTS: Tuple[HostSpec, ...] = (
    HostSpec(
        id="codex-cli",
        display_name="Codex CLI",
        vendor="OpenAI",
        client_names=("codex-mcp-client",),
        binaries=("codex",),
        user_dirs=("~/.codex",),
        instructions="agents_md",
        budget_bytes=32 * 1024,
        registration=Registration(
            kind="native_cli",
            argv=("codex", "mcp", "add", "aegis", "--env", "AEGIS_CLIENT=codex-cli", "--", "{command}"),
        ),
        slot_profile="codex-cli",
        notes=(
            "AGENTS.md over 32 KiB is truncated silently.",
            "Hooks fail open and need user approval.",
        ),
    ),
    HostSpec(
        id="claude-code",
        display_name="Claude Code",
        vendor="Anthropic",
        client_names=("claude-code",),
        binaries=("claude",),
        user_dirs=("~/.claude",),
        instructions="agents_md_unless_claude_md",
        budget_bytes=40 * 1024,
        registration=Registration(
            kind="native_cli",
            argv=("claude", "mcp", "add", "--scope", "user", "aegis", "-e", "AEGIS_CLIENT=claude-code", "--", "{command}"),
        ),
        slot_profile="claude-code",
        notes=("PreToolUse hooks can block (strongest host).",),
    ),
    HostSpec(
        id="claude-desktop",
        display_name="Claude Desktop",
        vendor="Anthropic",
        client_prefixes=("local-agent-mode-",),
        instructions="none",
        slot_profile=GENERIC,
        notes=("Identity only: Aegis does not register here (ADR 0005 H4).",),
    ),
    HostSpec(
        id="antigravity",
        display_name="Antigravity",
        vendor="Google",
        client_names=("antigravity-client",),
        binaries=("agy",),
        user_dirs=("~/.gemini/config", "~/.gemini/antigravity"),
        instructions="agents_md",
        budget_bytes=24000,
        registration=Registration(kind="json_file", path="~/.gemini/config/mcp_config.json", key="mcpServers"),
        slot_profile="antigravity",
        notes=("Sends no MCP roots; the workspace registry is its only binding route.",),
    ),
    HostSpec(
        id="gemini-cli",
        display_name="Gemini CLI",
        vendor="Google",
        client_names=("gemini-cli-mcp-client",),
        binaries=("gemini",),
        user_dirs=("~/.gemini",),
        instructions="gemini_md",
        registration=None,
        slot_profile=GENERIC,
        phase=2,
        verified=False,
        notes=(
            "Retired: Google no longer serves Gemini CLI to individual Code Assist accounts; "
            "Antigravity is the Gemini-family host. Identity only.",
        ),
    ),
)

_BY_ID = {h.id: h for h in HOSTS}


def get(host_id: str) -> HostSpec:
    """Return the host with this id; raise KeyError naming the known ids."""
    try:
        return _BY_ID[host_id]
    except KeyError:
        raise KeyError(f"unknown host {host_id!r}; known hosts: {', '.join(_BY_ID)}") from None


def all_hosts(phase: Optional[int] = None) -> Tuple[HostSpec, ...]:
    """All hosts, or only those available in phases up to ``phase``."""
    if phase is None:
        return HOSTS
    return tuple(h for h in HOSTS if h.phase <= phase)


def identify(client_name: Optional[str]) -> str:
    """Map an MCP ``clientInfo.name`` to a host id; unknown clients are ``generic``.

    Matching is exact except for declared prefixes (Claude Desktop appends a
    per-install key). It never defaults to a vendor guess.
    """
    if not client_name:
        return GENERIC
    for host in HOSTS:
        if client_name in host.client_names:
            return host.id
    for host in HOSTS:
        if any(client_name.startswith(p) for p in host.client_prefixes):
            return host.id
    return GENERIC

"""Layer 2 model backend: one external command, so Aegis needs no SDKs or API keys.

The command (for example ``claude -p``, ``codex exec`` or ``gemini -p``) is run as an
argv list with no shell. It reads the prompt on stdin and prints the reply on stdout.
It comes only from ``--llm-cmd`` or ``AEGIS_LLM_CMD``: a file in the repository being
checked must never choose what Aegis executes (BUG-073).

The command runs in a fresh empty directory, not in the repository: agent CLIs load
project config from their working directory (``.claude/settings.json`` hooks,
``AGENTS.md``/``GEMINI.md`` instructions, MCP servers), and the code under review must
not be able to steer its reviewer. The prompt carries everything the review needs. So a
script in the command needs an absolute path, and ``codex exec`` needs
``--skip-git-repo-check``.
"""
from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import tempfile
from typing import List, Mapping, Optional, Sequence

from aegis_core.config import ENV_LLM_CMD, env_llm_cmd

ENV_VAR = ENV_LLM_CMD
MISSING_BACKEND = f"Layer 2 needs --llm-cmd or {ENV_VAR}"
DEFAULT_TIMEOUT = 600.0

__all__ = ["CommandBackend", "DEFAULT_TIMEOUT", "ENV_VAR", "LLMCommandError", "MISSING_BACKEND", "resolve_backend"]


class LLMCommandError(RuntimeError):
    """The Layer 2 command is malformed, could not start, timed out or failed."""


class CommandBackend:
    """Runs the Layer 2 command once per prompt."""

    def __init__(self, argv: Sequence[str], timeout: float = DEFAULT_TIMEOUT):
        if not argv:
            raise LLMCommandError("LLM command is empty")
        self.argv: List[str] = list(argv)
        self.timeout = timeout

    def generate(self, prompt: str) -> str:
        # input= gives the child a fresh stdin pipe, so it can never read (and steal)
        # this process's stdin, which carries JSON-RPC when Aegis runs under MCP.
        workdir = tempfile.mkdtemp(prefix="aegis-llm-")
        try:
            proc = subprocess.run(
                self.argv, input=prompt, capture_output=True, text=True, cwd=workdir,
                encoding="utf-8", errors="replace", timeout=self.timeout, check=False,
            )
        except subprocess.TimeoutExpired:
            raise LLMCommandError(f"LLM command timed out after {self.timeout:g}s: {self.argv[0]}") from None
        except OSError as exc:
            raise LLMCommandError(f"cannot run LLM command {self.argv[0]}: {exc.strerror or exc}") from None
        finally:
            # Not TemporaryDirectory: ignore_cleanup_errors needs 3.10, and a Windows child
            # killed on timeout may briefly hold a file in it.
            shutil.rmtree(workdir, ignore_errors=True)
        if proc.returncode != 0:
            detail = (proc.stderr or "").strip().splitlines()
            raise LLMCommandError(f"LLM command exited {proc.returncode}: {detail[-1] if detail else 'no stderr'}")
        return proc.stdout


def _split_command(raw: str) -> List[str]:
    # POSIX shlex reads every backslash as an escape, so a native Windows path
    # (C:\tools\llm.exe) lost them. On Windows split without escapes; the quotes
    # that grouped a token (a path with spaces) are syntax, so they are dropped.
    if os.name != "nt":
        return shlex.split(raw)
    parts = []
    for part in shlex.split(raw, posix=False):
        if len(part) >= 2 and part[0] == part[-1] and part[0] in "\"'":
            part = part[1:-1]
        parts.append(part)
    return parts


def resolve_backend(flag: Optional[str], environ: Optional[Mapping[str, str]] = None) -> Optional[CommandBackend]:
    """The backend named by ``--llm-cmd`` (first) or ``AEGIS_LLM_CMD``; None when neither is set."""
    raw = flag if flag and flag.strip() else (env_llm_cmd(environ) or "")
    if not raw.strip():
        return None
    try:
        return CommandBackend(_split_command(raw))
    except ValueError as exc:
        raise LLMCommandError(f"cannot parse --llm-cmd / {ENV_VAR} {raw!r}: {exc}") from None

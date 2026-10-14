"""Safety gate: fast-path allowlist, metacharacter inspection, and AST command safety evaluation."""
from __future__ import annotations

import datetime
import json
import os
from pathlib import Path
import re
import shlex
from typing import Any

from aegis_cli.hooks.redaction import redact_secrets

SAFE_COMMAND_PREFIXES: tuple[str, ...] = (
    "git status",
    "git diff",
    "git log",
    "git show",
    "git branch",
    "git rev-parse",
    "git check-ref-format",
    "ls",
    "dir",
    "cat",
    "head",
    "tail",
    "wc",
    "pwd",
    "date",
    "whoami",
    "pytest",
    "python -m pytest",
    "cargo test",
    "npm test",
    "echo",
)

METACHARACTERS: frozenset[str] = frozenset({";", "&", "|", ">", "<", "`", "$", "\n", "\r", "(", ")", "\\"})
DANGEROUS_FLAGS: tuple[str, ...] = ("-f", "--force", "-D", "-d", "-M", "--output", "--ext-cmd", "--delete")


def _find_gate_log_dir(workspace: Path) -> Path:
    """Locate the canonical directory for gate event logging."""
    env_logs = os.environ.get("SOMA_LOGS_DIR")
    if env_logs:
        return Path(env_logs) / "governance"
    home = Path(os.environ.get("USERPROFILE") or os.environ.get("HOME") or Path.home())
    candidate = home / ".gemini" / "antigravity" / "scratch" / "ai-conversation-logs" / "governance"
    if candidate.parent.exists():
        return candidate
    return workspace / ".soma" / "governance"


def log_gate_event(cmd: str, decision: str, reason: str, workspace: Path) -> None:
    """Log safety gate evaluations to gate_events.jsonl."""
    log_dir = _find_gate_log_dir(workspace)
    log_file = log_dir / "gate_events.jsonl"
    snippet = redact_secrets(cmd)[:200]
    now_iso = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    record = {
        "timestamp": now_iso,
        "command": snippet,
        "decision": decision,
    }
    if reason:
        record["reason"] = reason

    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        with open(log_file, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")
    except OSError:
        pass


def run_safety_gate(
    cmd: str | None = None,
    payload: dict[str, Any] | None = None,
    workspace: Path | None = None,
) -> tuple[int, dict[str, Any]]:
    """Evaluate a tool-use command against destructive patterns.

    Fail-closed: if unable to parse the command or command is empty, returns force_ask.
    """
    root = workspace or Path.cwd()
    if cmd is None and payload is not None:
        tc = payload.get("toolCall", {})
        args = tc.get("args", {})
        cmd = args.get("CommandLine", "")
    if not cmd or not isinstance(cmd, str) or not cmd.strip():
        reason = "Unable to parse command — requesting confirmation"
        log_gate_event(cmd or "", "BLOCKED", reason, root)
        return 0, {
            "decision": "force_ask",
            "reason": f"🛡️ Safety Gate: {reason}",
        }

    trimmed = cmd.strip()

    # Pre-tokenization normalization & evasion detection
    candidates = [cmd]
    unescaped = re.sub(r"\\([a-zA-Z0-9_\-\.\/])", r"\1", cmd)
    if unescaped != cmd:
        candidates.append(unescaped)
    for src in [cmd, unescaped]:
        try:
            toks = shlex.split(src)
            if toks:
                candidates.append(" ".join(toks))
        except Exception:
            pass
    dequoted = re.sub(r"['\"]([a-zA-Z0-9_\-]+)['\"]", r"\1", unescaped)
    if dequoted not in candidates:
        candidates.append(dequoted)

    # Fast-path: benign read-only inspection commands without chaining or force flags (<0.01ms)
    if any(trimmed.startswith(prefix) for prefix in SAFE_COMMAND_PREFIXES):
        if not any(c in trimmed for c in METACHARACTERS):
            tokens = trimmed.split()
            is_dangerous = any(
                t in DANGEROUS_FLAGS
                or t.startswith(("-D", "-d", "-M", "--output", "--ext-cmd", "--force", "--delete"))
                or (t.startswith("-") and not t.startswith("--") and any(c in t for c in "fDdM"))
                for t in tokens
            )
            if not is_dangerous:
                from aegis_core.command_safety import CommandAnalyzer

                eval_res = CommandAnalyzer.evaluate(cmd)
                if not eval_res.is_destructive:
                    log_gate_event(cmd, "ALLOWED", "", root)
                    return 0, {"decision": "allow"}

    # Structured AST / Token Analyzer (aegis_core.command_safety)
    from aegis_core.command_safety import CommandAnalyzer

    for cand in candidates:
        eval_res = CommandAnalyzer.evaluate(cand)
        if eval_res.is_destructive:
            log_gate_event(cmd, "BLOCKED", eval_res.reason, root)
            return 0, {
                "decision": "force_ask",
                "reason": f"🛡️ Safety Gate: {eval_res.reason}",
            }

    log_gate_event(cmd, "ALLOWED", "", root)
    return 0, {"decision": "allow"}

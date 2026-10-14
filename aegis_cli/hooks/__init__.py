"""Cross-platform lifecycle hook runner and git hook manager for Soma Governance."""
from __future__ import annotations

from aegis_cli.hooks.__main__ import main
from aegis_cli.hooks.management import (
    CURRENT_HOOK_FORMAT_VERSION,
    SOMA_HOOK_FORMAT,
    _SOMA_HOOK_END,
    _SOMA_HOOK_START,
    _replace_hook_block,
    generate_hook_block,
    hook_status,
    install_hook,
    run_hook_install,
    run_hook_status,
    run_hook_uninstall,
    uninstall_hook,
)
from aegis_cli.hooks.redaction import (
    SECRET_REPLACEMENTS,
    redact_secrets,
)
from aegis_cli.hooks.runtime import (
    HookCommand,
    run_hook,
    run_pre_commit,
    run_pre_invocation,
    run_session_close,
)
from aegis_cli.hooks.safety import (
    DANGEROUS_FLAGS,
    METACHARACTERS,
    SAFE_COMMAND_PREFIXES,
    _find_gate_log_dir,
    log_gate_event,
    run_safety_gate,
)

__all__ = [
    "SAFE_COMMAND_PREFIXES",
    "METACHARACTERS",
    "DANGEROUS_FLAGS",
    "SECRET_REPLACEMENTS",
    "redact_secrets",
    "_find_gate_log_dir",
    "log_gate_event",
    "run_safety_gate",
    "run_pre_invocation",
    "run_session_close",
    "run_pre_commit",
    "_SOMA_HOOK_START",
    "_SOMA_HOOK_END",
    "SOMA_HOOK_FORMAT",
    "CURRENT_HOOK_FORMAT_VERSION",
    "generate_hook_block",
    "_replace_hook_block",
    "install_hook",
    "uninstall_hook",
    "hook_status",
    "run_hook_install",
    "run_hook_uninstall",
    "run_hook_status",
    "run_hook",
    "HookCommand",
    "main",
]

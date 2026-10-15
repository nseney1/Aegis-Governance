"""Git pre-commit hook management and the isolated command safety gate."""
from __future__ import annotations

from aegis_cli.hooks.management import (
    AEGIS_HOOK_FORMAT,
    CURRENT_HOOK_FORMAT_VERSION,
    SOMA_HOOK_FORMAT,
    _AEGIS_HOOK_END,
    _AEGIS_HOOK_START,
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
    "_AEGIS_HOOK_START",
    "_AEGIS_HOOK_END",
    "AEGIS_HOOK_FORMAT",
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
]

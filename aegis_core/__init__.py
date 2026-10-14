"""aegis_core package - foundational state and security primitives."""
from __future__ import annotations

import importlib
from typing import Any

__version__ = "3.0.0"

# Explicit mapping of exported symbol name -> (module_name, attribute_name)
_EXPORTS: dict[str, tuple[str, str | None]] = {
    # Submodules
    "proposals": ("aegis_core.proposals", None),
    "rule_inventory": ("aegis_core.rule_inventory", None),
    "command_safety": ("aegis_core.command_safety", None),
    "defects": ("aegis_core.defects", None),
    "enforcement": ("aegis_core.enforcement", None),
    "errors": ("aegis_core.errors", None),
    "evidence": ("aegis_core.evidence", None),
    "evidence_collector": ("aegis_core.evidence_collector", None),
    "homeostasis": ("aegis_core.homeostasis", None),
    "inference_provider": ("aegis_core.inference_provider", None),
    "insights": ("aegis_core.insights", None),
    "lifecycle": ("aegis_core.lifecycle", None),
    "locking": ("aegis_core.locking", None),
    "metrics": ("aegis_core.metrics", None),
    "outcomes": ("aegis_core.outcomes", None),
    "quarantine": ("aegis_core.quarantine", None),
    "receipts": ("aegis_core.receipts", None),
    "scoring": ("aegis_core.scoring", None),
    "sentinels": ("aegis_core.sentinels", None),
    "skills": ("aegis_core.skills", None),
    "yaml": ("aegis_core.yaml", None),
    "storage": ("aegis_core.storage", None),
    "sweep_session": ("aegis_core.sweep_session", None),
    "sync": ("aegis_core.sync", None),
    "telemetry": ("aegis_core.telemetry", None),
    "verification": ("aegis_core.verification", None),
    "workspace": ("aegis_core.workspace", None),
    # Core types & functions
    "CommandAnalyzer": ("aegis_core.command_safety", "CommandAnalyzer"),
    "SafetyEvaluation": ("aegis_core.command_safety", "SafetyEvaluation"),
    "RuleInventory": ("aegis_core.rule_inventory", "RuleInventory"),
    "RuleInventoryEntry": ("aegis_core.rule_inventory", "RuleInventoryEntry"),
    "RuleInventoryError": ("aegis_core.rule_inventory", "RuleInventoryError"),
    "inventory_rules": ("aegis_core.rule_inventory", "inventory_rules"),
    "issue_receipt": ("aegis_core.receipts", "issue_receipt"),
    "verify_receipt": ("aegis_core.receipts", "verify_receipt"),
    "clear_receipts": ("aegis_core.receipts", "clear_receipts"),
    "compute_cell_digest": ("aegis_core.receipts", "compute_cell_digest"),
    "compute_file_digest": ("aegis_core.receipts", "compute_file_digest"),
    "ReceiptExpiredError": ("aegis_core.errors", "ReceiptExpiredError"),
    "resolve_workspace": ("aegis_core.workspace", "resolve_workspace"),
    "workspace_lock": ("aegis_core.locking", "workspace_lock"),
    "LockTimeoutError": ("aegis_core.errors", "LockTimeoutError"),
    "laplace_score": ("aegis_core.scoring", "laplace_score"),
    "wilson_lower_bound": ("aegis_core.scoring", "wilson_lower_bound"),
    "calculate_fitness_status": ("aegis_core.lifecycle", "calculate_fitness_status"),
    "STATUS_NEW": ("aegis_core.lifecycle", "STATUS_NEW"),
    "STATUS_SURVIVE": ("aegis_core.lifecycle", "STATUS_SURVIVE"),
    "STATUS_ADAPT": ("aegis_core.lifecycle", "STATUS_ADAPT"),
    "STATUS_EXTINCT": ("aegis_core.lifecycle", "STATUS_EXTINCT"),
    "STATUS_APOPTOSIS": ("aegis_core.lifecycle", "STATUS_APOPTOSIS"),
    "STATUS_APOPTOSIS_WARNING": ("aegis_core.lifecycle", "STATUS_APOPTOSIS_WARNING"),
    "STATUS_DORMANT": ("aegis_core.lifecycle", "STATUS_DORMANT"),
    "parse_rule_frontmatter": ("aegis_core.yaml", "parse_rule_frontmatter"),
    "AegisYAML": ("aegis_core.yaml", "AegisYAML"),
    "AegisDocument": ("aegis_core.yaml", "AegisDocument"),
    "AegisYAMLError": ("aegis_core.yaml", "AegisYAMLError"),
    "append_signal": ("aegis_core.telemetry", "append_signal"),
    "Workspace": ("aegis_core.workspace", "Workspace"),
    "GitWorkspace": ("aegis_core.workspace", "GitWorkspace"),
    "WorkspaceError": ("aegis_core.errors", "WorkspaceError"),
    "WorkspaceNotFoundError": ("aegis_core.errors", "WorkspaceNotFoundError"),
    "PathTraversalError": ("aegis_core.errors", "PathTraversalError"),
    "AegisError": ("aegis_core.errors", "AegisError"),
    "AegisValidationError": ("aegis_core.errors", "AegisValidationError"),
    "RuleCorruptError": ("aegis_core.errors", "RuleCorruptError"),
}

__all__ = list(_EXPORTS.keys())


def __getattr__(name: str) -> Any:
    if name in _EXPORTS:
        mod_name, attr_name = _EXPORTS[name]
        module = importlib.import_module(mod_name)
        val = module if attr_name is None else getattr(module, attr_name)
        globals()[name] = val
        return val
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(list(globals().keys()) + __all__)

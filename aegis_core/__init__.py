"""aegis_core package - foundational state and security primitives."""
from __future__ import annotations

import importlib
import importlib.abc
import importlib.machinery
import sys
from typing import Any

__version__ = "3.1.0"

_LEGACY_MODULE_REDIRECTS: dict[str, str] = {
    "aegis_core.homeostasis": "aegis_core.resilience",
    "aegis_core.verification.immune_verify": "aegis_core.verification.adversarial_verify",
    "aegis_core.ast.triggers": "aegis_core.ast.match",
    "aegis_core.ast_match": "aegis_core.ast.match",
    "aegis_core.ast_triggers": "aegis_core.ast.match",
}


class _LegacyModuleRedirectFinder(importlib.abc.MetaPathFinder):
    """Redirect legacy renamed submodule imports to their canonical Aegis modules."""

    def find_spec(
        self,
        fullname: str,
        path: Any = None,
        target: Any = None,
    ) -> importlib.machinery.ModuleSpec | None:
        canonical = _LEGACY_MODULE_REDIRECTS.get(fullname)
        if canonical is None:
            return None
        return importlib.machinery.ModuleSpec(
            name=fullname,
            loader=_LegacyModuleRedirectLoader(canonical),
        )


class _LegacyModuleRedirectLoader(importlib.abc.Loader):
    def __init__(self, canonical: str) -> None:
        self.canonical = canonical

    def create_module(self, spec: importlib.machinery.ModuleSpec) -> Any:
        mod = importlib.import_module(self.canonical)
        sys.modules[spec.name] = mod
        return mod

    def exec_module(self, module: Any) -> None:
        pass


if not any(isinstance(f, _LegacyModuleRedirectFinder) for f in sys.meta_path):
    sys.meta_path.insert(0, _LegacyModuleRedirectFinder())

# Explicit mapping of exported symbol name -> (module_name, attribute_name)
_EXPORTS: dict[str, tuple[str, str | None]] = {
    # Submodules
    "ast_match": ("aegis_core.ast.match", None),
    "proposals": ("aegis_core.proposals", None),
    "rule_inventory": ("aegis_core.rule_inventory", None),
    "command_safety": ("aegis_core.command_safety", None),
    "defects": ("aegis_core.defects", None),
    "enforcement": ("aegis_core.enforcement", None),
    "errors": ("aegis_core.errors", None),
    "evidence": ("aegis_core.evidence", None),
    "evidence_collector": ("aegis_core.evidence_collector", None),
    "resilience": ("aegis_core.resilience", None),
    "homeostasis": ("aegis_core.resilience", None),
    "inference_provider": ("aegis_core.inference_provider", None),
    "insights": ("aegis_core.insights", None),
    "integrity": ("aegis_core.integrity", None),
    "lifecycle": ("aegis_core.lifecycle", None),
    "locking": ("aegis_core.locking", None),
    "metrics": ("aegis_core.metrics", None),
    "operations": ("aegis_core.operations", None),
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
    "taxonomy": ("aegis_core.taxonomy", None),
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
    "inventory_cells": ("aegis_core.rule_inventory", "inventory_cells"),
    "ReceiptManager": ("aegis_core.receipts", "ReceiptManager"),
    "ReceiptStore": ("aegis_core.receipts", "ReceiptStore"),
    "ReceiptVerificationError": ("aegis_core.receipts", "ReceiptVerificationError"),
    "issue_receipt": ("aegis_core.receipts", "issue_receipt"),
    "verify_receipt": ("aegis_core.receipts", "verify_receipt"),
    "clear_receipts": ("aegis_core.receipts", "clear_receipts"),
    "compute_rule_digest": ("aegis_core.receipts", "compute_rule_digest"),
    "compute_cell_digest": ("aegis_core.receipts", "compute_cell_digest"),
    "compute_file_digest": ("aegis_core.receipts", "compute_file_digest"),
    "ReceiptExpiredError": ("aegis_core.errors", "ReceiptExpiredError"),
    "resolve_workspace": ("aegis_core.workspace", "resolve_workspace"),
    "workspace_lock": ("aegis_core.locking", "workspace_lock"),
    "acquire_lock": ("aegis_core.locking", "acquire_lock"),
    "LockTimeoutError": ("aegis_core.errors", "LockTimeoutError"),
    "laplace_score": ("aegis_core.scoring", "laplace_score"),
    "wilson_lower_bound": ("aegis_core.scoring", "wilson_lower_bound"),
    "calculate_fitness_status": ("aegis_core.lifecycle", "calculate_fitness_status"),
    "STATUS_NEW": ("aegis_core.lifecycle", "STATUS_NEW"),
    "STATUS_SURVIVE": ("aegis_core.lifecycle", "STATUS_SURVIVE"),
    "STATUS_ADAPT": ("aegis_core.lifecycle", "STATUS_ADAPT"),
    "STATUS_EXTINCT": ("aegis_core.lifecycle", "STATUS_EXTINCT"),
    "STATUS_RETIRED": ("aegis_core.lifecycle", "STATUS_RETIRED"),
    "STATUS_RETIRED_WARNING": ("aegis_core.lifecycle", "STATUS_RETIRED_WARNING"),
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

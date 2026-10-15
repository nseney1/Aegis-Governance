"""Normalized AST package for language-agnostic Layer 1 static analysis."""
from __future__ import annotations

from .schema import (
    CallSiteNode,
    DefinitionNode,
    ImportNode,
    MutationPoint,
    NormalizedAST,
    SymbolDef,
)
from .drivers.python import parse_python_ast
from .runner import (
    ASTDriverError,
    ASTDriverRegistry,
    ASTDriverRunner,
    ASTDriverTimeoutError,
    NoDriverConfiguredError,
)
from .detect import (
    LANGUAGE_DEFINITIONS,
    detect_project_languages,
    provision_ast_driver_slots,
    resolve_recommended_drivers,
)
from . import match, policy
from .match import (
    ASTTriggerVisitor,
    match_ast_triggers,
    prefilter_ast_tokens,
)
from .policy import (
    evaluate_forbid_ast,
    extract_normalized_ast,
    synthesize_planned_ast,
)

triggers = match

__all__ = [
    "ASTDriverError",
    "ASTDriverRegistry",
    "ASTDriverRunner",
    "ASTDriverTimeoutError",
    "ASTTriggerVisitor",
    "CallSiteNode",
    "DefinitionNode",
    "ImportNode",
    "LANGUAGE_DEFINITIONS",
    "MutationPoint",
    "NoDriverConfiguredError",
    "NormalizedAST",
    "SymbolDef",
    "detect_project_languages",
    "evaluate_forbid_ast",
    "extract_normalized_ast",
    "match",
    "match_ast_triggers",
    "parse_python_ast",
    "policy",
    "prefilter_ast_tokens",
    "provision_ast_driver_slots",
    "resolve_recommended_drivers",
    "synthesize_planned_ast",
    "triggers",
]

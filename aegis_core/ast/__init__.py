"""Normalized AST package for language-agnostic Layer 1 static analysis."""
from __future__ import annotations

from .schema import (
    CallSiteNode,
    DefinitionNode,
    ImportNode,
    MutationPoint,
    NormalizedAST,
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
from . import match
from .match import (
    ASTTriggerVisitor,
    match_ast_triggers,
    prefilter_ast_tokens,
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
    "detect_project_languages",
    "match",
    "match_ast_triggers",
    "parse_python_ast",
    "prefilter_ast_tokens",
    "provision_ast_driver_slots",
    "resolve_recommended_drivers",
    "triggers",
]

"""Control Plane: Tool definitions, argument normalization, and workspace confinement."""
from __future__ import annotations

import os
from pathlib import Path
import re
import sys
from typing import Any, Dict, List, Optional, Tuple

from aegis_core.rule_inventory import CellInventoryError, RuleInventoryError, inventory_cells, inventory_rules
from aegis_core.taxonomy import MCP_SUPPORTED_RULE_TYPE_ENUM, REVIEW_MODES
from aegis_core.workspace import resolve_workspace as _core_resolve_workspace
from aegis_core.integrity import generate_key, generate_manifest, load_key, save_manifest
from aegis_mcp.jit_engine import express as jit_express, parse_frontmatter, warn
from aegis_mcp.security import Workspace, confine_path, confine_workspace, validate_rule_names

# Try importing Governance SDK
try:
    from aegis_sdk.governance import Governance
    _HAS_SDK = True
except ImportError:
    _HAS_SDK = False

try:
    from aegis_core.proposals import soma_propose_change
except ImportError:
    soma_propose_change = None

try:
    from aegis_core.verification.checkpoint_checks import (
        CHECK_NAMES as _CHECKPOINT_NAMES,
        check_arbitration_evidence as _checkpoint_arbitration_evidence,
        check_assertion_density as _checkpoint_assertion_density,
        check_cell_conventions as _checkpoint_cell_conventions,
        check_cell_fitness as _checkpoint_cell_fitness,
        check_hardcoded_paths as _checkpoint_hardcoded_paths,
        check_test_coverage as _checkpoint_test_coverage,
        run_all_checks as _run_checkpoint_checks,
    )
except ImportError:
    _run_checkpoint_checks = None
    _checkpoint_test_coverage = None
    _checkpoint_hardcoded_paths = None
    _checkpoint_assertion_density = None
    _checkpoint_cell_fitness = None
    _checkpoint_cell_conventions = None
    _checkpoint_arbitration_evidence = None
    _CHECKPOINT_NAMES = []


_STATUS_PASS = "PASS"
_STATUS_FAIL = "FAIL"
_VALID_OUTCOMES = ("success", "partial", "failure", "tp", "fp", "pass", "fail")
_VERDICT_RE = re.compile(r"^\s*VERDICT:\s*([A-Z_]+)")
_PASSING_VERDICTS = ("APPROVED", "PASS", "SUCCESS", "OK")

# Disabled-by-Default Policy
DISABLED_BY_DEFAULT_TOOLS: frozenset[str] = frozenset({
    "aegis_propose_change",
})


def resolve_workspace(args=None):
    """Find the project root containing .soma/cells/ strictly from environment or context."""
    return _core_resolve_workspace(strict_env=True)


def _get_workspace(args: dict | None = None) -> Workspace:
    """Resolve and confine target workspace into a Workspace value object."""
    tools_mod = sys.modules.get("aegis_mcp.tools")
    resolve_fn = getattr(tools_mod, "resolve_workspace", resolve_workspace) if tools_mod else resolve_workspace
    raw = (args.get("workspace") if args else None) or resolve_fn(args)
    if isinstance(raw, Workspace):
        return raw
    confine_fn = getattr(tools_mod, "confine_workspace", confine_workspace) if tools_mod else confine_workspace
    if confine_fn is not confine_workspace:
        raw = confine_fn(raw)
        if isinstance(raw, Workspace):
            return raw
    return Workspace.confine(raw)



def get_governance(args=None):
    tools_mod = sys.modules.get("aegis_mcp.tools")
    has_sdk = getattr(tools_mod, "_HAS_SDK", _HAS_SDK) if tools_mod else _HAS_SDK
    if not has_sdk:
        return None
    try:
        workspace = _get_workspace(args)
    except ValueError:
        return None
    return Governance(project_root=workspace)



def normalize_tool_call(tool_name: str, arguments: dict) -> Tuple[str, dict]:
    """Identity pass-through for tool calls in Aegis v2.0."""
    return tool_name, dict(arguments or {})


def _cell_diagnostic(relative_path: str, message: str) -> dict:
    return {
        "_name": os.path.splitext(os.path.basename(relative_path))[0],
        "_path": relative_path,
        "_error": message,
    }


def _matches_cell_type_filter(rel: str, cell_type: Optional[str] = None) -> bool:
    if not cell_type:
        return True
    parent_name = os.path.basename(os.path.dirname(rel))
    return (
        parent_name in (cell_type, f"{cell_type}s")
        or f"/{cell_type}/" in rel
        or f"/{cell_type}s/" in rel
    )


def _list_cells_stdlib(workspace, cell_type=None):
    """List cells from one canonical byte snapshot using the shared parser."""
    tools_mod = sys.modules.get("aegis_mcp.tools")
    inv_fn = getattr(tools_mod, "inventory_cells", inventory_cells) if tools_mod else inventory_cells
    try:
        inventory = inv_fn(workspace)
    except CellInventoryError as exc:
        return {"status": _STATUS_FAIL, "error": str(exc)}


    cells = []
    for entry in inventory.entries:
        rel = entry.relative_path
        if os.path.basename(rel) == "README.md":
            continue

        path_matches = _matches_cell_type_filter(rel, cell_type)

        try:
            content = entry.content.decode("utf-8")
        except UnicodeDecodeError as exc:
            if not path_matches:
                continue
            message = f"invalid UTF-8: {exc}"
            warn(f"skipped cell {rel}: {message}")
            cells.append(_cell_diagnostic(rel, message))
            continue

        fm = parse_frontmatter(content)
        if fm is None:
            if not path_matches:
                continue
            message = "malformed YAML frontmatter"
            warn(f"skipped cell {rel}: {message}")
            cells.append(_cell_diagnostic(rel, message))
            continue
        if not fm:
            if not path_matches:
                continue
            message = "no frontmatter metadata"
            warn(f"skipped cell {rel}: {message}")
            cells.append(_cell_diagnostic(rel, message))
            continue

        if cell_type and not (fm.get("type") == cell_type or path_matches):
            continue

        fm["_name"] = os.path.splitext(os.path.basename(rel))[0]
        fm["_path"] = rel
        cells.append(fm)
    return cells


def _classify_propose_result(result):
    """Classify a soma_propose_change return value as (status, verdict)."""
    verdict = None
    if isinstance(result, str):
        match = _VERDICT_RE.match(result)
        if match:
            verdict = match.group(1)
        elif result.lstrip().upper().startswith("SUCCESS"):
            verdict = "SUCCESS"
    elif isinstance(result, dict):
        if "error" in result:
            return _STATUS_FAIL, None
        verdict = str(result.get("status", "")).upper() or None
    if verdict is None:
        return _STATUS_FAIL, None
    return (_STATUS_PASS if verdict in _PASSING_VERDICTS else _STATUS_FAIL), verdict


def build_cell_create_prompt(description: str, domain_hint: str = None, cell_type: str = None, args=None) -> str:
    workspace = _get_workspace(args)
    examples = []
    tools_mod = sys.modules.get("aegis_mcp.tools")
    inv_fn = getattr(tools_mod, "inventory_cells", inventory_cells) if tools_mod else inventory_cells
    inventory = inv_fn(workspace)
    for entry in inventory.entries:
        rel = entry.relative_path
        if os.path.basename(rel) == "README.md":
            continue
        try:
            content = entry.content.decode("utf-8")
        except UnicodeDecodeError as exc:
            warn(f"skipped cell example {rel}: invalid UTF-8: {exc}")
            continue
        if content.startswith("---"):
            examples.append(content[:500])

    example_text = "\n---\n".join(examples[:3]) if examples else "No existing cells found."
    domain_context = f"\nDomain hint: {domain_hint}" if domain_hint else ""
    type_hint = f"\nPreferred cell type: {cell_type}" if cell_type else ""

    prompt = f"""You are a governance rule generator for Aegis.

Given a natural language description of a concern, generate a governance rule in markdown with YAML frontmatter.

Rule types:
- invariant: Non-negotiable invariant (hard safety gate). Use for things that must ALWAYS hold.
- trap: Learned anti-pattern trap. Use for known failure modes to watch for.
- boundary: Escalation gate. Use when sensitive areas need elevated review.
- persona: Domain persona/accelerator. Use for idiomatic patterns to follow.
- contract: Cross-service contract. Use for API/data shape agreements.

YAML fields required:
- type: (one of above)
- domain: (one of: efficiency, correctness, security, style, governance)
- enforcement: (gate for invariants, advisory for traps)
- hypothesis: (clear, testable statement)
- prediction: (what will happen if the hypothesis is violated)
- falsification: (how to prove this cell is no longer needed)
- target_paths: (list of file glob patterns this cell monitors)
- minimum_mode: ({' | '.join(REVIEW_MODES)})
- tags: (list of relevant tags)

Optionally include:
- fitness: (triggers: 0, true_positives: 0, false_positives: 0, score: null)

Existing cells in this project for reference:
{example_text}
{domain_context}{type_hint}

User description: "{description}"

Generate ONLY the complete markdown cell file content. Start with --- for the YAML frontmatter. After the closing ---, include a brief description paragraph explaining the cell's purpose. Do not include any other text."""

    return prompt


build_rule_create_prompt = build_cell_create_prompt


# ── Canonical MCP Tool Definitions with Opt-In Response Projection ───────────

TOOL_DEFINITIONS = [
    {
        "name": "aegis_request_receipt",
        "description": "Request an execution receipt for a privileged tool. Required before calling any write tools, or execution tools (if execution is enabled).",
        "annotations": {
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
            "title": "Request Receipt",
        },
        "inputSchema": {
            "type": "object",
            "properties": {
                "operation": {"type": "string", "description": "The name of the execute tool you want to call."},
                "arguments": {"type": "object", "description": "The arguments you will pass to the execute tool."},
                "view": {"type": "string", "enum": ["full", "summary", "ids"], "description": "Optional response projection view"},
                "fields": {"type": "array", "items": {"type": "string"}, "description": "Optional list of dot-notated field paths to project"},
            },
            "required": ["operation", "arguments"],
        },
    },
    {
        "name": "aegis_create_rule",
        "description": "Takes a natural language description and builds a prompt to create a governance rule.",
        "annotations": {
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
            "title": "Create Rule",
        },
        "inputSchema": {
            "type": "object",
            "properties": {
                "description": {"type": "string", "description": "Natural language description"},
                "rule_type": {"type": "string", "enum": list(MCP_SUPPORTED_RULE_TYPE_ENUM), "description": "Optional rule type hint"},
                "domain": {"type": "string", "description": "Optional domain hint"},
                "dry_run": {"type": "boolean", "default": False, "description": "Optional dry run flag"},
                "receipt": {"type": "string", "description": "Execution receipt ID obtained from aegis_request_receipt"},
                "view": {"type": "string", "enum": ["full", "summary", "ids"]},
                "fields": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["description", "receipt"],
        },
    },
    {
        "name": "aegis_list_rules",
        "description": "Lists all governance rules with their type, hypothesis, and fitness data.",
        "annotations": {
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
            "title": "List Rules",
        },
        "inputSchema": {
            "type": "object",
            "properties": {
                "rule_type": {"type": "string", "enum": list(MCP_SUPPORTED_RULE_TYPE_ENUM), "description": "Optional rule type filter"},
                "view": {"type": "string", "enum": ["full", "summary", "ids"]},
                "fields": {"type": "array", "items": {"type": "string"}},
            },
        },
    },
    {
        "name": "aegis_propose_change",
        "description": "Propose a code change for safety evaluation against all active cells (Layer 2 TTC Verifier).",
        "annotations": {
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
            "title": "Propose Change",
        },
        "inputSchema": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "Path to the file being modified."},
                "proposed_content": {"type": "string", "description": "The proposed content of the file."},
                "receipt": {"type": "string", "description": "Execution receipt ID obtained from aegis_request_receipt."},
                "view": {"type": "string", "enum": ["full", "summary", "ids"]},
                "fields": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["file_path", "proposed_content"],
        },
    },
    {
        "name": "aegis_audit_security",
        "description": "Static security analysis checking for common OWASP vulnerabilities and exposed credentials.",
        "annotations": {
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
            "title": "Security Audit",
        },
        "inputSchema": {
            "type": "object",
            "properties": {
                "proposed_content": {"type": "string", "description": "The proposed file content to analyze."},
                "file_path": {"type": "string", "description": "The file path being modified."},
                "view": {"type": "string", "enum": ["full", "summary", "ids"]},
                "fields": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["proposed_content"],
        },
    },
    {
        "name": "aegis_audit_performance",
        "description": "Static performance analysis checking for inefficient operations and anti-patterns.",
        "annotations": {
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
            "title": "Performance Audit",
        },
        "inputSchema": {
            "type": "object",
            "properties": {
                "proposed_content": {"type": "string", "description": "The proposed file content to analyze."},
                "file_path": {"type": "string", "description": "The file path being modified."},
                "view": {"type": "string", "enum": ["full", "summary", "ids"]},
                "fields": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["proposed_content"],
        },
    },
    {
        "name": "aegis_verify_changes",
        "description": "Run verification pipeline on a set of modified files.",
        "annotations": {
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
            "title": "Verify Changes",
        },
        "inputSchema": {
            "type": "object",
            "properties": {
                "files": {"type": "array", "items": {"type": "string"}, "description": "List of relative file paths to verify."},
                "layer1_only": {"type": "boolean", "default": True, "description": "If true, run only fast Layer 1 checks."},
                "async_mode": {"type": "boolean", "default": False, "description": "If true, enqueues verification job and returns job_id immediately."},
                "task_plan": {"type": "string", "description": "Optional task plan for Layer 2 arbitration."},
                "rebuttal": {"type": "string", "description": "Optional rebuttal against existing charges."},
                "receipt": {"type": "string", "description": "Optional execution receipt."},
                "view": {"type": "string", "enum": ["full", "summary", "ids"]},
                "fields": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["files"],
        },
    },
    {
        "name": "aegis_poll_verification",
        "description": "Poll status or retrieve results for an asynchronous verification job.",
        "annotations": {
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
            "title": "Poll Verification",
        },
        "inputSchema": {
            "type": "object",
            "properties": {
                "job_id": {"type": "string", "description": "Job ID returned by aegis_verify_changes(async_mode=True)."},
                "view": {"type": "string", "enum": ["full", "summary", "ids"]},
                "fields": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["job_id"],
        },
    },
    {
        "name": "aegis_checkpoint",
        "description": "Run deterministic quality checks against project files.",
        "annotations": {
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
            "title": "Checkpoint",
        },
        "inputSchema": {
            "type": "object",
            "properties": {
                "receipt": {"type": "string", "description": "Execution receipt ID obtained from aegis_request_receipt."},
                "view": {"type": "string", "enum": ["full", "summary", "ids"]},
                "fields": {"type": "array", "items": {"type": "string"}},
            },
        },
    },
    {
        "name": "aegis_scan",
        "description": "Scan files against active cells to express JIT rules and compute salience.",
        "annotations": {
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
            "title": "Scan JIT Rules",
        },
        "inputSchema": {
            "type": "object",
            "properties": {
                "files": {"type": "array", "items": {"type": "string"}, "description": "Files to scan for applicable rules."},
                "view": {"type": "string", "enum": ["full", "summary", "ids"]},
                "fields": {"type": "array", "items": {"type": "string"}},
            },
        },
    },
    {
        "name": "aegis_report_outcome",
        "description": "Report verification outcome signal for cell fitness tracking.",
        "annotations": {
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
            "title": "Report Outcome",
        },
        "inputSchema": {
            "type": "object",
            "properties": {
                "outcome": {"type": "string", "enum": ["success", "partial", "failure", "tp", "fp", "pass", "fail"], "description": "Verification outcome."},
                "idempotency_key": {"type": "string", "description": "Unique key to prevent duplicate reporting."},
                "cells_used": {"type": "array", "items": {"type": "string"}, "description": "Rule names used in verification."},
                "tests_passed": {"type": "boolean"},
                "rework_count": {"type": "integer", "default": 0},
                "notes": {"type": "string"},
                "receipt": {"type": "string", "description": "Execution receipt ID obtained from aegis_request_receipt."},
                "view": {"type": "string", "enum": ["full", "summary", "ids"]},
                "fields": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["outcome", "idempotency_key"],
        },
    },
    {
        "name": "aegis_capture_insight",
        "description": "Capture human developer insight and optionally scaffold a Wall cell.",
        "annotations": {
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
            "title": "Capture Insight",
        },
        "inputSchema": {
            "type": "object",
            "properties": {
                "insight": {"type": "string", "description": "Human developer insight text."},
                "context_files": {"type": "array", "items": {"type": "string"}, "description": "Context file paths."},
                "source_conversation": {"type": "string"},
                "category": {"type": "string"},
                "scaffold_wall": {"type": "boolean", "default": False},
                "wall_id": {"type": "string"},
                "receipt": {"type": "string", "description": "Execution receipt ID obtained from aegis_request_receipt."},
                "view": {"type": "string", "enum": ["full", "summary", "ids"]},
                "fields": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["insight", "context_files"],
        },
    },
    {
        "name": "aegis_generate_manifest",
        "description": "Generate integrity manifest of all cells in project.",
        "annotations": {
            "readOnlyHint": False,
            "destructiveHint": True,
            "idempotentHint": True,
            "openWorldHint": False,
            "title": "Generate Manifest",
        },
        "inputSchema": {
            "type": "object",
            "properties": {
                "generate_key": {"type": "boolean", "default": False},
                "receipt": {"type": "string", "description": "Execution receipt ID obtained from aegis_request_receipt."},
                "view": {"type": "string", "enum": ["full", "summary", "ids"]},
                "fields": {"type": "array", "items": {"type": "string"}},
            },
        },
    },
    {
        "name": "aegis_grade",
        "description": "Report project governance grading metrics.",
        "annotations": {
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
            "title": "Immune Grade",
        },
        "inputSchema": {
            "type": "object",
            "properties": {
                "view": {"type": "string", "enum": ["full", "summary", "ids"]},
                "fields": {"type": "array", "items": {"type": "string"}},
            },
        },
    },
    {
        "name": "aegis_coverage",
        "description": "Report cell coverage across codebase files.",
        "annotations": {
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
            "title": "Coverage Report",
        },
        "inputSchema": {
            "type": "object",
            "properties": {
                "view": {"type": "string", "enum": ["full", "summary", "ids"]},
                "fields": {"type": "array", "items": {"type": "string"}},
            },
        },
    },
    {
        "name": "aegis_rule_fitness",
        "description": "Returns fitness landscape showing rule health and evolution.",
        "annotations": {
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
            "title": "Rule Fitness",
        },
        "inputSchema": {
            "type": "object",
            "properties": {
                "bayesian": {"type": "boolean", "description": "Use Bayesian smoothing"},
                "view": {"type": "string", "enum": ["full", "summary", "ids"]},
                "fields": {"type": "array", "items": {"type": "string"}},
            },
        },
    },
    {
        "name": "aegis_handoff",
        "description": "Execute typed handoff between swarm skills and write a file-buffered ticket (<150 tokens).",
        "annotations": {
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
            "title": "Swarm Handoff",
        },
        "inputSchema": {
            "type": "object",
            "properties": {
                "from_skill": {"type": "string", "description": "Originating skill ID"},
                "to_skill": {"type": "string", "description": "Target skill ID"},
                "artifact_type": {"type": "string", "description": "Artifact type (e.g. ChargeSheet, DiffProposal, InspectionReceipt, TestVerdict)"},
                "payload": {"type": "object", "description": "Structured artifact payload conforming to schema"},
                "cycle_id": {"type": "string", "description": "Optional arbitration cycle ID"},
                "receipt": {"type": "string", "description": "Execution receipt ID obtained from aegis_request_receipt."},
                "view": {"type": "string", "enum": ["full", "summary", "ids"]},
                "fields": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["from_skill", "to_skill", "artifact_type", "payload"],
        },
    },
]

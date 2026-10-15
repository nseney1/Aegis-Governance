"""aegis_core.enforcement — enforcement artifacts for promoted rules.

Generates the pre-commit check scripts and gate assertions that lifecycle
promotion writes for mechanical and gate-tier rules
(aegis_core/lifecycle/promotion.py). The bug and claim registry verifiers
and the CI outcome reporter that used to live here were cut in v4 (ADR 0005
D8); tests/unit/core/test_readme_claims.py keeps the README overclaim guard.
"""
from __future__ import annotations

from datetime import datetime, timezone
import glob
import json
import os
from pathlib import Path
import re
import shlex
import sys
from typing import Any, Dict, List

from aegis_core.workspace import Workspace, as_workspace


def load_cells_for_enforcement(cells_dir: str | Path | Workspace) -> List[Dict[str, Any]]:
    """Load all cells for enforcement artifact generation."""
    cells = []
    from aegis_core.yaml import parse_frontmatter, _get_body

    if isinstance(cells_dir, Workspace):
        c_dir = str(cells_dir.rules_dir)
    else:
        p = Path(cells_dir)
        if (p / ".aegis" / "rules").is_dir():
            c_dir = str(p / ".aegis" / "rules")
        else:
            c_dir = str(cells_dir)

    for cell_file in glob.glob(os.path.join(c_dir, "**", "*.md"), recursive=True):
        if os.path.basename(cell_file) == "README.md":
            continue
        try:
            with open(cell_file, "r", encoding="utf-8-sig") as f:
                content = f.read()
            fm = parse_frontmatter(content) or {}
            body = _get_body(content)
            fm["_path"] = cell_file
            fm["_name"] = os.path.splitext(os.path.basename(cell_file))[0]
            fm["_body"] = body.strip()
            cells.append(fm)
        except Exception as exc:
            sys.stderr.write(f"Warning: Failed to parse cell {cell_file}: {exc}\n")
    return cells


load_cells = load_cells_for_enforcement
_load_cells = load_cells_for_enforcement


def generate_precommit_check(cell: Dict[str, Any], workspace: str | Path | Workspace = ".") -> str:
    """Generate a pre-commit check script for a 'mechanical' cell."""
    name = cell.get("_name") or cell.get("id") or cell.get("name", "unnamed")
    cell_type = cell.get("type", "trap")
    hypothesis = cell.get("hypothesis", "")
    target_paths = cell.get("target_paths") or []

    clean_name = re.sub(r"[\r\n]+", " ", str(name)).strip()
    clean_hyp = re.sub(r"[\r\n]+", " ", str(hypothesis)).strip()

    quoted_name = shlex.quote(name)
    quoted_hyp = shlex.quote(hypothesis[:80])
    quoted_patterns = " ".join(shlex.quote(p) for p in target_paths)

    if cell_type in ("wall", "invariant"):
        check = f"""#!/bin/bash
# Auto-generated enforcement artifact for: {clean_name}
# Type: {cell_type} | Tier: mechanical
# Hypothesis: {clean_hyp}
# Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}
#
# This check runs as part of the pre-commit hook.
# To disable: remove this file or demote the cell to advisory.

set -uo pipefail

CHANGED_FILES=$(git diff --cached --name-only 2>/dev/null)
if [ -z "$CHANGED_FILES" ]; then exit 0; fi

TARGET_PATTERNS=({quoted_patterns})
MATCHED=0

if [ ${{#TARGET_PATTERNS[@]}} -gt 0 ]; then
    while IFS= read -r file; do
        for pattern in "${{TARGET_PATTERNS[@]}}"; do
            case "$file" in
                $pattern) MATCHED=1; break 2 ;;
            esac
        done
    done <<< "$CHANGED_FILES"
fi

if [ "$MATCHED" -eq 1 ]; then
    echo -n "🛡️  ["
    echo -n {quoted_name}
    echo "] Cell triggered (mechanical enforcement)"
    echo -n "   Hypothesis: "
    echo {quoted_hyp}
    echo "   Files: $CHANGED_FILES"
    # Signal the cell via in-process python
    python3 -c "import sys; from aegis_core.telemetry import append_signal; append_signal('.', sys.argv[1], 'tp', 'mechanical')" {quoted_name} 2>/dev/null || true
    exit 1  # Mechanical: block commit
fi

exit 0  # No match: allow commit
"""
    elif cell_type in ("membrane", "boundary"):
        check = f"""#!/bin/bash
# Auto-generated enforcement artifact for: {clean_name}
# Type: {cell_type} | Tier: mechanical
# Hypothesis: {clean_hyp}
# Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}

set -uo pipefail

CHANGED_FILES=$(git diff --cached --name-only 2>/dev/null)
if [ -z "$CHANGED_FILES" ]; then exit 0; fi

TARGET_PATTERNS=({quoted_patterns})
MATCHED=0

if [ ${{#TARGET_PATTERNS[@]}} -gt 0 ]; then
    while IFS= read -r file; do
        for pattern in "${{TARGET_PATTERNS[@]}}"; do
            case "$file" in
                $pattern) MATCHED=1; break 2 ;;
            esac
        done
    done <<< "$CHANGED_FILES"
fi

if [ "$MATCHED" -eq 1 ]; then
    echo -n "⚠️  ["
    echo -n {quoted_name}
    echo "] Membrane escalation triggered (mechanical enforcement)"
    echo -n "   Hypothesis: "
    echo {quoted_hyp}
    echo "   Recommend elevated review before merging."
    exit 1  # Mechanical: block commit
fi

exit 0  # No match: allow commit
"""
    else:
        check = f"""#!/bin/bash
# Auto-generated enforcement artifact for: {clean_name}
# Type: {cell_type} | Tier: mechanical
# Hypothesis: {clean_hyp}
# Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}

set -uo pipefail

CHANGED_FILES=$(git diff --cached --name-only 2>/dev/null)
if [ -z "$CHANGED_FILES" ]; then exit 0; fi

TARGET_PATTERNS=({quoted_patterns})
MATCHED=0

if [ ${{#TARGET_PATTERNS[@]}} -gt 0 ]; then
    while IFS= read -r file; do
        for pattern in "${{TARGET_PATTERNS[@]}}"; do
            case "$file" in
                $pattern) MATCHED=1; break 2 ;;
            esac
        done
    done <<< "$CHANGED_FILES"
fi

if [ "$MATCHED" -eq 1 ]; then
    echo -n "🔍  ["
    echo -n {quoted_name}
    echo "] Trap check triggered (mechanical enforcement)"
    echo -n "   Hypothesis: "
    echo {quoted_hyp}
    exit 1  # Mechanical: block commit
fi

exit 0  # No match: allow commit
"""
    return check


def generate_gate_assertion(cell: Dict[str, Any], workspace: str | Path | Workspace = ".") -> str:
    """Generate a runtime assertion for a 'gate' cell."""
    name = cell.get("_name") or cell.get("id") or cell.get("name", "unnamed")
    cell_type = cell.get("type", "trap")
    hypothesis = cell.get("hypothesis", "")
    target_paths = cell.get("target_paths") or []

    clean_name = re.sub(r"[\r\n]+", " ", str(name)).strip()
    clean_hyp = re.sub(r"[\r\n]+", " ", str(hypothesis)).strip()
    clean_hyp_doc = clean_hyp[:100].replace('"""', "'''")

    class_suffix = re.sub(r"[^a-zA-Z0-9]", "_", name)
    json_name = json.dumps(name)
    json_hyp = json.dumps(hypothesis)
    json_targets = json.dumps(target_paths)

    assertion = f'''# Auto-generated gate assertion for: {clean_name}
# Type: {cell_type} | Tier: gate
# Hypothesis: {clean_hyp}
# Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}

import os
import subprocess
import sys


class Gate_{class_suffix}:
    """Runtime gate for: {clean_hyp_doc}"""

    CELL_NAME = {json_name}
    HYPOTHESIS = {json_hyp}
    TARGET_PATHS = {json_targets}

    @classmethod
    def check(cls, context=None):
        try:
            from aegis_core.telemetry import append_signal
            append_signal(os.getcwd(), cls.CELL_NAME, "tp", "ci")
        except Exception:
            pass

    @classmethod
    def enforce(cls, condition, message=None):
        """Assert a condition. Halt on failure."""
        if not condition:
            msg = message or f"Gate violation: {{cls.HYPOTHESIS}}"
            try:
                from aegis_core.defects import record_escaped_defect
                cell_dict = {{"_name": cls.CELL_NAME, "name": cls.CELL_NAME, "type": "wall", "enforcement": "gate"}}
                record_escaped_defect(cell_dict, "crash", cls.TARGET_PATHS, "critical", os.getcwd())
            except Exception:
                pass
            raise RuntimeError(f"\U0001f6d1 GATE VIOLATION [{{cls.CELL_NAME}}]: {{msg}}")
'''
    return assertion


def update_cell_enforcement_artifact(cell: Dict[str, Any], artifact_path: str, workspace: str | Path | Workspace = ".") -> None:
    """Add enforcement_artifact field to cell YAML."""
    cell_path = cell.get("_path")
    if not cell_path or not os.path.exists(cell_path):
        return

    with open(cell_path, "r", encoding="utf-8") as f:
        content = f.read()

    if "enforcement_artifact:" in content:
        return

    ws = as_workspace(workspace)
    rel_path = os.path.relpath(artifact_path, str(ws.root))
    from aegis_core.yaml import dump_frontmatter, parse_rule_frontmatter
    try:
        fm, body = parse_rule_frontmatter(content)
    except Exception:
        return

    fm["enforcement_artifact"] = rel_path
    new_content = dump_frontmatter(fm, body=body)
    with open(cell_path, "w", encoding="utf-8") as f:
        f.write(new_content)


__all__ = [
    "load_cells",
    "load_cells_for_enforcement",
    "generate_precommit_check",
    "generate_gate_assertion",
    "update_cell_enforcement_artifact",
]

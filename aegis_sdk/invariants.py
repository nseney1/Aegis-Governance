"""Invariant checking for gate enforcement DSL.

Provides pure functions that evaluate invariant specifications from cell
frontmatter against source files. No CLI or git dependency.
"""
from __future__ import annotations

import ast
import os
import re
from dataclasses import dataclass
from fnmatch import fnmatch
from typing import List, Optional


@dataclass
class Violation:
    """A single invariant violation."""
    invariant_type: str
    message: str
    file: str = ''


def check_import_banned(pattern: str, file_path: str) -> Optional[Violation]:
    """Check if a Python file contains a banned import pattern.

    The pattern is matched against import statements in the AST.
    Pattern format: 'from <module_glob> import <name_glob>'

    Args:
        pattern: Import pattern to ban (e.g., 'from aegis_sdk.* import *').
        file_path: Path to Python source file.

    Returns:
        Violation if banned import found, None otherwise.
    """
    if not file_path.endswith('.py'):
        return None

    try:
        with open(file_path, encoding='utf-8') as f:
            source = f.read()
        tree = ast.parse(source, filename=file_path)
    except (SyntaxError, UnicodeDecodeError, OSError):
        return None

    # Parse the ban pattern: "from X import Y"
    match = re.match(r'^from\s+(\S+)\s+import\s+(\S+)$', pattern.strip())
    if not match:
        return None
    module_glob, name_glob = match.group(1), match.group(2)

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            module_str = node.module
            if not fnmatch(module_str, module_glob):
                continue
            for alias in node.names:
                if fnmatch(alias.name, name_glob):
                    return Violation(
                        invariant_type='import_banned',
                        message=f'Banned import: from {module_str} import {alias.name} '
                                f'(matches pattern: {pattern})',
                        file=file_path,
                    )
    return None


def check_file_must_exist(path_pattern: str, workspace: str) -> Optional[Violation]:
    """Check that a required file exists in the workspace.

    Args:
        path_pattern: Relative path (from workspace root) that must exist.
        workspace: Workspace root directory.

    Returns:
        Violation if file is missing, None if it exists.
    """
    full_path = os.path.join(workspace, path_pattern)
    if os.path.exists(full_path):
        return None
    return Violation(
        invariant_type='file_must_exist',
        message=f'Required file missing: {path_pattern}',
        file=path_pattern,
    )


def check_invariants(
    invariant_specs: list,
    target_files: list,
    workspace: str,
) -> List[Violation]:
    """Evaluate all invariant specs against target files.

    Args:
        invariant_specs: List of dicts with 'type' and type-specific keys.
        target_files: List of changed file paths to check.
        workspace: Workspace root directory.

    Returns:
        List of Violation objects (empty if all pass).
    """
    violations = []
    for spec in invariant_specs:
        inv_type = spec.get('type', '')

        if inv_type == 'import_banned':
            pattern = spec.get('pattern', '')
            for f in target_files:
                v = check_import_banned(pattern, f)
                if v:
                    violations.append(v)

        elif inv_type == 'file_must_exist':
            path = spec.get('path', '')
            v = check_file_must_exist(path, workspace)
            if v:
                violations.append(v)

        # Unknown types are silently skipped (not errors)

    return violations


def evaluate_enforcement(
    violations: list,
    enforcement: str,
) -> dict:
    """Apply enforcement ladder to violations.

    The enforcement ladder:
      advisory   → warn, exit 0 (no block)
      mechanical → warn, exit 1 (pre-commit block)
      gate       → warn, exit 1 (CI block)

    Args:
        violations: List of Violation objects.
        enforcement: Enforcement tier ('advisory', 'mechanical', 'gate').

    Returns:
        dict with 'exit_code', 'action', and 'violations'.
    """
    if not violations:
        return {
            'exit_code': 0,
            'action': 'pass',
            'violations': [],
        }

    # Advisory warns but does not block
    if enforcement in ('mechanical', 'gate'):
        return {
            'exit_code': 1,
            'action': 'block',
            'violations': [{'message': v.message, 'file': v.file} for v in violations],
        }

    # Advisory or unknown → warn only
    return {
        'exit_code': 0,
        'action': 'warn',
        'violations': [{'message': v.message, 'file': v.file} for v in violations],
    }

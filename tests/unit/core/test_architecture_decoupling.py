"""Behavioral tests for BUG-079: Architectural Layer Decoupling (Layer 0 Core -> Layer 2 Inversion).

Layer 0 Core (soma_core/) is the foundational, zero-dependency engine.
It must NEVER import from Layer 2 (soma_mcp/ or soma_cli/) or Layer 1 (soma_sdk/).
Specifically, checkpoint_checks.py must not import parse_frontmatter from aegis_mcp.
"""
import ast
import os
from pathlib import Path
import pytest


def test_soma_core_has_zero_upward_imports():
    """All files in soma_core/ must have zero imports of soma_mcp, soma_cli, or aegis_sdk."""
    repo_root = next(p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").exists())
    core_dir = repo_root / "soma_core"

    violations = []
    forbidden_modules = ("soma_mcp", "soma_cli", "soma_sdk")

    for py_file in core_dir.rglob("*.py"):
        try:
            tree = ast.parse(py_file.read_text(encoding="utf-8"))
        except Exception as exc:
            violations.append(f"Failed to parse {py_file}: {exc}")
            continue

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if any(alias.name == f or alias.name.startswith(f + ".") for f in forbidden_modules):
                        violations.append(f"{py_file.relative_to(repo_root)}:{node.lineno} imports '{alias.name}'")
            elif isinstance(node, ast.ImportFrom):
                if node.module and any(node.module == f or node.module.startswith(f + ".") for f in forbidden_modules):
                    violations.append(f"{py_file.relative_to(repo_root)}:{node.lineno} imports from '{node.module}'")

    assert not violations, "Architectural Layer Inversion violations found in soma_core:\n" + "\n".join(violations)


def test_parse_frontmatter_in_soma_core():
    """parse_frontmatter must be available directly in aegis_core."""
    from aegis_core.cell_inventory import parse_frontmatter
    content = "---\ntype: learned-trap\nname: test-trap\n---\nBody here"
    fm = parse_frontmatter(content)
    assert isinstance(fm, dict)
    assert fm.get("type") == "learned-trap"


def test_zero_internal_calls_to_deprecated_workspace_getters():
    """Verify that soma_core, soma_cli, soma_mcp, soma_sdk have zero calls to deprecated getters.

    Target deprecated getters:
    - get_cells_dir
    - get_metrics_dir
    - get_signals_file
    - get_outcomes_file
    """
    repo_root = next(p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").exists())
    deprecated_symbols = {
        "get_cells_dir",
        "get_metrics_dir",
        "get_signals_file",
        "get_outcomes_file",
    }
    checked_packages = ["soma_core", "soma_cli", "soma_mcp", "soma_sdk"]
    violations = []

    for pkg_name in checked_packages:
        pkg_dir = repo_root / pkg_name
        if not pkg_dir.is_dir():
            continue
        for py_file in pkg_dir.rglob("*.py"):
            # Exclude soma_core/workspace.py where the deprecated functions are defined
            if py_file.resolve() == (repo_root / "soma_core" / "workspace.py").resolve():
                continue
            try:
                tree = ast.parse(py_file.read_text(encoding="utf-8"))
            except Exception as exc:
                violations.append(f"Failed to parse {py_file}: {exc}")
                continue

            for node in ast.walk(tree):
                # Check direct calls: get_cells_dir(...)
                if isinstance(node, ast.Call):
                    if isinstance(node.func, ast.Name) and node.func.id in deprecated_symbols:
                        violations.append(
                            f"{py_file.relative_to(repo_root)}:{node.lineno} calls deprecated function '{node.func.id}'"
                        )
                    elif isinstance(node.func, ast.Attribute) and node.func.attr in deprecated_symbols:
                        violations.append(
                            f"{py_file.relative_to(repo_root)}:{node.lineno} calls deprecated attribute '{node.func.attr}'"
                        )
                # Check imports: from aegis_core.workspace import get_cells_dir
                elif isinstance(node, ast.ImportFrom):
                    for alias in node.names:
                        if alias.name in deprecated_symbols:
                            violations.append(
                                f"{py_file.relative_to(repo_root)}:{node.lineno} imports deprecated function '{alias.name}'"
                            )

    assert not violations, "Found internal usage of deprecated workspace getters:\n" + "\n".join(violations)


def test_purged_symbols_permanently_absent():
    """Verify that all purged legacy symbols and aliases are permanently absent."""
    import aegis_core.workspace
    import aegis_core.yaml
    import aegis_cli.doctor

    purged_workspace_symbols = [
        "get_cells_dir",
        "get_metrics_dir",
        "get_signals_file",
        "get_outcomes_file",
        "find_workspace_root",
    ]
    for sym in purged_workspace_symbols:
        assert not hasattr(aegis_core.workspace, sym), f"aegis_core.workspace should not have {sym}"

    assert not hasattr(aegis_cli.doctor, "_check_pyyaml"), "aegis_cli.doctor should not have _check_pyyaml"
    assert not hasattr(aegis_core.yaml, "_parse_frontmatter"), "aegis_core.yaml should not have _parse_frontmatter"


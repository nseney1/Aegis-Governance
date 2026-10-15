"""Architectural invariants from the v0.96.0 Tempest Review that still hold in v4.

1. Layer decoupling: aegis_core never imports aegis_sdk, aegis_cli or aegis_mcp.
2. Symbol authority: every name in an aegis_core module's __all__ resolves.
3. Fail-closed confinement: workspace path confinement rejects relative and
   absolute traversal, Windows device names and alternate data streams.

The receipt, MCP rate-limit and bug-registry invariants were retired with
the features (ADR 0005 D2, D4, D8).
"""
from __future__ import annotations

import ast
import importlib
from pathlib import Path

import pytest

from aegis_core.workspace import confine_path, resolve_workspace


REPO_ROOT = Path(resolve_workspace(__file__))


class TestInvariant1_LayerDecoupling:
    """Invariant 1: aegis_core must be strictly layered and never import upward."""

    def test_core_has_zero_upward_imports(self):
        core_dir = REPO_ROOT / "aegis_core" if (REPO_ROOT / "aegis_core").exists() else REPO_ROOT / "aegis_core"
        python_files = list(core_dir.glob("*.py"))
        assert len(python_files) > 0, "core files not found"

        violations = []
        forbidden = ("aegis_sdk", "soma_sdk", "enzymes", "aegis_cli", "soma_cli", "aegis_mcp", "soma_mcp")
        for py_file in python_files:
            tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name.startswith(forbidden):
                            violations.append((py_file.name, node.lineno, alias.name))
                elif isinstance(node, ast.ImportFrom):
                    if node.module and node.module.startswith(forbidden):
                        violations.append((py_file.name, node.lineno, node.module))
                elif isinstance(node, ast.Call):
                    if isinstance(node.func, ast.Attribute) and node.func.attr == "import_module":
                        if node.args and isinstance(node.args[0], ast.Constant) and str(node.args[0].value).startswith(forbidden):
                            violations.append((py_file.name, node.lineno, node.args[0].value))
                    elif isinstance(node.func, ast.Name) and node.func.id == "__import__":
                        if node.args and isinstance(node.args[0], ast.Constant) and str(node.args[0].value).startswith(forbidden):
                            violations.append((py_file.name, node.lineno, node.args[0].value))

        assert not violations, f"Forbidden upward imports found in core: {violations}"



class TestInvariant2_SymbolAuthority:
    """Invariant 2: All symbols declared in __all__ across core modules must be resolvable."""

    def test_all_symbols_resolvable(self):
        core_dir = REPO_ROOT / "aegis_core" if (REPO_ROOT / "aegis_core").exists() else REPO_ROOT / "aegis_core"
        pkg = "aegis_core" if (REPO_ROOT / "aegis_core").exists() else "soma_core"
        python_files = [f for f in core_dir.glob("*.py") if f.name != "__init__.py"]

        missing_symbols = []
        for py_file in python_files:
            module_name = f"{pkg}.{py_file.stem}"
            mod = importlib.import_module(module_name)
            assert hasattr(mod, "__all__"), f"{module_name} lacks __all__ declaration"
            exported = getattr(mod, "__all__", [])
            for sym in exported:
                if not hasattr(mod, sym):
                    missing_symbols.append((module_name, sym))

        assert not missing_symbols, f"Exported symbols missing from modules: {missing_symbols}"


class TestInvariant3_FailClosedConfinement:
    """Invariant 4: Path confinement rejects traversals, device names, and streams."""

    @pytest.mark.parametrize("bad_path", [
        "../outside.txt",
        "../../etc/passwd",
        "/etc/shadow",
        "foo/../../bar/../../baz",
        "COM1",
        "LPT2",
        "NUL",
        "CON",
        "CONIN$",
        "CONOUT$",
        "aux.txt",

        "safe.txt:hidden_stream",
        "file::$DATA",
    ])
    def test_confine_path_fails_closed(self, tmp_path, bad_path):
        with pytest.raises(ValueError):
            confine_path(bad_path, str(tmp_path))

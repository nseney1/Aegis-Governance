"""v3.0.0 Zero-Legacy Architectural Sentinel Tests.

Enforces via AST and regex scans across `aegis_core/`, `aegis_cli/`, `aegis_mcp/`,
`aegis_sdk/`, `rules/`, `skills/`, and `tests/` that:
1. Zero `soma_*` imports or `Soma*` class aliases exist, and legacy shims are deleted.
2. Zero biological rule type literals (`vacuole`, `chloroplast`, `plasmodesmata`)
   exist in production modules.
3. All `.aegis/rules/` files use pure Aegis prefixes and types.
4. All 20 MCP tools are registered strictly under the `aegis_*` namespace.
5. Every CLI command in `CommandRegistry` supports `OutputContext` (`--plain`,
   `NO_COLOR`, `--json`) without leaking ANSI escape sequences.
"""
from __future__ import annotations

import argparse
import ast
from pathlib import Path
import re

import pytest

from aegis_cli.cli import main as cli_main
from aegis_cli.registry import get_default_registry
from aegis_cli.ui.theme import OutputContext
from aegis_core.yaml_engine.frontmatter import parse_rule_frontmatter
from aegis_mcp.registry import TOOL_DEFINITIONS
from aegis_mcp.tools import _TOOL_HANDLERS

REPO_ROOT = Path(__file__).resolve().parents[3]
PROD_PACKAGES = ("aegis_core", "aegis_cli", "aegis_mcp", "aegis_sdk")
ALL_SCAN_DIRS = (*PROD_PACKAGES, "rules", "skills", "tests")
THIS_FILE = Path(__file__).resolve()


def _iter_python_files(dirs: tuple[str, ...]) -> list[Path]:
    files: list[Path] = []
    for d in dirs:
        root = REPO_ROOT / d
        if not root.exists():
            continue
        for p in sorted(root.rglob("*.py")):
            if "__pycache__" in p.parts or p.resolve() == THIS_FILE:
                continue
            files.append(p)
    return files


class TestV3ZeroLegacyImportsAndShims:
    """Verify zero soma_* imports, zero Soma* class aliases, and deleted shim files."""

    def test_soma_packages_raise_module_not_found(self) -> None:
        for pkg in ("soma_core", "soma_cli", "soma_sdk", "soma_mcp"):
            with pytest.raises(ModuleNotFoundError):
                __import__(pkg)

    def test_legacy_shim_files_deleted(self) -> None:
        deleted_paths = [
            REPO_ROOT / "aegis_core" / "compat.py",
            REPO_ROOT / "aegis_core" / "somayaml.py",
            REPO_ROOT / "aegis_sdk" / "cells.py",
            REPO_ROOT / "aegis_core" / "cell_inventory.py",
            REPO_ROOT / "aegis_mcp" / "cell_cache.py",
        ]
        existing = [str(p.relative_to(REPO_ROOT)) for p in deleted_paths if p.exists()]
        assert not existing, f"Legacy shim files must be deleted in v3.0.0: {existing}"

    def test_zero_soma_imports_across_repo(self) -> None:
        offenders: list[str] = []
        import_re = re.compile(r"^\s*(?:from|import)\s+soma_[a-zA-Z0-9_.]*")

        for path in _iter_python_files(ALL_SCAN_DIRS):
            rel = path.relative_to(REPO_ROOT)
            text = path.read_text(encoding="utf-8")
            for lineno, line in enumerate(text.splitlines(), start=1):
                if import_re.match(line):
                    offenders.append(f"{rel}:{lineno}: {line.strip()}")

            tree = ast.parse(text, filename=str(rel))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name.startswith("soma_"):
                            offenders.append(f"{rel}:{node.lineno}: import {alias.name}")
                elif isinstance(node, ast.ImportFrom):
                    if node.module and node.module.startswith("soma_"):
                        offenders.append(f"{rel}:{node.lineno}: from {node.module} import ...")

        assert not offenders, "Found prohibited soma_* imports:\n" + "\n".join(offenders)

    def test_zero_soma_class_definitions_or_aliases(self) -> None:
        offenders: list[str] = []
        for path in _iter_python_files(ALL_SCAN_DIRS):
            rel = path.relative_to(REPO_ROOT)
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(rel))
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef) and node.name.startswith("Soma"):
                    offenders.append(f"{rel}:{node.lineno}: class {node.name}")
                elif isinstance(node, ast.Assign):
                    for target in node.targets:
                        if isinstance(target, ast.Name) and target.id.startswith("Soma"):
                            offenders.append(f"{rel}:{node.lineno}: {target.id} = ...")

        assert not offenders, "Found prohibited Soma* class/alias definitions:\n" + "\n".join(offenders)


class TestV3ZeroBiologicalRuleTypes:
    """Verify zero biological rule type literals in production modules and .aegis/rules/."""

    def test_zero_biological_literals_in_production_modules(self) -> None:
        bio_re = re.compile(r"\b(vacuoles?|chloroplasts?|plasmodesmata)\b", re.IGNORECASE)
        offenders: list[str] = []
        for path in _iter_python_files(PROD_PACKAGES):
            rel = path.relative_to(REPO_ROOT)
            for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
                if bio_re.search(line):
                    offenders.append(f"{rel}:{lineno}: {line.strip()}")

        assert not offenders, (
            "Found biological rule type terms in production modules:\n" + "\n".join(offenders)
        )

    def test_repository_rules_use_pure_aegis_prefixes_and_types(self) -> None:
        rules_dir = REPO_ROOT / ".aegis" / "rules"
        valid_prefixes = ("invariant-", "boundary-", "trap-", "persona-", "contract-", "gate-")
        valid_types = {"invariant", "boundary", "trap", "persona", "contract", "gate"}
        offenders: list[str] = []

        for md_file in sorted(rules_dir.rglob("*.md")):
            if md_file.name == "README.md":
                continue
            rel = md_file.relative_to(REPO_ROOT)
            if not md_file.name.startswith(valid_prefixes):
                offenders.append(f"{rel}: filename does not start with {valid_prefixes}")
            meta, _ = parse_rule_frontmatter(str(md_file))
            rule_id = str(meta.get("id", ""))
            rule_type = str(meta.get("type", ""))
            if not rule_id.startswith(valid_prefixes):
                offenders.append(f"{rel}: frontmatter id '{rule_id}' invalid prefix")
            if rule_type not in valid_types:
                offenders.append(f"{rel}: frontmatter type '{rule_type}' not in {valid_types}")

        assert not offenders, "Repository rules violated pure Aegis naming:\n" + "\n".join(offenders)

    def test_mcp_tools_registered_strictly_under_aegis_namespace(self) -> None:
        tool_names = [t["name"] for t in TOOL_DEFINITIONS]
        assert len(tool_names) == 4
        assert all(name.startswith("aegis_") for name in tool_names), tool_names
        assert set(_TOOL_HANDLERS.keys()) == set(tool_names)


class TestV3CLIOutputContextAndANSIHygiene:
    """Verify every CLI command in CommandRegistry supports OutputContext without leaking ANSI."""

    def test_every_registered_command_supports_output_context(self, monkeypatch: pytest.MonkeyPatch) -> None:
        registry = get_default_registry()
        commands = list(registry._commands.values())
        assert len(commands) >= 9

        for cmd in commands:
            ns_plain = argparse.Namespace(plain=True, json=False)
            ui_plain = cmd.get_ui(ns_plain)
            assert isinstance(ui_plain, OutputContext)
            assert ui_plain.color_enabled is False
            assert ui_plain.emoji_enabled is False

            ns_json = argparse.Namespace(plain=False, json=True)
            ui_json = cmd.get_ui(ns_json)
            assert ui_json.json_mode is True
            assert ui_json.color_enabled is False
            assert ui_json.emoji_enabled is False

            monkeypatch.setenv("NO_COLOR", "1")
            ns_env = argparse.Namespace(plain=False, json=False)
            ui_env = cmd.get_ui(ns_env)
            assert ui_env.color_enabled is False
            monkeypatch.delenv("NO_COLOR", raising=False)

    @pytest.mark.parametrize(
        "argv",
        [
            ["status", "--plain"],
            ["doctor", "--plain"],
            ["doctor", "--json"],
            ["rule", "list", "--plain"],
            ["hook", "status", "--plain"],
        ],
    )
    def test_cli_commands_emit_zero_ansi_when_plain_or_no_color(
        self,
        argv: list[str],
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        monkeypatch.setenv("NO_COLOR", "1")
        cli_main(argv)
        captured = capsys.readouterr()
        # A removed command prints only a pointer, which would pass vacuously.
        assert captured.out.strip(), f"{argv} printed nothing on stdout: {captured.err!r}"
        assert "\x1b[" not in captured.out, f"ANSI escape leaked to stdout for {argv}: {captured.out!r}"
        assert "\x1b[" not in captured.err, f"ANSI escape leaked to stderr for {argv}: {captured.err!r}"

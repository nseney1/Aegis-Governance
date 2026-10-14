"""Tests for soma init zero-touch polyglot AST driver provisioning."""
import argparse
from pathlib import Path
import pytest

from aegis_cli.init import run_init
from aegis_core.skills.slots import SlotRegistry
from aegis_core.workspace import Workspace


def test_init_provisions_rust_ast_driver(tmp_path: Path, monkeypatch):
    # Setup simulated Rust project
    (tmp_path / "Cargo.toml").write_text("[package]\nname = 'rust_app'\n", encoding="utf-8")
    src = tmp_path / "src"
    src.mkdir()
    (src / "main.rs").write_text("fn main() {}\n", encoding="utf-8")
    (tmp_path / ".git").mkdir()

    # Stub input to auto-accept
    monkeypatch.setattr("builtins.input", lambda _: "y")

    args = argparse.Namespace(
        ws=Workspace.for_init(tmp_path),
        _project_root=tmp_path,
        dry_run=False,
        platform="gemini",
        rules="minimal",
        mcp=False,
        yes=True,
        force=True,
    )

    exit_code = run_init(args)
    assert exit_code == 0

    # Verify .soma/slots.yaml was auto-provisioned
    slots_path = tmp_path / ".soma" / "slots.yaml"
    assert slots_path.is_file()

    registry = SlotRegistry.load(tmp_path)
    rs_driver = registry.get_ast_driver(".rs")
    assert rs_driver is not None
    assert "rust_ast.py" in rs_driver

    # Verify driver file staged in .soma/drivers/
    driver_staged = tmp_path / ".soma" / "drivers" / "rust_ast.py"
    assert driver_staged.is_file()


def test_init_provisions_polyglot_ts_go_drivers(tmp_path: Path, monkeypatch):
    # Setup simulated mixed Go + TypeScript project
    (tmp_path / "go.mod").write_text("module example.com/app\n", encoding="utf-8")
    (tmp_path / "package.json").write_text('{"name": "frontend"}', encoding="utf-8")
    (tmp_path / "tsconfig.json").write_text("{}", encoding="utf-8")
    (tmp_path / ".git").mkdir()

    monkeypatch.setattr("builtins.input", lambda _: "y")

    args = argparse.Namespace(
        ws=Workspace.for_init(tmp_path),
        _project_root=tmp_path,
        dry_run=False,
        platform="gemini",
        rules="minimal",
        mcp=False,
        yes=True,
        force=True,
    )

    exit_code = run_init(args)
    assert exit_code == 0

    registry = SlotRegistry.load(tmp_path)
    assert registry.get_ast_driver(".ts") is not None
    assert registry.get_ast_driver(".go") is not None
    assert (tmp_path / ".soma" / "drivers" / "ts_ast.js").is_file()
    assert (tmp_path / ".soma" / "drivers" / "go_ast.go").is_file()

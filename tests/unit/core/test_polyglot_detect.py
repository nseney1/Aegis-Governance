"""Tests for polyglot language detection and zero-touch AST driver provisioning."""
import json
from pathlib import Path
import pytest

from aegis_core.ast.detect import (
    detect_project_languages,
    resolve_recommended_drivers,
    provision_ast_driver_slots,
)
from aegis_core.skills.slots import SlotRegistry


def test_detect_project_languages_python(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname='foo'\n", encoding="utf-8")
    (tmp_path / "app.py").write_text("print('hello')\n", encoding="utf-8")

    detected = detect_project_languages(tmp_path)
    assert "python" in detected
    assert detected["python"]["manifests"] == ["pyproject.toml"]
    assert ".py" in detected["python"]["extensions"]


def test_detect_project_languages_rust(tmp_path: Path):
    (tmp_path / "Cargo.toml").write_text("[package]\nname='foo'\n", encoding="utf-8")
    src = tmp_path / "src"
    src.mkdir()
    (src / "main.rs").write_text("fn main() {}\n", encoding="utf-8")

    detected = detect_project_languages(tmp_path)
    assert "rust" in detected
    assert detected["rust"]["manifests"] == ["Cargo.toml"]
    assert ".rs" in detected["rust"]["extensions"]


def test_detect_project_languages_typescript_and_javascript(tmp_path: Path):
    (tmp_path / "package.json").write_text('{"name": "foo"}', encoding="utf-8")
    (tmp_path / "tsconfig.json").write_text("{}", encoding="utf-8")
    (tmp_path / "index.ts").write_text("const x: number = 1;", encoding="utf-8")

    detected = detect_project_languages(tmp_path)
    assert "typescript" in detected
    assert ".ts" in detected["typescript"]["extensions"]


def test_detect_project_languages_go(tmp_path: Path):
    (tmp_path / "go.mod").write_text("module example.com/foo\n\ngo 1.21\n", encoding="utf-8")
    (tmp_path / "main.go").write_text("package main\nfunc main() {}\n", encoding="utf-8")

    detected = detect_project_languages(tmp_path)
    assert "go" in detected
    assert detected["go"]["manifests"] == ["go.mod"]
    assert ".go" in detected["go"]["extensions"]


def test_detect_polyglot_repository(tmp_path: Path):
    # Mixed Rust backend + TypeScript frontend
    (tmp_path / "Cargo.toml").write_text("[package]\nname='core'\n", encoding="utf-8")
    (tmp_path / "package.json").write_text('{"name": "frontend"}', encoding="utf-8")
    (tmp_path / "tsconfig.json").write_text("{}", encoding="utf-8")

    detected = detect_project_languages(tmp_path)
    assert "rust" in detected
    assert "typescript" in detected


def test_resolve_recommended_drivers():
    languages = {
        "rust": {"extensions": [".rs"]},
        "typescript": {"extensions": [".ts", ".tsx"]},
        "go": {"extensions": [".go"]},
        "python": {"extensions": [".py"]},
    }
    drivers = resolve_recommended_drivers(languages)
    # Python is handled in-process; no external slot needed
    assert "ast_driver_py" not in drivers
    # Other languages have recommended slot commands
    assert "ast_driver_rs" in drivers
    assert "ast_driver_ts" in drivers
    assert "ast_driver_go" in drivers


def test_provision_ast_driver_slots(tmp_path: Path):
    (tmp_path / "Cargo.toml").write_text("[package]\nname='foo'\n", encoding="utf-8")
    (tmp_path / "package.json").write_text('{"name": "web"}', encoding="utf-8")
    (tmp_path / "tsconfig.json").write_text("{}", encoding="utf-8")

    slots, created_files = provision_ast_driver_slots(tmp_path)
    assert {"ast_driver_rs", "ast_driver_ts", "ast_driver_js"} <= set(slots)

    # The opt-ins live in .aegis/config.json and SlotRegistry reads them back
    config = tmp_path / ".aegis" / "config.json"
    assert created_files == [str(config)]
    registry = SlotRegistry.load(tmp_path)
    assert registry.get_ast_driver(".rs") is not None
    assert registry.get_ast_driver(".ts") is not None
    # Nothing is staged in the repository: the packaged templates are what runs
    assert not (tmp_path / ".aegis" / "drivers").exists()


def test_provision_keeps_existing_config_keys(tmp_path: Path):
    (tmp_path / "Cargo.toml").write_text("[package]\nname='foo'\n", encoding="utf-8")
    config = tmp_path / ".aegis" / "config.json"
    config.parent.mkdir(parents=True)
    config.write_text(json.dumps({"v": 1, "hosts": ["codex-cli"], "jit": {"max_tokens": 900}}), encoding="utf-8")

    provision_ast_driver_slots(tmp_path)

    assert json.loads(config.read_text(encoding="utf-8")) == {
        "v": 1, "hosts": ["codex-cli"], "jit": {"max_tokens": 900}, "ast": {"packaged_drivers": ["rs"]},
    }
    assert SlotRegistry.load(tmp_path).get_ast_driver(".rs") == "{python} .aegis/drivers/rust_ast.py"


def test_provision_does_not_overwrite_unparseable_config(tmp_path: Path):
    (tmp_path / "Cargo.toml").write_text("[package]\nname='foo'\n", encoding="utf-8")
    config = tmp_path / ".aegis" / "config.json"
    config.parent.mkdir(parents=True)
    config.write_text("{hand-edited, not yet valid\n", encoding="utf-8")

    _, created_files = provision_ast_driver_slots(tmp_path)

    assert config.read_text(encoding="utf-8") == "{hand-edited, not yet valid\n"
    assert created_files == []


def test_provision_dry_run_writes_nothing(tmp_path: Path):
    (tmp_path / "go.mod").write_text("module x\n", encoding="utf-8")

    slots, created_files = provision_ast_driver_slots(tmp_path, dry_run=True)

    assert slots == {"ast_driver_go": "go run .aegis/drivers/go_ast.go"}
    assert created_files == []
    assert not (tmp_path / ".aegis").exists()

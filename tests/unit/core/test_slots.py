"""Unit tests for SlotRegistry in aegis_core.skills.slots."""
from __future__ import annotations

from pathlib import Path
import pytest

from aegis_core.skills.slots import (
    SlotRegistry,
    SlotResolutionError,
    SLOT_REF_PATTERN,
)


def test_slot_registry_init_and_get():
    reg = SlotRegistry({"key1": "val1", "key2": None})
    assert reg.get("key1") == "val1"
    assert reg.get("key2") is None
    assert reg.get("missing", "default") == "default"
    assert reg.to_dict() == {"key1": "val1"}


def test_slot_registry_load_nonexistent(tmp_path):
    reg = SlotRegistry.load(tmp_path)
    assert reg.to_dict() == {}


def test_slot_registry_load_valid(tmp_path):
    soma_dir = tmp_path / ".soma"
    soma_dir.mkdir()
    (soma_dir / "slots.yaml").write_text("slots:\n  tool: /usr/bin/tool\n", encoding="utf-8")

    reg = SlotRegistry.load(tmp_path)
    assert reg.get("tool") == "/usr/bin/tool"


def test_slot_registry_load_invalid_yaml(tmp_path):
    soma_dir = tmp_path / ".soma"
    soma_dir.mkdir()
    # Bad yaml syntax
    (soma_dir / "slots.yaml").write_text(": : invalid", encoding="utf-8")

    with pytest.raises(SlotResolutionError, match="Failed to parse"):
        SlotRegistry.load(tmp_path)


def test_slot_registry_load_non_mapping_slots(tmp_path):
    soma_dir = tmp_path / ".soma"
    soma_dir.mkdir()
    (soma_dir / "slots.yaml").write_text("slots: 'not a dict'\n", encoding="utf-8")

    reg = SlotRegistry.load(tmp_path)
    assert reg.to_dict() == {}


def test_slot_registry_resolve_strict():
    reg = SlotRegistry({"compiler": "rustc"})
    # Valid interpolation
    assert reg.resolve("Run ${compiler} --version") == "Run rustc --version"
    assert reg.resolve("Run ${SLOT.compiler} --version") == "Run rustc --version"

    # Missing slot in strict mode raises error
    with pytest.raises(SlotResolutionError, match="Unresolved required slot: 'linker'"):
        reg.resolve("Run ${linker}", strict=True)

    # Missing slot in non-strict mode preserves reference
    assert reg.resolve("Run ${linker}", strict=False) == "Run ${linker}"


def test_slot_registry_get_ast_driver():
    reg = SlotRegistry({
        "ast_driver": "default_driver",
        "ast_driver_rs": "cargo_driver",
    })
    # Python is always None
    assert reg.get_ast_driver("py") is None
    assert reg.get_ast_driver(".py") is None

    # Specific extension resolves ast_driver_<ext>
    assert reg.get_ast_driver("rs") == "cargo_driver"
    assert reg.get_ast_driver(".rs") == "cargo_driver"

    # Fallback to ast_driver
    assert reg.get_ast_driver("ts") == "default_driver"


def test_slot_registry_get_configured_extensions():
    # Empty registry always includes .py
    empty_reg = SlotRegistry({})
    assert empty_reg.get_configured_extensions() == {".py"}

    # Configured slots add extensions
    reg = SlotRegistry({
        "ast_driver_rs": "python3 rust.py",
        "ast_driver_.go": "go run go.go",
        "ast_driver_ts": "node ts.js",
        "unrelated_slot": "some_value",
    })
    exts = reg.get_configured_extensions()
    assert exts == {".py", ".rs", ".go", ".ts"}

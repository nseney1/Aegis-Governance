"""Skill graph discovery and the ${SLOT.*} registry used by aegis_scan.

The swarm handoff router and its typed artifacts were removed in v4. The file
keeps its name because the Layer-1 runner maps aegis_core/skills/* to it.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from aegis_core.skills.slots import SlotRegistry, SlotResolutionError


class TestSlotRegistry:
    """Test fail-closed slot resolution."""

    def test_slot_resolution_success(self):
        reg = SlotRegistry({"test_command": "pytest tests/", "linter": "ruff check"})
        resolved = reg.resolve("Run: ${SLOT.test_command} && ${SLOT.linter}")
        assert resolved == "Run: pytest tests/ && ruff check"

    def test_slot_resolution_fail_closed(self):
        reg = SlotRegistry({"test_command": "pytest"})
        with pytest.raises(SlotResolutionError, match="Unresolved required slot: 'missing_slot'"):
            reg.resolve("Run: ${SLOT.missing_slot}", strict=True)

    def test_slot_loading_from_workspace(self, tmp_path: Path):
        soma_dir = tmp_path / ".aegis"
        soma_dir.mkdir(parents=True)
        (soma_dir / "slots.yaml").write_text(
            "---\nslots:\n  test_command: 'cargo test'\n  build_command: 'cargo build'\n---\n",
            encoding="utf-8",
        )
        reg = SlotRegistry.load(tmp_path)
        assert reg.get("test_command") == "cargo test"
        assert reg.get("build_command") == "cargo build"
        assert reg.get("missing") is None


class TestSlotRegistryBranches:

    def test_slot_registry_branches(self, tmp_path: Path):
        # Nonexistent file returns empty
        reg = SlotRegistry.load(tmp_path)
        assert reg.to_dict() == {}

        # Invalid yaml syntax raises SlotResolutionError
        soma_dir = tmp_path / ".aegis"
        soma_dir.mkdir(parents=True, exist_ok=True)
        (soma_dir / "slots.yaml").write_text("a: [unclosed", encoding="utf-8")
        with pytest.raises(SlotResolutionError, match="Failed to parse"):
            SlotRegistry.load(tmp_path)

        # slots not a mapping
        (soma_dir / "slots.yaml").write_text("---\nslots: 'not-a-map'\n---\n", encoding="utf-8")
        assert SlotRegistry.load(tmp_path).to_dict() == {}

        # resolve with strict=False returns token
        reg2 = SlotRegistry({"existing": "val"})
        assert reg2.resolve("Hello ${existing} and ${missing}", strict=False) == "Hello val and ${missing}"
        assert reg2.to_dict() == {"existing": "val"}

        # resolve default strict=True raises SlotResolutionError when slot is missing
        with pytest.raises(SlotResolutionError, match="Unresolved required slot: 'missing'"):
            reg2.resolve("Hello ${missing}")

    def test_get_ast_driver_branch_coverage_and_mutant_kills(self):
        from aegis_core.skills.slots import SlotRegistry
        reg = SlotRegistry({
            "ast_driver_ts": "node install/drivers/ts_ast.js",
            "ast_driver": "default-runner",
        })
        # .py returns None
        assert reg.get_ast_driver("py") is None
        assert reg.get_ast_driver(".py") is None
        assert reg.get_ast_driver("PY") is None

        # specific extension
        assert reg.get_ast_driver("ts") == "node install/drivers/ts_ast.js"
        assert reg.get_ast_driver(".ts") == "node install/drivers/ts_ast.js"

        # fallback to default ast_driver
        assert reg.get_ast_driver("go") == "default-runner"
        assert reg.get_ast_driver(".go") == "default-runner"

        # empty registry
        empty_reg = SlotRegistry()
        assert empty_reg.get_ast_driver("ts") is None
        assert empty_reg.get_ast_driver("py") is None

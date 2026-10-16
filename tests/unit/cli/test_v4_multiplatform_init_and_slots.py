"""Unit tests for v4.0.0 Wave 1 Lane B:
- Cross-model SlotRegistry.for_platform() and slot resolution
- aegis init scaffolds .aegis/rules/<type>/, seeds only rules the loader accepts and
  writes no manifest (D3)
"""
from __future__ import annotations

import argparse
from pathlib import Path

from aegis_cli.init import run_init
from aegis_core.rules import load_rules
from aegis_core.skills.slots import (
    DEFAULT_SLOTS,
    PLATFORM_SLOT_PROFILES,
    SlotRegistry,
)


class TestCrossModelSlotRegistry:
    """Verify SlotRegistry.for_platform and slot resolution across AI platforms."""

    def test_platform_slot_profiles_and_defaults(self):
        for platform in (
            "gemini",
            "antigravity",
            "claude",
            "claude-code",
            "claude-ai",
            "claude-desktop",
            "cursor",
            "copilot",
            "kiro",
            "generic",
        ):
            assert platform in PLATFORM_SLOT_PROFILES

        for key in (
            "TEST_RUNNER",
            "LINTER",
            "FORMATTER",
            "TYPE_CHECKER",
            "BUILD_TOOL",
            "TOOL_READ",
            "TOOL_EDIT",
            "TOOL_WRITE",
            "TOOL_SEARCH",
            "TOOL_RUN",
            "TOOL_SUBAGENT",
            "MODEL_FAST",
            "MODEL_STANDARD",
            "MODEL_HEAVY",
        ):
            assert key in DEFAULT_SLOTS

    def test_for_platform_gemini_claude_cursor_resolution(self):
        template = (
            "Read=${SLOT.TOOL_READ} Edit=${SLOT.TOOL_EDIT} "
            "Subagent=${SLOT.TOOL_SUBAGENT} Fast=${SLOT.MODEL_FAST} "
            "Std=${SLOT.MODEL_STANDARD} Heavy=${SLOT.MODEL_HEAVY}"
        )

        gemini_reg = SlotRegistry.for_platform("gemini")
        assert gemini_reg.resolve(template) == (
            "Read=view_file Edit=replace_file_content "
            "Subagent=invoke_subagent Fast=flash "
            "Std=inherit Heavy=pro"
        )

        claude_reg = SlotRegistry.for_platform("claude")
        assert claude_reg.resolve(template) == (
            "Read=Read Edit=Edit "
            "Subagent=Task Fast=haiku "
            "Std=sonnet Heavy=opus"
        )

        cursor_reg = SlotRegistry.for_platform("cursor")
        assert cursor_reg.resolve(template) == (
            "Read=read_file Edit=edit_file "
            "Subagent=subagent Fast=fast-tier "
            "Std=standard-tier Heavy=heavy-tier"
        )

        # Normalized aliases
        assert SlotRegistry.for_platform("claude-code").get("TOOL_SUBAGENT") == "Task"
        assert SlotRegistry.for_platform("antigravity").get("TOOL_SUBAGENT") == "invoke_subagent"

    def test_user_config_sets_slots_but_the_repo_config_cannot(self, tmp_path: Path, monkeypatch):
        # H5/D10: the repo-writable config.json cannot set any slot; ~/.aegis/config.json
        # may set repo-style slots (TEST_RUNNER) and valid TOOL_*/MODEL_* names.
        home = tmp_path / "home"
        (home / ".aegis").mkdir(parents=True)
        (home / ".aegis" / "config.json").write_text(
            '{"v": 1, "slots": {"TEST_RUNNER": "cargo test"}}', encoding="utf-8"
        )
        monkeypatch.setenv("HOME", str(home))
        monkeypatch.setenv("USERPROFILE", str(home))
        ws = tmp_path / "ws"
        (ws / ".aegis").mkdir(parents=True)
        (ws / ".aegis" / "config.json").write_text(
            '{"v": 1, "slots": {"MODEL_FAST": "custom-haiku-override", "TEST_RUNNER": "make evil"}}',
            encoding="utf-8",
        )

        reg = SlotRegistry.for_platform("claude", workspace=ws)
        assert reg.get("MODEL_FAST") == "haiku"
        assert reg.get("TEST_RUNNER") == "cargo test"
        assert reg.get("TOOL_READ") == "Read"

        text = "Use ${SLOT.TOOL_READ} with ${SLOT.MODEL_FAST} via ${SLOT.TEST_RUNNER} and ${SLOT.UNKNOWN_KEEP}"
        resolved = SlotRegistry.for_platform("claude", workspace=ws).sanitized().resolve(text, strict=False)
        assert resolved == "Use Read with haiku via cargo test and ${SLOT.UNKNOWN_KEEP}"


class TestInitWorkspaceRules:
    """aegis init gives the workspace the D12 rules layout and nothing a scan cannot serve."""

    def test_init_scaffolds_type_dirs_and_seeds_only_loadable_rules_without_a_manifest(self, tmp_path: Path):
        project_root = tmp_path / "citadel_repo"
        project_root.mkdir()

        args = argparse.Namespace(
            dry_run=False,
            yes=True,
            force=False,
            rules="standard",
            no_hooks=True,
            _project_root=project_root,
        )
        rc = run_init(args)
        assert rc == 0

        ws_rules = project_root / ".aegis" / "rules"
        assert sorted(p.name for p in ws_rules.iterdir()) == ["gates", "invariants", "personas", "traps"]
        assert not (ws_rules / "manifest.json").exists()
        assert not (project_root / ".aegis" / "keys").exists()
        # The seeded starter rules load cleanly; nothing under .aegis/rules is ignored.
        ruleset = load_rules(project_root)
        assert ruleset.errors == () and ruleset.ignored == ()
        assert {r.type for r in ruleset.rules} == {"persona"}

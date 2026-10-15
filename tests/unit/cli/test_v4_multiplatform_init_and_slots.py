"""Unit tests for v4.0.0 Wave 1 Lane B:
- Cross-model SlotRegistry.for_platform() and resolve_text_for_platform()
- Multi-platform detect_platforms() and portable MCP configuration
- Workspace SSOT rule seeding + manifest signing in aegis init
- Extracted formatters (sarif, release_gate) and lifecycle cleanse module
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from aegis_cli.formatters import format_sarif_report, verify_release_gate
from aegis_cli.init import generate_mcp_config, run_init, seed_workspace_rules
from aegis_cli.platforms import McpAdapter, detect_platform, detect_platforms
from aegis_core.lifecycle.cleanse import (
    AEGIS_INTERNAL_PURGE_STEMS,
    UNIVERSAL_TENETS,
    clean_global_rules,
    is_purge_candidate,
)
from aegis_core.rule_inventory import inventory_rules
from aegis_core.skills.slots import (
    DEFAULT_SLOTS,
    PLATFORM_SLOT_PROFILES,
    SlotRegistry,
    resolve_text_for_platform,
)
from aegis_mcp.rule_cache import RuleCache


class TestCrossModelSlotRegistry:
    """Verify SlotRegistry.for_platform and resolve_text_for_platform across AI platforms."""

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

    def test_workspace_overrides_repo_slots_but_not_platform_slots(self, tmp_path: Path):
        # H5: repo-writable slots.yaml may set repo slots (TEST_RUNNER) but not the
        # host's TOOL_*/MODEL_* capability slots.
        aegis_dir = tmp_path / ".aegis"
        aegis_dir.mkdir()
        (aegis_dir / "slots.yaml").write_text(
            "slots:\n  MODEL_FAST: custom-haiku-override\n  TEST_RUNNER: cargo test\n",
            encoding="utf-8",
        )

        reg = SlotRegistry.for_platform("claude", workspace=tmp_path)
        assert reg.get("MODEL_FAST") == "haiku"
        assert reg.get("TEST_RUNNER") == "cargo test"
        assert reg.get("TOOL_READ") == "Read"

        text = "Use ${SLOT.TOOL_READ} with ${SLOT.MODEL_FAST} via ${SLOT.TEST_RUNNER} and ${SLOT.UNKNOWN_KEEP}"
        resolved = resolve_text_for_platform(text, "claude", workspace=tmp_path)
        assert resolved == "Use Read with haiku via cargo test and ${SLOT.UNKNOWN_KEEP}"


class TestMultiPlatformDetectionAndPortableMcp:
    """Verify detect_platforms() and portable MCP configuration."""

    def test_detect_platforms_multiple_and_ordering(self, tmp_path: Path):
        # Empty defaults to ['gemini'] while single-platform detect_platform returns 'unknown'
        assert detect_platforms(tmp_path) == ["gemini"]
        assert detect_platform(tmp_path) == "unknown"

        # Create both .gemini and .claude
        (tmp_path / ".claude").mkdir()
        (tmp_path / ".gemini").mkdir()
        detected = detect_platforms(tmp_path)
        assert detected == ["gemini", "claude"]
        assert detect_platform(tmp_path) == "gemini"

        # Add home markers for cursor and kiro
        fake_home = tmp_path / "home"
        (fake_home / ".cursor").mkdir(parents=True)
        (fake_home / ".kiro").mkdir(parents=True)
        assert detect_platforms(tmp_path, home=fake_home) == [
            "gemini",
            "claude",
            "cursor",
            "kiro",
        ]

    def test_generate_mcp_config_portable_vs_legacy(self, tmp_path: Path):
        generate_mcp_config(tmp_path, portable=True)
        mcp_file = tmp_path / ".mcp.json"
        assert mcp_file.is_file()
        data = json.loads(mcp_file.read_text(encoding="utf-8"))
        assert data == {
            "mcpServers": {
                "aegis": {
                    "command": "aegis-mcp",
                    "args": [],
                }
            }
        }
        assert str(tmp_path) not in mcp_file.read_text(encoding="utf-8")

    def test_mcp_adapter_portable_install(self, tmp_path: Path):
        adapter = McpAdapter(workspace=tmp_path)
        res = adapter.install(tmp_path, portable=True)
        assert res.success
        data = json.loads((tmp_path / ".mcp.json").read_text(encoding="utf-8"))
        assert data == {
            "mcpServers": {
                "aegis": {
                    "command": "aegis-mcp",
                    "args": [],
                }
            }
        }
        assert adapter.verify(local=True)


class TestInitSeedsWorkspaceRulesSSOT:
    """Verify aegis init always seeds <workspace>/.aegis/rules/ and manifest.json."""

    def test_init_seeds_workspace_rules_and_manifest_on_fresh_repo(self, tmp_path: Path):
        project_root = tmp_path / "citadel_repo"
        project_root.mkdir()
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        (project_root / ".gemini").mkdir()

        args = argparse.Namespace(
            dry_run=False,
            platform="gemini",
            yes=True,
            force=False,
            rules="standard",
            mcp=True,
            portable=True,
            no_hooks=True,
            _project_root=project_root,
            _home=fake_home,
        )
        rc = run_init(args)
        assert rc == 0

        ws_rules = project_root / ".aegis" / "rules"
        assert ws_rules.is_dir()
        assert (ws_rules / "manifest.json").is_file()

        inv = inventory_rules(str(project_root))
        assert len(inv.entries) >= 5

        cached_rules = RuleCache().get_rules(str(project_root))
        assert len(cached_rules) >= 5
        rule_ids = {r.get("id") or r.get("_name") for r in cached_rules}
        assert "providence" in rule_ids
        assert "destructive-ops" in rule_ids


class TestExtractedFormattersAndCleanseReExports:
    """Verify extracted formatters and cleanse helpers remain importable from verify.py and rule.py."""

    def test_verify_and_rule_reexports(self):
        from aegis_cli import rule as rule_mod
        from aegis_cli import verify as verify_mod

        assert verify_mod.format_sarif_report is format_sarif_report
        assert verify_mod.verify_release_gate is verify_release_gate
        assert rule_mod.clean_global_rules is clean_global_rules
        assert rule_mod.is_purge_candidate is is_purge_candidate
        assert rule_mod.UNIVERSAL_TENETS is UNIVERSAL_TENETS
        assert rule_mod.AEGIS_INTERNAL_PURGE_STEMS is AEGIS_INTERNAL_PURGE_STEMS

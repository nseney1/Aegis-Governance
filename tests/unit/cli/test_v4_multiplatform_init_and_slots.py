"""Unit tests for v4.0.0 Wave 1 Lane B:
- Cross-model SlotRegistry.for_platform() and slot resolution
- Multi-platform detect_platforms() and portable MCP configuration
- aegis init scaffolds .aegis/rules/<type>/ without copying host rules into it or
  writing a manifest (D3)
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from aegis_cli.init import generate_mcp_config, run_init
from aegis_cli.platforms import McpAdapter, detect_platform, detect_platforms
from aegis_core.rules import load_rules
from aegis_core.skills.slots import (
    DEFAULT_SLOTS,
    PLATFORM_SLOT_PROFILES,
    SlotRegistry,
)


class TestCrossModelSlotRegistry:
    """Verify SlotRegistry.for_platform and slot resolution across AI platforms."""

    def test_platform_slot_profiles_and_defaults(self):
        # Keyed by host slot_profile id (D16); v3 platform names are not profiles.
        assert set(PLATFORM_SLOT_PROFILES) == {"codex-cli", "claude-code", "antigravity", "gemini-cli", "generic"}

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

    def test_detect_platforms_reads_home_markers_under_path_home(self, tmp_path: Path, monkeypatch):
        # Path.home() is USERPROFILE on Windows; a different HOME must not be scanned instead.
        profile = tmp_path / "profile"
        (profile / ".kiro").mkdir(parents=True)
        (tmp_path / "elsewhere" / ".cursor").mkdir(parents=True)
        cwd = tmp_path / "cwd"
        cwd.mkdir()
        monkeypatch.chdir(cwd)
        monkeypatch.setattr("pathlib.Path.home", lambda: profile)
        monkeypatch.setenv("HOME", str(tmp_path / "elsewhere"))

        assert detect_platforms() == ["kiro"]

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


class TestInitWorkspaceRules:
    """aegis init gives the workspace the D12 rules layout and nothing a scan cannot serve."""

    def test_init_scaffolds_type_dirs_without_seeding_host_rules_or_a_manifest(self, tmp_path: Path):
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
        assert sorted(p.name for p in ws_rules.iterdir()) == ["gates", "invariants", "traps"]
        assert not (ws_rules / "manifest.json").exists()
        assert not (project_root / ".aegis" / "keys").exists()
        # The host instruction rules went to the host; none of them is a workspace rule.
        ruleset = load_rules(project_root)
        assert (ruleset.rules, ruleset.ignored) == ((), ())

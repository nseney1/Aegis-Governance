"""Unit tests for platform adapters (Gemini hooks and base MCP config)."""
from __future__ import annotations

from pathlib import Path

from aegis_cli.platforms import GeminiAdapter, get_adapter


def _hook_commands(cfg):
    for event_map in cfg.values():
        for entries in event_map.values():
            for entry in entries:
                for hook in entry.get("hooks", [entry]):
                    yield hook["command"]


def test_gemini_adapter_hooks_only_call_live_aegis_commands(tmp_path: Path) -> None:
    """A hooks.json written today must not call a hook phase v4 removed (D15)."""
    import shlex

    from aegis_cli.cli import _build_parser, removed_command_pointer

    adapter = GeminiAdapter(workspace=tmp_path, home=tmp_path)
    commands = list(_hook_commands(adapter.render_config()))
    assert commands == ["aegis hook safety-gate"]
    for command in commands:
        argv = shlex.split(command)[1:]
        assert removed_command_pointer(argv) is None
        ns = _build_parser().parse_args(argv)
        assert (ns.command, ns.hook_action) == ("hook", "safety-gate")


def test_base_adapter_render_mcp_entry_defaults_to_aegis_mcp(tmp_path: Path) -> None:
    adapter = get_adapter("gemini", workspace=tmp_path)
    entry_global = adapter.render_mcp_entry(local=False)
    assert entry_global["command"] == "aegis-mcp"
    assert "env" not in entry_global

    entry_local = adapter.render_mcp_entry(local=True)
    assert entry_local["command"] == "aegis-mcp"
    assert entry_local["env"] == {"AEGIS_WORKSPACE": str(tmp_path)}

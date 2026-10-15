"""Unit tests for platform adapters (Gemini hooks and base MCP config)."""
from __future__ import annotations

from pathlib import Path

from aegis_cli.platforms import GeminiAdapter, get_adapter


def test_gemini_adapter_render_config_uses_aegis_hooks(tmp_path: Path) -> None:
    adapter = GeminiAdapter(workspace=tmp_path, home=tmp_path)
    cfg = adapter.render_config()

    pre_inv = cfg["governance-monitor"]["PreInvocation"][0]["command"]
    safety = cfg["safety-gate"]["PreToolUse"][0]["hooks"][0]["command"]
    stop = cfg["session-close"]["Stop"][0]["command"]

    assert pre_inv == "aegis hook pre-invocation"
    assert safety == "aegis hook safety-gate"
    assert stop == "aegis hook session-close"


def test_base_adapter_render_mcp_entry_defaults_to_aegis_mcp(tmp_path: Path) -> None:
    adapter = get_adapter("gemini", workspace=tmp_path)
    entry_global = adapter.render_mcp_entry(local=False)
    assert entry_global["command"] == "aegis-mcp"
    assert "env" not in entry_global

    entry_local = adapter.render_mcp_entry(local=True)
    assert entry_local["command"] == "aegis-mcp"
    assert entry_local["env"] == {"AEGIS_WORKSPACE": str(tmp_path)}

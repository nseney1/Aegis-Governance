"""Platform adapters for cross-platform installation and configuration."""
from __future__ import annotations

from typing import Type

from aegis_cli.platforms.base import (
    PlatformAdapter,
    PlatformInstallResult,
    detect_platform,
    detect_platforms,
    get_rules_dir,
)
from aegis_cli.platforms.claude import ClaudeAdapter
from aegis_cli.platforms.copilot import CopilotAdapter
from aegis_cli.platforms.gemini import GeminiAdapter, GeminiPlatformAdapter
from aegis_cli.platforms.kiro import KiroAdapter
from aegis_cli.platforms.mcp import McpAdapter

_ADAPTERS: dict[str, Type[PlatformAdapter]] = {
    "gemini": GeminiAdapter,
    "claude": ClaudeAdapter,
    "kiro": KiroAdapter,
    "copilot": CopilotAdapter,
    "mcp": McpAdapter,
}


def get_adapter(name: str, **kwargs) -> PlatformAdapter:
    """Retrieve an initialized PlatformAdapter instance by name."""
    normalized = name.lower().strip()
    cls = _ADAPTERS.get(normalized)
    if not cls:
        raise ValueError(f"Unknown platform '{name}'. Expected one of: {list(_ADAPTERS.keys())}")
    return cls(**kwargs)


def register_adapter(name: str, adapter_cls: Type[PlatformAdapter]) -> None:
    """Register or override a platform adapter."""
    _ADAPTERS[name.lower().strip()] = adapter_cls


__all__ = [
    "PlatformAdapter",
    "PlatformInstallResult",
    "GeminiAdapter",
    "GeminiPlatformAdapter",
    "ClaudeAdapter",
    "KiroAdapter",
    "CopilotAdapter",
    "McpAdapter",
    "get_adapter",
    "register_adapter",
    "detect_platform",
    "detect_platforms",
    "get_rules_dir",
]



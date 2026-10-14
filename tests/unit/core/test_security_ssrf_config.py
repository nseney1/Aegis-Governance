"""Behavioral tests for BUG-073: Host API Key Exfiltration & SSRF via Workspace Config.

Workspace configuration (.soma/soma.conf) must NEVER be permitted to configure
external network endpoints (e.g. OPENAI_BASE_URL, BASE_URL) because doing so
allows untrusted repositories to exfiltrate host developer credentials (such as
host environment or keyring API keys) to an attacker-controlled HTTP server.
"""
import os
from pathlib import Path
from unittest.mock import patch
import pytest

from aegis_core.inference_provider import resolve_key, resolve_provider, OpenAIProvider


def test_workspace_conf_cannot_override_base_url(tmp_path: Path):
    """Untrusted workspace soma.conf must NOT supply OPENAI_BASE_URL."""
    soma_dir = tmp_path / ".soma"
    soma_dir.mkdir(parents=True)
    conf_file = soma_dir / "soma.conf"
    conf_file.write_text("OPENAI_BASE_URL=https://evil.attacker.com/v1\n", encoding="utf-8")

    # When querying with workspace set, OPENAI_BASE_URL must NOT be resolved from workspace config
    resolved = resolve_key(str(tmp_path), ["OPENAI_BASE_URL"])
    assert resolved != "https://evil.attacker.com/v1", (
        "Security violation: OPENAI_BASE_URL was loaded from workspace config! Potential SSRF / credential leak."
    )
    assert resolved is None


def test_env_var_base_url_still_allowed(monkeypatch):
    """Environment variables set by the operator are authoritative and permitted."""
    monkeypatch.setenv("OPENAI_BASE_URL", "https://trusted-internal-proxy.local/v1")
    resolved = resolve_key(None, ["OPENAI_BASE_URL"])
    assert resolved == "https://trusted-internal-proxy.local/v1"


def test_resolve_provider_does_not_forward_host_key_to_workspace_url(tmp_path: Path, monkeypatch):
    """When a repo defines OPENAI_BASE_URL, resolve_provider must not attach host OPENAI_API_KEY to it."""
    import sys
    from unittest.mock import MagicMock
    mock_openai_module = MagicMock()
    monkeypatch.setitem(sys.modules, "openai", mock_openai_module)

    soma_dir = tmp_path / ".soma"
    soma_dir.mkdir(parents=True)
    conf_file = soma_dir / "soma.conf"
    conf_file.write_text("OPENAI_BASE_URL=https://evil.attacker.com/v1\n", encoding="utf-8")

    monkeypatch.setenv("OPENAI_API_KEY", "sk-live-host-secret-key-12345")
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)

    provider = resolve_provider(workspace=str(tmp_path), provider_name="openai")
    assert provider is not None and provider.__class__.__name__ == "OpenAIProvider"
    assert provider.base_url != "https://evil.attacker.com/v1", (
        "OpenAIProvider configured with untrusted workspace base_url! Host API key would be leaked."
    )
    assert provider.base_url is None

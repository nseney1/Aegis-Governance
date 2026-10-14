from pathlib import Path
"""TDD tests for keyring integration in resolve_key.

Tests verify the resolution priority: env var > keyring > config file,
and that keyring is handled gracefully when unavailable or erroring.
"""
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

REPO_ROOT = str(next(p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").exists()))
sys.path.insert(0, REPO_ROOT)

from aegis_core.inference_provider import resolve_key, read_config_key


# ── Helpers ───────────────────────────────────────────────────────────────

@pytest.fixture
def no_env(monkeypatch):
    """Ensure test env vars are not set."""
    for key in ("TEST_API_KEY", "ALT_KEY"):
        monkeypatch.delenv(key, raising=False)


@pytest.fixture
def tmp_workspace(tmp_path):
    """Create a minimal workspace with a soma.conf containing a test key."""
    conf = tmp_path / "soma.conf"
    conf.write_text('TEST_CONFIG_VAL="config-value-123"\nTEST_API_KEY="leaked-secret"\n', encoding="utf-8")
    return str(tmp_path)


# ── 1. Env var value returned when set ────────────────────────────────────

class TestResolveKeyEnvVar:
    def test_returns_env_var_when_set(self, monkeypatch, tmp_workspace):
        monkeypatch.setenv("TEST_API_KEY", "env-value-abc")
        result = resolve_key(tmp_workspace, ["TEST_API_KEY"])
        assert result == "env-value-abc"


# ── 2. Keyring value when env var not set ─────────────────────────────────

class TestResolveKeyKeyring:
    def test_returns_keyring_value_when_env_not_set(self, no_env, tmp_path):
        """When env var is absent but keyring has the key, return keyring value."""
        mock_keyring = MagicMock()
        mock_keyring.get_password.return_value = "keyring-secret-456"
        with patch.dict("sys.modules", {"keyring": mock_keyring}):
            # Re-import to pick up the mocked keyring
            import importlib
            from aegis_core import inference_provider as mod
            importlib.reload(mod)
            try:
                result = mod.resolve_key(str(tmp_path), ["TEST_API_KEY"])
                assert result == "keyring-secret-456"
                mock_keyring.get_password.assert_called_with("soma", "TEST_API_KEY")
            finally:
                importlib.reload(mod)


# ── 3. Fallback to config file ────────────────────────────────────────────

class TestResolveKeyConfigFallback:
    def test_falls_back_to_config_when_no_env_no_keyring(self, no_env, tmp_workspace):
        """Neither env nor keyring → config file value."""
        mock_keyring = MagicMock()
        mock_keyring.get_password.return_value = None
        with patch.dict("sys.modules", {"keyring": mock_keyring}):
            import importlib
            from aegis_core import inference_provider as mod
            importlib.reload(mod)
            try:
                result = mod.resolve_key(tmp_workspace, ["TEST_CONFIG_VAL"])
                assert result == "config-value-123"
            finally:
                importlib.reload(mod)


# ── 4. Returns None when nothing has the key ──────────────────────────────

class TestResolveKeyNone:
    def test_returns_none_when_nothing_has_key(self, no_env, tmp_path):
        """No env, no keyring, no config → None."""
        mock_keyring = MagicMock()
        mock_keyring.get_password.return_value = None
        with patch.dict("sys.modules", {"keyring": mock_keyring}):
            import importlib
            from aegis_core import inference_provider as mod
            importlib.reload(mod)
            try:
                result = mod.resolve_key(str(tmp_path), ["TEST_API_KEY"])
                assert result is None
            finally:
                importlib.reload(mod)


# ── 5. Graceful when keyring package not installed ────────────────────────

class TestResolveKeyNoKeyringPackage:
    def test_works_without_keyring_installed(self, no_env, tmp_workspace):
        """When keyring is not installed, fall back to config without error."""
        with patch.dict("sys.modules", {"keyring": None}):
            import importlib
            from aegis_core import inference_provider as mod
            importlib.reload(mod)
            try:
                result = mod.resolve_key(tmp_workspace, ["TEST_CONFIG_VAL"])
                assert result == "config-value-123"
            finally:
                importlib.reload(mod)


# ── 6. Fallback to config when keyring raises exception ───────────────────

class TestResolveKeyKeyringException:
    def test_falls_back_when_keyring_raises(self, no_env, tmp_workspace):
        """If keyring.get_password raises, swallow and fall back to config."""
        mock_keyring = MagicMock()
        mock_keyring.get_password.side_effect = RuntimeError("dbus not available")
        with patch.dict("sys.modules", {"keyring": mock_keyring}):
            import importlib
            from aegis_core import inference_provider as mod
            importlib.reload(mod)
            try:
                result = mod.resolve_key(tmp_workspace, ["TEST_CONFIG_VAL"])
                assert result == "config-value-123"
            finally:
                importlib.reload(mod)


# ── 7. Env var takes priority over keyring ────────────────────────────────

class TestResolveKeyPriorityEnvOverKeyring:
    def test_env_wins_over_keyring(self, monkeypatch, tmp_workspace):
        """Env var must beat keyring, even when keyring has a value."""
        monkeypatch.setenv("TEST_CONFIG_VAL", "env-wins")
        mock_keyring = MagicMock()
        mock_keyring.get_password.return_value = "keyring-loses"
        with patch.dict("sys.modules", {"keyring": mock_keyring}):
            import importlib
            from aegis_core import inference_provider as mod
            importlib.reload(mod)
            try:
                result = mod.resolve_key(tmp_workspace, ["TEST_CONFIG_VAL"])
                assert result == "env-wins"
            finally:
                importlib.reload(mod)

# ── 8. API keys in config are ignored ─────────────────────────────────────

class TestResolveKeySecretIgnoresConfig:
    def test_api_keys_ignore_config_file(self, no_env, tmp_workspace):
        """Even if an API key is in soma.conf, resolve_key must ignore it and return None."""
        mock_keyring = MagicMock()
        mock_keyring.get_password.return_value = None
        with patch.dict("sys.modules", {"keyring": mock_keyring}):
            import importlib
            from aegis_core import inference_provider as mod
            importlib.reload(mod)
            try:
                # The fixture puts TEST_API_KEY="leaked-secret" in soma.conf
                result = mod.resolve_key(tmp_workspace, ["TEST_API_KEY"])
                assert result is None  # Must ignore the config file!
            finally:
                importlib.reload(mod)


# ── 8. Keyring takes priority over config ─────────────────────────────────

class TestResolveKeyPriorityKeyringOverConfig:
    def test_keyring_wins_over_config(self, no_env, tmp_workspace):
        """Keyring must beat config file."""
        mock_keyring = MagicMock()
        mock_keyring.get_password.return_value = "keyring-wins"
        with patch.dict("sys.modules", {"keyring": mock_keyring}):
            import importlib
            from aegis_core import inference_provider as mod
            importlib.reload(mod)
            try:
                result = mod.resolve_key(tmp_workspace, ["TEST_API_KEY"])
                assert result == "keyring-wins"
            finally:
                importlib.reload(mod)

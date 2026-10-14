"""Behavioral tests for BUG-081: Gemini Provider AFC Warning & CLI Pollution.

Upstream google-genai SDK emits an advisory warning when automatic function calling (AFC)
is left enabled in Models.generate_content. Because Soma uses Gemini purely as a
single-turn reasoning model without tool calling, GeminiProvider must explicitly
disable AFC in its generate_content config.
"""
import sys
from unittest.mock import MagicMock, patch

from aegis_core.inference_provider import GeminiProvider


def test_gemini_provider_disables_automatic_function_calling():
    """GeminiProvider.generate() must pass config with AFC disabled."""
    mock_google = MagicMock()
    mock_genai = MagicMock()
    mock_google.genai = mock_genai
    mock_client = MagicMock()
    mock_genai.Client.return_value = mock_client

    with patch.dict(sys.modules, {"google": mock_google, "google.genai": mock_genai}):
        provider = GeminiProvider(api_key="fake-test-key")
        provider.generate("test prompt")

        mock_client.models.generate_content.assert_called_once()
        _, kwargs = mock_client.models.generate_content.call_args
        assert kwargs.get("model") == "gemini-3.8-flash"
        assert kwargs.get("contents") == "test prompt"
        assert kwargs.get("config") == {"automatic_function_calling": {"disable": True}}

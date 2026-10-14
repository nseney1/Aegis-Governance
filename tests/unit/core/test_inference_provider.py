"""Tests for inference provider resolution, models, and fallback behavior."""
import inspect
import sys
import unittest
from unittest.mock import MagicMock, patch

from aegis_core.inference_provider import (
    AnthropicProvider,
    GeminiProvider,
    InferenceProvider,
    OpenAIProvider,
    PromptOnlyProvider,
    resolve_provider,
)


class TestInferenceProviderModels(unittest.TestCase):
    def test_all_providers_define_default_model(self):
        """Ensure all concrete InferenceProvider subclasses define a non-empty DEFAULT_MODEL."""
        providers = [GeminiProvider, AnthropicProvider, OpenAIProvider, PromptOnlyProvider]
        for p_cls in providers:
            self.assertTrue(
                hasattr(p_cls, "DEFAULT_MODEL"),
                f"{p_cls.__name__} must define DEFAULT_MODEL class attribute",
            )
            self.assertTrue(
                len(p_cls.DEFAULT_MODEL) > 0,
                f"{p_cls.__name__}.DEFAULT_MODEL cannot be empty",
            )

    def test_default_model_property(self):
        """Ensure the default_model property returns DEFAULT_MODEL."""
        mock_google = MagicMock()
        mock_genai = MagicMock()
        mock_google.genai = mock_genai
        with patch.dict(sys.modules, {"google": mock_google, "google.genai": mock_genai}):
            p1 = GeminiProvider(api_key="k")
            self.assertEqual(p1.default_model, "gemini-3.8-flash")

        mock_anthropic_mod = MagicMock()
        with patch.dict(sys.modules, {"anthropic": mock_anthropic_mod}):
            p2 = AnthropicProvider(api_key="k")
            self.assertEqual(p2.default_model, "claude-3-5-sonnet-latest")

        mock_openai_mod = MagicMock()
        with patch.dict(sys.modules, {"openai": mock_openai_mod}):
            p3 = OpenAIProvider(api_key="k")
            self.assertEqual(p3.default_model, "gpt-4o")

        p4 = PromptOnlyProvider()
        self.assertEqual(p4.default_model, "human")

    def test_gemini_provider_default_model(self):
        """Ensure GeminiProvider defaults to active gemini-3.8-flash."""
        mock_google = MagicMock()
        mock_genai = MagicMock()
        mock_google.genai = mock_genai
        mock_client = MagicMock()
        mock_genai.Client.return_value = mock_client
        with patch.dict(sys.modules, {"google": mock_google, "google.genai": mock_genai}):
            provider = GeminiProvider(api_key="fake-key")
            self.assertEqual(provider.DEFAULT_MODEL, "gemini-3.8-flash")

            provider.generate("test prompt")
            mock_client.models.generate_content.assert_called_once_with(
                model="gemini-3.8-flash",
                contents="test prompt",
                config={"automatic_function_calling": {"disable": True}},
            )

    def test_gemini_provider_count_tokens_default_model(self):
        """Ensure GeminiProvider token counting defaults to gemini-3.8-flash."""
        mock_google = MagicMock()
        mock_genai = MagicMock()
        mock_google.genai = mock_genai
        mock_client = MagicMock()
        mock_genai.Client.return_value = mock_client
        with patch.dict(sys.modules, {"google": mock_google, "google.genai": mock_genai}):
            provider = GeminiProvider(api_key="fake-key")

            provider.count_tokens("test text")
            mock_client.models.count_tokens.assert_called_once_with(
                model="gemini-3.8-flash",
                contents="test text",
            )

    def test_anthropic_provider_default_model(self):
        """Ensure AnthropicProvider defaults to claude-3-5-sonnet-latest."""
        mock_anthropic_mod = MagicMock()
        with patch.dict(sys.modules, {"anthropic": mock_anthropic_mod}):
            mock_client = MagicMock()
            mock_anthropic_mod.Anthropic.return_value = mock_client
            provider = AnthropicProvider(api_key="fake-key")
            self.assertEqual(provider.DEFAULT_MODEL, "claude-3-5-sonnet-latest")

            provider.generate("test prompt")
            mock_client.messages.create.assert_called_once()
            call_kwargs = mock_client.messages.create.call_args.kwargs
            self.assertEqual(call_kwargs["model"], "claude-3-5-sonnet-latest")

    def test_openai_provider_default_model(self):
        """Ensure OpenAIProvider defaults to gpt-4o."""
        mock_openai_mod = MagicMock()
        with patch.dict(sys.modules, {"openai": mock_openai_mod}):
            mock_client = MagicMock()
            mock_openai_mod.OpenAI.return_value = mock_client
            provider = OpenAIProvider(api_key="fake-key")
            self.assertEqual(provider.DEFAULT_MODEL, "gpt-4o")

            provider.generate("test prompt")
            mock_client.chat.completions.create.assert_called_once()
            call_kwargs = mock_client.chat.completions.create.call_args.kwargs
            self.assertEqual(call_kwargs["model"], "gpt-4o")

    def test_compute_token_census_default_model(self):
        """Ensure compute_token_census default parameter is gemini-3.8-flash."""
        from aegis_core.metrics import compute_token_census
        sig = inspect.signature(compute_token_census)
        self.assertEqual(sig.parameters["model"].default, "gemini-3.8-flash")

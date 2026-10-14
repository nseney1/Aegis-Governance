"""Inference provider abstraction layer for Soma."""
import os
import sys
from abc import ABC, abstractmethod

def _get_keyring():
    if "keyring" in sys.modules:
        return sys.modules["keyring"]
    try:
        import keyring
        return keyring
    except ImportError:
        return None


class InferenceUnavailableError(RuntimeError):
    """No usable inference backend for this call site.

    Subclasses RuntimeError so existing broad `except Exception` handlers
    (e.g. ttc_oracle.evaluate_change) keep working unchanged.
    """


def _stdin_is_interactive():
    """True only when stdin is a real TTY we may safely read from.

    Under the stdio MCP server stdin carries the client's JSON-RPC requests;
    reading it would swallow them. sys.stdin can also be None (pythonw,
    some service supervisors) or a stream whose isatty() raises.
    """
    stream = getattr(sys, 'stdin', None)
    if stream is None:
        return False
    try:
        return bool(stream.isatty())
    except Exception:
        return False


def read_config_key(workspace, key):
    if not workspace:
        return None
    
    # Check soma.conf
    conf_path = os.path.join(workspace, 'soma.conf')
    if os.path.exists(conf_path):
        with open(conf_path, encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line.startswith(f"{key}=") and not line.startswith('#'):
                    return line.split('=', 1)[1].strip().strip('"').strip("'")
    
    return None

def resolve_key(workspace, env_keys):
    for key in env_keys:
        val = os.environ.get(key)
        if val:
            return val
        kr = _get_keyring()
        if kr is not None:
            try:
                val = kr.get_password('soma', key)
                if val:
                    return val
            except Exception:
                pass
        # Security Guard (BUG-073): Never permit untrusted workspace configs
        # (.soma/soma.conf) to specify API keys or external network base URLs/endpoints.
        # Doing so prevents malicious repositories from exfiltrating developer host
        # environment or keyring credentials via Authorization header forwarding.
        if "API_KEY" not in key and not any(k in key for k in ("BASE_URL", "_URL", "ENDPOINT", "HOST")):
            val = read_config_key(workspace, key)
            if val:
                return val
    return None

class InferenceProvider(ABC):
    DEFAULT_MODEL: str = ""

    @property
    def default_model(self) -> str:
        return self.DEFAULT_MODEL

    @abstractmethod
    def generate(self, prompt: str, model: str = None) -> str:
        pass
        
    @abstractmethod
    def count_tokens(self, text: str, model: str = None) -> int:
        pass

class GeminiProvider(InferenceProvider):
    DEFAULT_MODEL = "gemini-3.8-flash"

    def __init__(self, api_key=None):
        try:
            from google import genai
            if api_key:
                self.client = genai.Client(api_key=api_key)
            else:
                self.client = genai.Client()
        except ImportError:
            raise ImportError("google-genai package required. Install with: pip install google-genai")

    def generate(self, prompt: str, model: str = None) -> str:
        model_name = model or self.DEFAULT_MODEL
        response = self.client.models.generate_content(
            model=model_name,
            contents=prompt,
            config={"automatic_function_calling": {"disable": True}},
        )
        return response.text

    def count_tokens(self, text: str, model: str = None) -> int:
        model_name = model or self.DEFAULT_MODEL
        response = self.client.models.count_tokens(model=model_name, contents=text)
        return response.total_tokens

class AnthropicProvider(InferenceProvider):
    DEFAULT_MODEL = "claude-3-5-sonnet-latest"

    def __init__(self, api_key=None):
        try:
            from anthropic import Anthropic
            self.client = Anthropic(api_key=api_key)
        except ImportError:
            raise ImportError("anthropic package required. Install with: pip install anthropic")

    def generate(self, prompt: str, model: str = None) -> str:
        model_name = model or self.DEFAULT_MODEL
        response = self.client.messages.create(
            model=model_name,
            max_tokens=8192,
            messages=[{"role": "user", "content": prompt}]
        )
        return response.content[0].text
        
    def count_tokens(self, text: str, model: str = None) -> int:
        return int(len(text.split()) * 1.35)

class OpenAIProvider(InferenceProvider):
    DEFAULT_MODEL = "gpt-4o"

    def __init__(self, api_key=None, base_url=None):
        self.base_url = base_url
        try:
            from openai import OpenAI
            self.client = OpenAI(api_key=api_key, base_url=base_url)
        except ImportError:
            raise ImportError("openai package required. Install with: pip install openai")

    def generate(self, prompt: str, model: str = None) -> str:
        model_name = model or self.DEFAULT_MODEL
        response = self.client.chat.completions.create(
            model=model_name,
            messages=[{"role": "user", "content": prompt}]
        )
        return response.choices[0].message.content
        
    def count_tokens(self, text: str, model: str = None) -> int:
        return int(len(text.split()) * 1.35)

class PromptOnlyProvider(InferenceProvider):
    """Last-resort provider: hands the prompt to a human on an interactive TTY."""
    DEFAULT_MODEL = "human"

    def generate(self, prompt: str, model: str = None) -> str:
        if not _stdin_is_interactive():
            raise InferenceUnavailableError(
                "No inference provider is configured and stdin is not a TTY, so "
                "the prompt-only fallback cannot be used here (reading stdin "
                "would consume the MCP JSON-RPC request stream and hang the "
                "server). Configure a provider via GEMINI_API_KEY, "
                "ANTHROPIC_API_KEY or OPENAI_API_KEY in the environment "
                "or system keyring."
            )

        print("\n--- PROMPT TO MANUALLY PASTE ---", file=sys.stderr)
        print(prompt, file=sys.stderr)
        print("--------------------------------\n", file=sys.stderr)
        print("Please paste the response below (end with EOF / Ctrl+D):",
              file=sys.stderr)
        sys.stderr.flush()
        return sys.stdin.read().strip()

    def count_tokens(self, text: str, model: str = None) -> int:
        return int(len(text.split()) * 1.35)

def resolve_provider(workspace=None, provider_name=None):
    """Resolve the appropriate inference provider."""
    explicit_provider = provider_name or resolve_key(workspace, ["SOMA_INFERENCE_PROVIDER"])
    
    if explicit_provider == "gemini":
        key = resolve_key(workspace, ["GEMINI_API_KEY", "GOOGLE_API_KEY"])
        return GeminiProvider(api_key=key)
    elif explicit_provider == "anthropic":
        key = resolve_key(workspace, ["ANTHROPIC_API_KEY"])
        return AnthropicProvider(api_key=key)
    elif explicit_provider == "openai":
        key = resolve_key(workspace, ["OPENAI_API_KEY"])
        base_url = resolve_key(workspace, ["OPENAI_BASE_URL"])
        return OpenAIProvider(api_key=key, base_url=base_url)
    elif explicit_provider == "prompt-only":
        return PromptOnlyProvider()
        
    # Auto-resolve
    gemini_key = resolve_key(workspace, ["GEMINI_API_KEY", "GOOGLE_API_KEY"])
    if gemini_key:
        return GeminiProvider(api_key=gemini_key)
        
    anthropic_key = resolve_key(workspace, ["ANTHROPIC_API_KEY"])
    if anthropic_key:
        return AnthropicProvider(api_key=anthropic_key)
        
    openai_key = resolve_key(workspace, ["OPENAI_API_KEY"])
    if openai_key:
        base_url = resolve_key(workspace, ["OPENAI_BASE_URL"])
        return OpenAIProvider(api_key=openai_key, base_url=base_url)
        
    print("[soma] No inference provider configured; falling back to "
          "prompt-only (interactive TTY required).", file=sys.stderr)
    return PromptOnlyProvider()


__all__ = [
    "AnthropicProvider",
    "GeminiProvider",
    "InferenceProvider",
    "InferenceUnavailableError",
    "OpenAIProvider",
    "PromptOnlyProvider",
    "read_config_key",
    "resolve_key",
    "resolve_provider",
]

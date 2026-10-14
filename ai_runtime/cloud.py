"""Cloud LLM providers: OpenAI, Anthropic, Google.

These providers talk to the public APIs.  The HTTP layer is *not* duplicated:
it lives in :mod:`nodes.ai.llm` (``_chat_openai_compatible``,
``_chat_anthropic``, ``_chat_google``), which already knows how each API
shapes its request and response.  This module only adds the availability
contract required by the runtime -- the matching environment variable must be
set -- and turns the answer into a :class:`~ai_runtime.base.Completion`.
"""

from __future__ import annotations

import os
import time
from typing import Any, Dict, List, Optional, Sequence

from ai_runtime.base import Completion, Provider, ProviderUnavailable

__all__ = [
    "CLOUD_PROVIDERS",
    "OpenAIProvider",
    "AnthropicProvider",
    "GoogleProvider",
    "SYSTEM_PROMPT",
]

#: System prompt shared by every cloud provider.
SYSTEM_PROMPT = (
    "You are a scientific assistant inside Chem ML Platform.  Answer in the "
    "language of the question, be quantitative, state the confidence, and say "
    "explicitly when the available evidence is insufficient."
)


class _CloudProvider(Provider):
    """Shared plumbing of the public API providers."""

    family = "cloud"
    capabilities = ["complete"]
    #: Endpoint base for OpenAI-compatible APIs.
    base: str = ""
    #: Default system prompt.
    system: str = SYSTEM_PROMPT

    # -- API ----------------------------------------------------------------- #
    def complete(
        self, prompt: str, *, context: str = "", **kwargs: Any
    ) -> Completion:
        from nodes.ai import llm

        api_key = self._api_key()
        if not api_key:
            raise ProviderUnavailable(self.unavailable_reason())
        model = str(kwargs.get("model") or self.model)
        system = str(kwargs.get("system") or self.system)
        user = f"{prompt}\n\n{context}" if context else prompt
        temperature = float(kwargs.get("temperature", 0.3))
        max_tokens = int(kwargs.get("max_tokens", 1024))
        timeout = float(kwargs.get("timeout", 30.0))

        started = time.perf_counter()
        try:
            answer = self._call(llm, api_key, model, system, user, temperature, max_tokens, timeout)
        except Exception as exc:  # noqa: BLE001 - surfaced as unavailability
            raise ProviderUnavailable(f"{self.name}: {exc}") from exc

        text = str(getattr(answer, "content", "") or "")
        if not text.strip():
            raise ProviderUnavailable(f"{self.name}: empty completion")
        return self._completion(
            text,
            model=model,
            confidence=0.75,
            latency_ms=(time.perf_counter() - started) * 1000.0,
            metadata={"source": "cloud api"},
        )

    def _call(self, llm, api_key, model, system, user, temperature, max_tokens, timeout):
        """Invoke the provider specific handler in :mod:`nodes.ai.llm`."""
        raise NotImplementedError

    def _api_key(self) -> str:
        for key in self.env_keys:
            value = (os.environ.get(key) or "").strip()
            if value:
                return value
        return ""


class OpenAIProvider(_CloudProvider):
    name = "openai"
    model = "gpt-4o-mini"
    description = "OpenAI chat completions (GPT-4o / GPT-4o-mini)"
    env_keys = ["OPENAI_API_KEY"]
    base = "https://api.openai.com/v1"

    def _call(self, llm, api_key, model, system, user, temperature, max_tokens, timeout):
        return llm._chat_openai_compatible(
            self.base, api_key, model, system, user, temperature, max_tokens, timeout
        )


class AnthropicProvider(_CloudProvider):
    name = "anthropic"
    model = "claude-3-5-sonnet-latest"
    description = "Anthropic messages API (Claude 3.5 Sonnet)"
    env_keys = ["ANTHROPIC_API_KEY"]

    def _call(self, llm, api_key, model, system, user, temperature, max_tokens, timeout):
        return llm._chat_anthropic(
            api_key, model, system, user, temperature, max_tokens, timeout
        )


class GoogleProvider(_CloudProvider):
    name = "google"
    model = "gemini-1.5-flash"
    description = "Google Gemini generateContent API"
    env_keys = ["GOOGLE_API_KEY", "GEMINI_API_KEY"]

    def _call(self, llm, api_key, model, system, user, temperature, max_tokens, timeout):
        return llm._chat_google(
            api_key, model, system, user, temperature, max_tokens, timeout
        )


CLOUD_PROVIDERS: List[Provider] = [
    OpenAIProvider(),
    AnthropicProvider(),
    GoogleProvider(),
]

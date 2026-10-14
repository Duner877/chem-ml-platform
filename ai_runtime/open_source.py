"""Open-source LLM providers: Llama, Qwen, DeepSeek.

All three expose an **OpenAI-compatible** ``/chat/completions`` endpoint, so a
single transport (``_chat_openai_compatible``) serves them.  Availability is
decided by the matching environment variable *and*, for a locally hosted
endpoint, by an actual TCP reachability probe -- a stopped vLLM server must
not be treated as a working provider.
"""

from __future__ import annotations

import os
import socket
import time
from typing import Any, Dict, List, Optional, Sequence
from urllib.parse import urlparse

from ai_runtime.base import Completion, Provider, ProviderUnavailable
from ai_runtime.cloud import SYSTEM_PROMPT

__all__ = [
    "OPEN_SOURCE_PROVIDERS",
    "LlamaProvider",
    "QwenProvider",
    "DeepSeekProvider",
]


class _OpenAICompatibleProvider(Provider):
    """Base of every provider speaking the OpenAI chat schema."""

    family = "open_source"
    capabilities = ["complete"]
    base: str = ""
    system: str = SYSTEM_PROMPT
    #: Set when the endpoint is hosted locally (probe it before using it).
    local_endpoint: bool = False

    def complete(
        self, prompt: str, *, context: str = "", **kwargs: Any
    ) -> Completion:
        from nodes.ai import llm

        api_key = self._api_key()
        if not api_key:
            raise ProviderUnavailable(self.unavailable_reason())
        if self.local_endpoint and not _reachable(self.base):
            raise ProviderUnavailable(f"{self.name}: {self.base} is not reachable")

        model = str(kwargs.get("model") or self.model)
        user = f"{prompt}\n\n{context}" if context else prompt
        started = time.perf_counter()
        try:
            answer = llm._chat_openai_compatible(
                self.base,
                api_key,
                model,
                str(kwargs.get("system") or self.system),
                user,
                float(kwargs.get("temperature", 0.3)),
                int(kwargs.get("max_tokens", 1024)),
                float(kwargs.get("timeout", 60.0)),
            )
        except Exception as exc:  # noqa: BLE001 - surfaced as unavailability
            raise ProviderUnavailable(f"{self.name}: {exc}") from exc
        text = str(getattr(answer, "content", "") or "")
        if not text.strip():
            raise ProviderUnavailable(f"{self.name}: empty completion")
        return self._completion(
            text,
            model=model,
            confidence=0.7,
            latency_ms=(time.perf_counter() - started) * 1000.0,
            metadata={"source": "open-source endpoint", "base": self.base},
        )

    def _api_key(self) -> str:
        for key in self.env_keys:
            value = (os.environ.get(key) or "").strip()
            if value:
                return value
        return ""


class LlamaProvider(_OpenAICompatibleProvider):
    """Meta Llama served by vLLM / TGI / llama.cpp (OpenAI compatible)."""

    name = "llama"
    model = "meta-llama/Llama-3.1-8B-Instruct"
    description = "Meta Llama 3.1 via an OpenAI-compatible server"
    env_keys = ["LLAMA_API_KEY", "VLLM_API_KEY"]
    base = os.environ.get("CHEMML_LLAMA_BASE", "http://localhost:8001/v1")
    local_endpoint = True


class QwenProvider(_OpenAICompatibleProvider):
    """Alibaba Qwen: DashScope cloud or a local OpenAI-compatible server."""

    name = "qwen"
    model = "qwen-plus"
    description = "Alibaba Qwen (DashScope compatible mode)"
    env_keys = ["DASHSCOPE_API_KEY"]
    base = os.environ.get(
        "CHEMML_QWEN_BASE", "https://dashscope.aliyuncs.com/compatible-mode/v1"
    )


class DeepSeekProvider(_OpenAICompatibleProvider):
    name = "deepseek"
    model = "deepseek-chat"
    description = "DeepSeek chat (OpenAI compatible)"
    env_keys = ["DEEPSEEK_API_KEY"]
    base = os.environ.get("CHEMML_DEEPSEEK_BASE", "https://api.deepseek.com/v1")


OPEN_SOURCE_PROVIDERS: List[Provider] = [
    LlamaProvider(),
    QwenProvider(),
    DeepSeekProvider(),
]


def _reachable(base: str, timeout: float = 1.0) -> bool:
    """True when a TCP connection to ``base`` succeeds."""
    parsed = urlparse(base)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False

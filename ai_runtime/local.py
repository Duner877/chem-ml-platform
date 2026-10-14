"""Local inference providers: HuggingFace, vLLM, Ollama.

These providers run on the user's own machine or cluster.  All three speak the
OpenAI chat schema, so one transport serves them; what differs is how
availability is decided:

* **Ollama** -- ``http://localhost:11434/v1`` by default, probed over TCP.
* **vLLM** -- any OpenAI-compatible server, probed over TCP.
* **HuggingFace** -- the Inference API, which needs a token; when no token is
  present the provider reports unavailable so the registry moves on.
"""

from __future__ import annotations

import os
import socket
import time
from typing import Any, Dict, List, Optional, Sequence
from urllib.parse import urlparse

from ai_runtime.base import Completion, Provider, ProviderUnavailable
from ai_runtime.cloud import SYSTEM_PROMPT

__all__ = ["LOCAL_PROVIDERS", "HuggingFaceProvider", "VLLMProvider", "OllamaProvider"]


class _LocalProvider(Provider):
    """Shared plumbing of the local inference providers."""

    family = "local"
    capabilities = ["complete"]
    base: str = ""
    system: str = SYSTEM_PROMPT

    # -- availability -------------------------------------------------------- #
    def endpoint(self) -> str:
        return (os.environ.get(self.env_keys[0]) if self.env_keys else "") or self.base

    def available(self) -> bool:
        base = self.endpoint()
        if not base:
            return False
        if self.env_keys:
            # A token is required in addition to a reachable endpoint.
            token = (os.environ.get(self.env_keys[0]) or "").strip()
            if not token:
                return False
        return _reachable(base)

    def unavailable_reason(self) -> str:
        base = self.endpoint()
        if not base:
            return f"no {self.name} endpoint configured"
        if self.env_keys and not (os.environ.get(self.env_keys[0]) or "").strip():
            return f"{self.env_keys[0]} is not set"
        return f"{self.name} at {base} is not reachable"

    # -- API ----------------------------------------------------------------- #
    def complete(
        self, prompt: str, *, context: str = "", **kwargs: Any
    ) -> Completion:
        from nodes.ai import llm

        api_key = (os.environ.get(self.env_keys[0]) or "local").strip() if self.env_keys else "ollama"
        model = str(kwargs.get("model") or self.model)
        user = f"{prompt}\n\n{context}" if context else prompt
        started = time.perf_counter()
        try:
            answer = llm._chat_openai_compatible(
                self.endpoint(),
                api_key,
                model,
                str(kwargs.get("system") or self.system),
                user,
                float(kwargs.get("temperature", 0.3)),
                int(kwargs.get("max_tokens", 1024)),
                float(kwargs.get("timeout", 120.0)),
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
            metadata={"source": "local inference", "base": self.endpoint()},
        )


class HuggingFaceProvider(_LocalProvider):
    """HuggingFace Inference API (hosted models)."""

    name = "huggingface"
    model = "meta-llama/Meta-Llama-3.1-8B-Instruct"
    description = "HuggingFace Inference API"
    env_keys = ["HF_TOKEN", "HUGGINGFACE_API_KEY"]
    base = "https://api-inference.huggingface.co/v1"


class VLLMProvider(_LocalProvider):
    """vLLM OpenAI-compatible server."""

    name = "vllm"
    model = "Qwen/Qwen2.5-7B-Instruct"
    description = "vLLM OpenAI-compatible server (local GPU)"
    env_keys = []
    base = os.environ.get("CHEMML_VLLM_BASE", "http://localhost:8000/v1")


class OllamaProvider(_LocalProvider):
    """Ollama local model server."""

    name = "ollama"
    model = "qwen2.5:7b"
    description = "Ollama local model server"
    env_keys = []
    base = os.environ.get("CHEMML_OLLAMA_BASE", "http://localhost:11434/v1")


LOCAL_PROVIDERS: List[Provider] = [
    HuggingFaceProvider(),
    VLLMProvider(),
    OllamaProvider(),
]


def _reachable(base: str, timeout: float = 1.0) -> bool:
    parsed = urlparse(base)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False

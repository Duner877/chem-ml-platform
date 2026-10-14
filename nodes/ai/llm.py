"""Large language model node.

The node talks to the public HTTP API of the selected provider when a key is
available.  Offline (or when the provider is unreachable) it falls back on a
deterministic local summariser so that a workflow built with ``LLMNode`` always
runs: the fallback is flagged in ``Text.data`` with ``"engine": "offline"``.
"""

from __future__ import annotations

import json
import os
import re
import time
from typing import Any, Dict, List, Optional, Sequence

from workflow_engine.errors import NodeInputError
from workflow_engine.node_base import ParameterSpec, ScientificNode
from workflow_engine.objects import ScientificObject, ScientificReport, Spectrum, Table, Text
from workflow_engine.ports import Port
from workflow_engine.registry import register_node

from nodes._helpers import collect, render_report_markdown, to_text

__all__ = ["LLMNode", "PROVIDERS"]

#: ``provider -> (default model, API base, key environment variable)``
PROVIDERS: Dict[str, Dict[str, str]] = {
    "openai": {
        "model": "gpt-4o-mini",
        "base": "https://api.openai.com/v1",
        "env": "OPENAI_API_KEY",
    },
    "anthropic": {
        "model": "claude-3-5-sonnet-latest",
        "base": "https://api.anthropic.com/v1",
        "env": "ANTHROPIC_API_KEY",
    },
    "google": {
        "model": "gemini-1.5-flash",
        "base": "https://generativelanguage.googleapis.com/v1beta",
        "env": "GOOGLE_API_KEY",
    },
    "deepseek": {
        "model": "deepseek-chat",
        "base": "https://api.deepseek.com/v1",
        "env": "DEEPSEEK_API_KEY",
    },
    "qwen": {
        "model": "qwen-plus",
        "base": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "env": "DASHSCOPE_API_KEY",
    },
    "ollama": {
        "model": "qwen2.5:7b",
        "base": "http://localhost:11434/v1",
        "env": "OLLAMA_API_KEY",
    },
    "offline": {
        "model": "chemml-offline-summariser",
        "base": "",
        "env": "",
    },
}

_JSON_OBJECT_HINT = (
    "Reply with a single JSON object only, no markdown fences, with keys: "
    "answer, confidence, reasoning, suggested_experiments."
)


def _extract_json(text: str) -> Dict[str, Any]:
    """Best effort extraction of a JSON object embedded in ``text``."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z]*", "", cleaned).strip()
        cleaned = cleaned.rstrip("`").strip()
    try:
        payload = json.loads(cleaned)
        if isinstance(payload, dict):
            return payload
    except ValueError:
        pass
    match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
    if match:
        try:
            payload = json.loads(match.group(0))
            if isinstance(payload, dict):
                return payload
        except ValueError:
            return {}
    return {}


def _clip(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, float(value)))


def _offline_answer(prompt: str, context: str) -> Dict[str, Any]:
    """Deterministic, dependency free stand-in for a real completion."""
    keywords = [
        token
        for token in re.findall(r"[A-Za-z][A-Za-z0-9\-]{3,}", f"{prompt}\n{context}")
        if token.lower() not in {"the", "and", "for", "with", "that", "this", "from"}
    ]
    ranked: Dict[str, int] = {}
    for token in keywords:
        ranked[token] = ranked.get(token, 0) + 1
    top = [word for word, _ in sorted(ranked.items(), key=lambda kv: (-kv[1], kv[0]))[:6]]

    return {
        "answer": (
            "Offline reasoning sketch (no LLM credentials configured). "
            "Dominant evidence tokens: " + (", ".join(top) if top else "none") + "."
        ),
        "confidence": 0.35,
        "reasoning": (
            "The node scored the upstream evidence with a deterministic "
            "frequency heuristic. Configure an API key to obtain a真正的 "
            "language-model completion through this same port."
        ),
        "suggested_experiments": [
            "Acquire a high resolution MS1 spectrum for the molecular ion.",
            "Record a 2-D NMR (HSQC / HMBC) to confirm connectivity.",
            "Validate the candidate against an authentic reference standard.",
        ],
    }


class _Completion:
    """Uniform result wrapper shared by the provider back-ends."""

    def __init__(self, text: str, engine: str, model: str, latency_ms: float):
        self.text = text
        self.engine = engine
        self.model = model
        self.latency_ms = latency_ms


def _chat_openai_compatible(
    base: str, api_key: str, model: str, system: str, user: str, temperature: float,
    max_tokens: int, timeout: float,
) -> _Completion:
    """POST a chat completion to any OpenAI-compatible endpoint."""
    import httpx

    started = time.perf_counter()
    response = httpx.post(
        f"{base.rstrip('/')}/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        },
        timeout=timeout,
    )
    response.raise_for_status()
    payload = response.json()
    choices = payload.get("choices") or []
    content = ""
    if choices:
        message = choices[0].get("message") or {}
        content = str(message.get("content", ""))
    return _Completion(
        content, "remote", model, (time.perf_counter() - started) * 1000.0
    )


def _chat_anthropic(
    api_key: str, model: str, system: str, user: str, temperature: float,
    max_tokens: int, timeout: float,
) -> _Completion:
    """POST a message to the Anthropic Messages API."""
    import httpx

    started = time.perf_counter()
    response = httpx.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        },
        timeout=timeout,
    )
    response.raise_for_status()
    payload = response.json()
    blocks = payload.get("content") or []
    content = "".join(str(block.get("text", "")) for block in blocks if isinstance(block, dict))
    return _Completion(
        content, "remote", model, (time.perf_counter() - started) * 1000.0
    )


def _chat_google(
    api_key: str, model: str, system: str, user: str, temperature: float,
    max_tokens: int, timeout: float,
) -> _Completion:
    """POST a generateContent request to the Gemini API."""
    import httpx

    started = time.perf_counter()
    response = httpx.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        params={"key": api_key},
        json={
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens,
            },
        },
        timeout=timeout,
    )
    response.raise_for_status()
    payload = response.json()
    candidates = payload.get("candidates") or []
    content = ""
    if candidates:
        parts = (candidates[0].get("content") or {}).get("parts") or []
        content = "".join(str(part.get("text", "")) for part in parts if isinstance(part, dict))
    return _Completion(
        content, "remote", model, (time.perf_counter() - started) * 1000.0
    )


@register_node
class LLMNode(ScientificNode):
    """Prompt a large language model with scientific context."""

    name = "LLM Reasoner"
    category = "AI/LLM"
    description = "调用 GPT / Claude / Gemini / Qwen / DeepSeek / Ollama 进行科学推理与解释生成。"
    version = "0.7.1"
    tags = ["ai", "llm", "gpt", "claude", "gemini", "reasoning"]
    #: v0.7.1 task E/F: cloud providers need the network; prompts may carry
    #: sensitive research data, so the permission prompt warns and local /
    #: offline providers are the honest fallback.
    capabilities = ["requires_network", "sensitive_data"]
    aliases = ["LLM", "GPT"]
    icon = "LL"

    input_ports = [
        Port("prompt", "Any", "提示词 / 文本", optional=True, multi=True),
        Port("context", "Any", "待推理的科学对象", optional=True, multi=True),
    ]
    output_ports = [
        Port("text", "Text", "模型回答"),
        Port("table", "Table", "结构化字段"),
    ]
    parameters = [
        ParameterSpec(
            "provider",
            "enum",
            "openai",
            "模型供应商",
            options=list(PROVIDERS),
        ),
        ParameterSpec("model", "string", "", "模型名（留空用默认值）"),
        ParameterSpec("api_key_env", "string", "", "API Key 环境变量名（覆盖默认）"),
        ParameterSpec("system_prompt", "text",
                      "You are a rigorous analytical chemist. Reason step by step and cite the evidence you were given.",
                      "系统提示词"),
        ParameterSpec("instruction", "text", "", "附加指令（拼在上下文之后）"),
        ParameterSpec("temperature", "number", 0.2, "采样温度", min=0.0, max=2.0, step=0.05),
        ParameterSpec("max_tokens", "integer", 1024, "最大输出 token", min=16, max=32768),
        ParameterSpec("timeout_s", "number", 30.0, "请求超时", unit="s", min=1.0, max=600.0),
        ParameterSpec("json_output", "boolean", True, "要求模型输出 JSON"),
    ]

    def execute(self, inputs: Dict[str, Any], ctx: Any = None) -> Dict[str, Any]:
        prompt = to_text(inputs.get("prompt"), default="")
        context = self._render_context(inputs.get("context"))
        instruction = str(self.get_param("instruction", "") or "").strip()

        provider_key = str(self.get_param("provider", "openai")).lower()
        provider = PROVIDERS.get(provider_key)
        if provider is None:
            raise NodeInputError(f"LLMNode: unknown provider {provider_key!r}")
        model = str(self.get_param("model", "") or "").strip() or provider["model"]
        system = str(self.get_param("system_prompt", "") or "")
        wants_json = bool(self.get_param("json_output", True))
        timeout = float(self.get_param("timeout_s", 30.0))

        sections = [part for part in (prompt, context, instruction) if part]
        user = "\n\n".join(sections)
        if not user:
            raise NodeInputError("LLMNode: empty prompt (connect a Text node or set 'instruction')")
        if wants_json:
            user = f"{user}\n\n{_JSON_OBJECT_HINT}"

        completion = self._complete(provider_key, provider, model, system, user, timeout)
        data = _extract_json(completion.text) if wants_json else {}
        confidence = _clip(data.get("confidence", 0.35))
        data.setdefault("answer", completion.text.strip())
        data["provider"] = provider_key
        data["model"] = model
        data["engine"] = completion.engine
        data["latency_ms"] = round(completion.latency_ms, 2)

        text = str(data.get("answer") or completion.text).strip()
        rows: List[List[Any]] = [
            ["provider", provider_key],
            ["model", model],
            ["engine", completion.engine],
            ["confidence", round(confidence, 4)],
            ["latency_ms", round(completion.latency_ms, 2)],
        ]
        reasoning = str(data.get("reasoning", "") or "")
        if reasoning:
            rows.append(["reasoning", reasoning])
        experiments = data.get("suggested_experiments") or []
        if isinstance(experiments, (list, tuple)):
            for index, item in enumerate(experiments):
                rows.append([f"experiment_{index + 1}", str(item)])

        self.log(f"LLM ({provider_key}/{model}) via {completion.engine}")
        return {
            "text": Text(name="LLM", text=text, data=data),
            "table": Table(name="LLM result", columns=["field", "value"], rows=rows),
        }

    # -- internals ---------------------------------------------------------- #
    @staticmethod
    def _render_context(value: Any) -> str:
        """Render the objects connected to ``context`` as readable text."""
        chunks: List[str] = []
        for item in collect(value):
            if isinstance(item, ScientificReport):
                chunks.append(render_report_markdown(item))
            elif isinstance(item, ScientificObject):
                chunks.append(item.summary())
            elif isinstance(item, (list, tuple)):
                chunks.extend(str(part) for part in item)
            else:
                chunks.append(str(item))
        return "\n".join(chunks)

    def _complete(
        self,
        provider_key: str,
        provider: Dict[str, str],
        model: str,
        system: str,
        user: str,
        timeout: float,
    ) -> _Completion:
        """Call the provider, degrading to the offline summariser on failure."""
        if provider_key == "offline":
            return _Completion(_offline_text(user), "offline", model, 0.0)

        variable = str(self.get_param("api_key_env", "") or "").strip() or provider["env"]
        api_key = os.environ.get(variable, "").strip()
        if not api_key and provider_key != "ollama":
            return _Completion(_offline_text(user), "offline", model, 0.0)

        temperature = float(self.get_param("temperature", 0.2))
        max_tokens = int(self.get_param("max_tokens", 1024))
        try:
            if provider_key == "anthropic":
                return _chat_anthropic(
                    api_key, model, system, user, temperature, max_tokens, timeout
                )
            if provider_key == "google":
                return _chat_google(
                    api_key, model, system, user, temperature, max_tokens, timeout
                )
            return _chat_openai_compatible(
                provider["base"], api_key or "ollama", model, system, user,
                temperature, max_tokens, timeout,
            )
        except Exception as exc:  # noqa: BLE001 - offline fallback
            self.log(f"provider {provider_key} unavailable: {exc}")
            return _Completion(_offline_text(user, str(exc)), "offline", model, 0.0)


def _offline_text(user: str, reason: str = "") -> str:
    """Build the JSON payload returned when no provider can be reached."""
    import json

    payload = _offline_answer(user, "")
    if reason:
        payload["reasoning"] = f"{payload['reasoning']} (provider error: {reason})"
    return json.dumps(payload, ensure_ascii=False, indent=2)

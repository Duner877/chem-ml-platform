"""AI runtime core: the provider contract and the registry that dispatches.

A provider is *available* when it can serve a request right now.  The rule the
platform follows everywhere is that availability is checked, never assumed:
a missing API key, a stopped Ollama daemon or an absent GPU all turn a provider
into :class:`ProviderUnavailable` and the registry moves on to the next one.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence

from workflow_engine.utils import new_id, now_iso

__all__ = [
    "Completion",
    "Provider",
    "ProviderUnavailable",
    "RuntimeRegistry",
    "registry",
    "FAMILIES",
]


#: Provider families in dispatch order.
FAMILIES: List[str] = ["cloud", "open_source", "chemistry", "local", "offline"]


@dataclass
class Completion:
    """One model answer plus the provenance needed to trust it."""

    text: str
    engine: str = "offline"
    family: str = "offline"
    model: str = ""
    provider: str = ""
    latency_ms: float = 0.0
    confidence: float = 0.0
    tokens: Dict[str, int] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": new_id("cmp_"),
            "text": self.text,
            "engine": self.engine,
            "family": self.family,
            "model": self.model,
            "provider": self.provider,
            "latency_ms": round(self.latency_ms, 3),
            "confidence": round(self.confidence, 4),
            "tokens": dict(self.tokens),
            "metadata": dict(self.metadata),
            "created_at": now_iso(),
        }


class ProviderUnavailable(RuntimeError):
    """Raised when a provider cannot serve the request.

    The message explains *why* (no API key, daemon down, ...) because the
    registry surfaces it in ``Completion.metadata["unavailable"]``.
    """


class Provider:
    """Base class of every AI runtime provider."""

    #: Family key from :data:`FAMILIES`.
    family: str = "offline"
    #: Provider key (``openai``, ``chemberta``, ``ollama``, ...).
    name: str = "Provider"
    #: Model identifier sent to the backend.
    model: str = ""
    #: Human readable description.
    description: str = ""
    #: Environment variables that must be set for the provider to work.
    env_keys: List[str] = []
    #: Tasks this provider can serve.
    capabilities: List[str] = ["complete"]
    #: Molecular properties this provider can predict.  ``["*"]`` means any.
    properties: List[str] = ["*"]

    # -- availability -------------------------------------------------------- #
    def available(self) -> bool:
        """True when the provider can serve a request right now."""
        return all(_env(key) for key in self.env_keys)

    def unavailable_reason(self) -> str:
        missing = [key for key in self.env_keys if not _env(key)]
        if missing:
            return "missing environment variable(s): " + ", ".join(missing)
        return "provider is not reachable"

    # -- API ----------------------------------------------------------------- #
    def complete(
        self, prompt: str, *, context: str = "", **kwargs: Any
    ) -> Completion:
        raise ProviderUnavailable(f"{self.name}: complete() is not implemented")

    def embed(self, items: Sequence[str], **kwargs: Any) -> List[List[float]]:
        raise ProviderUnavailable(f"{self.name}: embed() is not implemented")

    def predict(
        self, items: Sequence[str], *, property: str = "logp", **kwargs: Any
    ) -> List[Dict[str, Any]]:
        raise ProviderUnavailable(f"{self.name}: predict() is not implemented")

    # -- helpers ------------------------------------------------------------- #
    def describe(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "family": self.family,
            "model": self.model,
            "description": self.description,
            "available": self.available(),
            "reason": "" if self.available() else self.unavailable_reason(),
            "capabilities": list(self.capabilities),
            "env_keys": list(self.env_keys),
        }

    def _completion(
        self,
        text: str,
        *,
        model: str = "",
        confidence: float = 0.0,
        latency_ms: float = 0.0,
        metadata: Optional[Dict[str, Any]] = None,
        **tokens: Any,
    ) -> Completion:
        return Completion(
            text=text,
            engine=self.name,
            family=self.family,
            model=model or self.model,
            provider=self.name,
            latency_ms=latency_ms,
            confidence=confidence,
            metadata=dict(metadata or {}),
            tokens=dict(tokens),
        )


class RuntimeRegistry:
    """Holds every provider and dispatches to the first available one."""

    def __init__(self) -> None:
        self._providers: List[Provider] = []

    # -- registration -------------------------------------------------------- #
    def register(self, provider: Provider) -> Provider:
        if not isinstance(provider, Provider):
            raise TypeError("provider must subclass ai_runtime.base.Provider")
        self._providers.append(provider)
        return provider

    def register_many(self, providers: Iterable[Provider]) -> None:
        for provider in providers:
            self.register(provider)

    # -- lookup -------------------------------------------------------------- #
    @property
    def providers(self) -> List[Provider]:
        return list(self._providers)

    def family(self, name: str) -> List[Provider]:
        """Providers of one family, in registration order."""
        if name in ("", "auto", "any"):
            return list(self._providers)
        return [p for p in self._providers if p.family == name]

    def by_name(self, name: str) -> Optional[Provider]:
        for provider in self._providers:
            if provider.name == name:
                return provider
        return None

    def describe(self) -> List[Dict[str, Any]]:
        return [provider.describe() for provider in self._providers]

    # -- dispatch ------------------------------------------------------------ #
    def _candidates(self, family: str, provider: str) -> List[Provider]:
        if provider:
            chosen = self.by_name(provider)
            return [chosen] if chosen is not None else []
        # The runtime configuration may force a provider or restrict the mode.
        config = _safe_config()
        if config is not None:
            if config.provider:
                chosen = self.by_name(config.provider)
                return [chosen] if chosen is not None else []
            if family in ("", "auto", "any") and config.mode != "auto":
                ordered: List[Provider] = []
                for name in _family_order(config.mode):
                    ordered.extend(p for p in self._providers if p.family == name)
                return ordered
        return self.family(family)

    def mode(self) -> str:
        """The active AI mode (``auto`` / ``cloud`` / ``local`` / ...)."""
        config = _safe_config()
        return config.mode if config is not None else "auto"

    def state(self) -> Dict[str, Any]:
        """A compact snapshot: mode, forced provider and provider availability."""
        config = _safe_config()
        return {
            "mode": config.mode if config is not None else "auto",
            "provider": config.provider if config is not None else "",
            "model": config.model if config is not None else "",
            "available": [p.name for p in self._providers if p.available()],
            "providers": [p.describe() for p in self._providers],
        }

    def _first_available(
        self, family: str, provider: str, method: str, property: str = ""
    ) -> tuple[Optional[Provider], Dict[str, str]]:
        """Return the first provider able to serve ``method`` (and ``property``)
        plus the reasons the previous ones were skipped.

        A provider that declares ``properties`` is skipped when the requested
        property is not in its list -- otherwise the Uni-Mol provider, which
        computes an electronic energy, would happily answer a ``logp`` request
        with the wrong number.
        """
        reasons: Dict[str, str] = {}
        for candidate in self._candidates(family, provider):
            if method not in candidate.capabilities:
                continue
            if property and "*" not in candidate.properties:
                if property not in candidate.properties:
                    reasons[candidate.name] = (
                        f"{candidate.name} does not predict {property!r}"
                    )
                    continue
            if candidate.available():
                return candidate, reasons
            reasons[candidate.name] = candidate.unavailable_reason()
        return None, reasons

    def complete(
        self,
        prompt: str,
        *,
        family: str = "auto",
        provider: str = "",
        context: str = "",
        **kwargs: Any,
    ) -> Completion:
        config = _safe_config()
        if config is not None:
            if config.model:
                kwargs.setdefault("model", config.model)
            kwargs.setdefault("temperature", config.temperature)
            kwargs.setdefault("max_tokens", config.max_tokens)
            kwargs.setdefault("timeout", config.timeout)
        provider_obj, reasons = self._first_available(family, provider, "complete")
        started = time.perf_counter()
        if provider_obj is None:
            raise ProviderUnavailable(
                "no provider can complete(); tried "
                + (", ".join(reasons) or "none")
            )
        result = provider_obj.complete(prompt, context=context, **kwargs)
        result.latency_ms = (time.perf_counter() - started) * 1000.0
        if reasons:
            result.metadata["skipped"] = reasons
        return result

    def embed(
        self, items: Sequence[str], *, family: str = "auto", provider: str = "", **kwargs: Any
    ) -> List[List[float]]:
        provider_obj, _ = self._first_available(family, provider, "embed")
        if provider_obj is None:
            raise ProviderUnavailable("no provider can embed()")
        return provider_obj.embed(items, **kwargs)

    def predict(
        self,
        items: Sequence[str],
        *,
        property: str = "logp",
        family: str = "auto",
        provider: str = "",
        **kwargs: Any,
    ) -> List[Dict[str, Any]]:
        provider_obj, reasons = self._first_available(
            family, provider, "predict", property=property
        )
        if provider_obj is None:
            raise ProviderUnavailable(
                "no provider can predict(); tried " + (", ".join(reasons) or "none")
            )
        rows = provider_obj.predict(items, property=property, **kwargs)
        if reasons:
            for row in rows:
                row.setdefault("skipped", {}).update(reasons)
        return rows


#: Process wide registry.
registry = RuntimeRegistry()


def _env(key: str) -> str:
    """Non empty environment variable, or ``""``."""
    import os

    return (os.environ.get(key) or "").strip()


def _safe_config():
    """Load the AI configuration without creating an import cycle."""
    try:
        from ai_runtime.config import get_config

        return get_config()
    except Exception:  # pragma: no cover - config is optional at runtime
        return None


def _family_order(mode: str) -> List[str]:
    try:
        from ai_runtime.config import family_order

        return family_order(mode)
    except Exception:  # pragma: no cover
        return [mode]

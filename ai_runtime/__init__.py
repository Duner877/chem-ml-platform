"""AI Runtime -- one interface, four families of providers.

The specification requires a single AI runtime covering four provider
families, with an *internal engine* fallback whenever the real model is not
reachable::

    ai_runtime.complete("describe this spectrum", family="auto")
    ai_runtime.embed(["CCO", "c1ccccc1"])          # chemistry embeddings
    ai_runtime.predict(["CCO"], property="logp")    # property prediction

Families
--------
``cloud``       OpenAI, Anthropic, Google (API key required)
``open_source``  Llama, Qwen, DeepSeek (OpenAI compatible endpoints)
``chemistry``   Uni-Mol, ChemBERTa, GROVER, Graphormer
``local``       HuggingFace, vLLM, Ollama (local GPU / CPU)

Every provider implements the same three methods -- :meth:`Provider.complete`,
:meth:`Provider.embed`, :meth:`Provider.predict` -- and raises
:class:`ProviderUnavailable` when it cannot serve the request.  The registry
walks the family in priority order and falls back to
:class:`~ai_runtime.fallback.OfflineProvider`, which uses the platform's own
descriptor / fingerprint / EHT engines.  The engine that actually answered is
always recorded, so a result obtained offline is never mistaken for one
obtained from a real model.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Sequence

from ai_runtime.base import (
    Completion,
    Provider,
    ProviderUnavailable,
    RuntimeRegistry,
    registry,
)
from ai_runtime.config import (
    AIConfig,
    MODES,
    MODE_LABELS,
    get_config,
    save_config,
    set_mode,
    set_provider,
    update_config,
)

__all__ = [
    "Completion",
    "Provider",
    "ProviderUnavailable",
    "RuntimeRegistry",
    "registry",
    "complete",
    "embed",
    "predict",
    "describe",
    "register_builtin",
    # configuration / switching
    "AIConfig",
    "MODES",
    "MODE_LABELS",
    "get_config",
    "save_config",
    "set_mode",
    "set_provider",
    "update_config",
    "mode",
    "state",
]


def register_builtin() -> None:
    """Register every built-in provider family (idempotent)."""
    from ai_runtime.chemistry import CHEMISTRY_PROVIDERS
    from ai_runtime.cloud import CLOUD_PROVIDERS
    from ai_runtime.local import LOCAL_PROVIDERS
    from ai_runtime.open_source import OPEN_SOURCE_PROVIDERS

    registry.register_many(CLOUD_PROVIDERS)
    registry.register_many(OPEN_SOURCE_PROVIDERS)
    registry.register_many(CHEMISTRY_PROVIDERS)
    registry.register_many(LOCAL_PROVIDERS)
    # The offline engine is always last: it never raises.
    from ai_runtime.fallback import OfflineProvider

    registry.register_many([OfflineProvider()])


def complete(
    prompt: str,
    *,
    family: str = "auto",
    provider: str = "",
    context: str = "",
    **kwargs: Any,
) -> Completion:
    """Answer ``prompt`` with the first available provider of ``family``."""
    register_builtin()
    return registry.complete(
        prompt, family=family, provider=provider, context=context, **kwargs
    )


def embed(
    items: Sequence[str],
    *,
    family: str = "auto",
    provider: str = "",
    **kwargs: Any,
) -> List[List[float]]:
    """Embed ``items`` (SMILES, spectra, texts) into vectors."""
    register_builtin()
    return registry.embed(items, family=family, provider=provider, **kwargs)


def predict(
    items: Sequence[str],
    *,
    property: str = "logp",
    family: str = "auto",
    provider: str = "",
    **kwargs: Any,
) -> List[Dict[str, Any]]:
    """Predict ``property`` for every SMILES in ``items``."""
    register_builtin()
    return registry.predict(
        items, property=property, family=family, provider=provider, **kwargs
    )


def describe() -> List[Dict[str, Any]]:
    """JSON description of every registered provider."""
    register_builtin()
    return registry.describe()


def mode() -> str:
    """The active AI mode (``auto`` / ``cloud`` / ``local`` / ``offline``)."""
    return get_config().mode


def state() -> Dict[str, Any]:
    """Mode, forced provider and per-provider availability."""
    register_builtin()
    return registry.state()

"""Scientific Foundation Model runtime.

v0.6 "Scientific Foundation Model Edition" unifies every scientific
representation model behind one runtime, the way :mod:`ai_runtime` unifies the
language models::

    from foundation import embed, similarity, predict, describe

    embed(["CCO", "c1ccccc1"])                 # unit vectors
    similarity("CCO", "CCCO")                  # 0..1
    predict(["CCO"], property="logp")          # [{"value": ...}]

Models
------
``molecule``   ChemBERTa, GROVER, Graphormer, Uni-Mol, Morgan, Descriptor-Vector,
               plus the Physchem property predictor.
``spectrum``   Spectrum-Bin, Spectrum-Summary.

All models are deterministic, run offline on NumPy + the platform's own
``models`` engines, and record their provenance.  A model that would need
external weights reports ``requires_weights=True`` and uses a structure
encoder instead, so the topology of a workflow validates end to end.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from foundation.base import (
    MODALITIES,
    FoundationModel,
    FoundationRegistry,
    FoundationUnavailable,
    registry,
    seed_vector,
    unit,
)
from foundation.molecular import MOLECULAR_MODELS
from foundation.spectral import SPECTRAL_MODELS

__version__ = "0.7.1"

__all__ = [
    "FoundationModel",
    "FoundationRegistry",
    "FoundationUnavailable",
    "registry",
    "MODALITIES",
    "seed_vector",
    "unit",
    "register_builtin",
    "models",
    "describe",
    "catalog",
    "embed",
    "similarity",
    "predict",
    "__version__",
]

#: Guard so ``register_builtin`` stays cheap and idempotent.
_REGISTERED = False


def register_builtin() -> None:
    """Register every built-in foundation model (idempotent)."""
    global _REGISTERED
    if _REGISTERED:
        return
    registry.register_many(MOLECULAR_MODELS)
    registry.register_many(SPECTRAL_MODELS)
    _REGISTERED = True


def models() -> List[FoundationModel]:
    """Every registered foundation model."""
    register_builtin()
    return registry.models


def describe() -> List[Dict[str, Any]]:
    """JSON description of every registered foundation model."""
    register_builtin()
    return registry.describe()


def catalog() -> List[Dict[str, Any]]:
    """Model catalog enriched with the metadata from :mod:`models.registry`.

    The GUI uses this to show the architecture, task and reference of each
    model next to its live availability.
    """
    register_builtin()
    meta: Dict[str, Dict[str, Any]] = {}
    try:
        from models.registry import list_models

        for entry in list_models():
            meta[str(entry.get("key", "")).lower()] = entry
    except Exception:  # pragma: no cover - catalog is best effort
        meta = {}

    rows: List[Dict[str, Any]] = []
    for model in registry.models:
        described = model.describe()
        extra = meta.get(described["key"].lower(), {})
        described["task"] = extra.get("task", "")
        described["backend"] = extra.get("backend", "numpy")
        described["input"] = extra.get("input", "")
        described["output"] = extra.get("output", "")
        rows.append(described)
    return rows


def embed(
    items: Sequence[Any],
    *,
    model: str = "",
    modality: str = "molecule",
    dimension: Optional[int] = None,
    seed: int = 20240521,
) -> List[List[float]]:
    """Embed every item into a unit vector."""
    register_builtin()
    return registry.embed(
        items, model=model, modality=modality, dimension=dimension, seed=seed
    )


def similarity(
    first: Any,
    second: Any,
    *,
    model: str = "",
    modality: str = "molecule",
    metric: str = "cosine",
    seed: int = 20240521,
) -> float:
    """Similarity between two systems (0..1 for cosine on non-negative input)."""
    register_builtin()
    return registry.similarity(
        first, second, model=model, modality=modality, metric=metric, seed=seed
    )


def predict(
    items: Sequence[Any],
    *,
    property: str = "logp",
    model: str = "",
    modality: str = "molecule",
) -> List[Dict[str, Any]]:
    """Predict ``property`` for every item."""
    register_builtin()
    return registry.predict(
        items, property=property, model=model, modality=modality
    )

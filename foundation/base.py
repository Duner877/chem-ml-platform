"""Scientific foundation model runtime -- the core contract and registry.

v0.6 unifies every *scientific* representation model the platform ships --
molecular encoders (ChemBERTa / GROVER / Graphormer / Uni-Mol / Morgan),
physicochemical property predictors, and spectral encoders -- behind one
runtime, exactly the way :mod:`ai_runtime` unifies the language models.

    from foundation import embed, similarity, predict, describe

    foundation.embed(["CCO", "c1ccccc1"])              # unit vectors
    foundation.similarity("CCO", "CCCO")               # 0..1
    foundation.predict(["CCO"], property="logp")       # [{"value": ...}]

Every model is deterministic and runs offline on NumPy + the platform's own
``models`` engines; a model that would normally need external weights reports
``requires_weights=True`` and falls back to a structure encoder, which is
always recorded in the result metadata so a fallback is never mistaken for a
real checkpoint.

Layout
------
``foundation.base``      this file -- the contract and the registry
``foundation.molecular`` molecular encoders & property models
``foundation.spectral``  spectrum encoders & matchers
"""

from __future__ import annotations

import hashlib
from typing import Any, Dict, Iterable, List, Optional, Sequence

import numpy as np

__all__ = [
    "FoundationModel",
    "FoundationUnavailable",
    "FoundationRegistry",
    "registry",
    "MODALITIES",
    "seed_vector",
    "unit",
]

#: Modalities a foundation model can serve.
MODALITIES: List[str] = ["molecule", "spectrum", "material"]


class FoundationUnavailable(RuntimeError):
    """Raised when a foundation model cannot serve a request."""


def seed_vector(text: str, dimension: int, seed: int) -> np.ndarray:
    """Deterministic pseudo random projection of ``text`` into ``dimension``."""
    digest = hashlib.sha1(f"{seed}:{text}".encode("utf-8")).digest()
    values = np.frombuffer(digest * (dimension // 20 + 1), dtype=np.uint8)[:dimension]
    return (values.astype(float) / 127.5) - 1.0


def unit(vector: np.ndarray) -> np.ndarray:
    """Scale ``vector`` to unit length (a zero vector is returned unchanged)."""
    array = np.asarray(vector, dtype=float)
    norm = float(np.linalg.norm(array))
    return array / norm if norm > 0 else array


class FoundationModel:
    """Base class of every scientific foundation model."""

    #: Stable identifier (matches ``models.registry`` catalog keys when possible).
    key: str = ""
    #: Human readable name.
    name: str = "FoundationModel"
    #: Representation family (``smiles transformer``, ``fingerprint``, ...).
    family: str = "generic"
    #: Served modality -- one of :data:`MODALITIES`.
    modality: str = "molecule"
    #: Native embedding dimension.
    dimension: int = 256
    #: Capabilities: subset of ``{"embed", "predict", "similarity"}``.
    capabilities: List[str] = ["embed", "similarity"]
    #: Properties this model predicts; ``["*"]`` means any.
    properties: List[str] = ["*"]
    #: Long description shown by the GUI.
    description: str = ""
    #: True when the real checkpoint is distributed separately.
    requires_weights: bool = False
    #: Bibliographic reference.
    reference: str = ""

    # -- availability -------------------------------------------------------- #
    def available(self) -> bool:
        """Foundation models are pure NumPy, so they are always available."""
        return True

    # -- API ----------------------------------------------------------------- #
    def encode(
        self,
        system: Any,
        *,
        dimension: Optional[int] = None,
        seed: int = 20240521,
    ) -> np.ndarray:
        """Return a (unit length) embedding for ``system``."""
        raise FoundationUnavailable(f"{self.name}: encode() is not implemented")

    def predict(self, system: Any, *, property: str = "logp") -> Dict[str, Any]:
        """Predict ``property`` for ``system``."""
        raise FoundationUnavailable(f"{self.name}: predict() is not implemented")

    # -- helpers ------------------------------------------------------------- #
    def describe(self) -> Dict[str, Any]:
        return {
            "key": self.key or self.name.lower(),
            "name": self.name,
            "family": self.family,
            "modality": self.modality,
            "dimension": self.dimension,
            "capabilities": list(self.capabilities),
            "properties": list(self.properties),
            "description": self.description,
            "available": self.available(),
            "requires_weights": self.requires_weights,
            "reference": self.reference,
        }


class FoundationRegistry:
    """Holds every foundation model and dispatches requests to them."""

    def __init__(self) -> None:
        self._models: List[FoundationModel] = []

    # -- registration -------------------------------------------------------- #
    def register(self, model: FoundationModel) -> FoundationModel:
        if not isinstance(model, FoundationModel):
            raise TypeError("model must subclass foundation.base.FoundationModel")
        # Replace a previous registration with the same key (idempotent).
        key = model.key or model.name.lower()
        self._models = [m for m in self._models if (m.key or m.name.lower()) != key]
        self._models.append(model)
        return model

    def register_many(self, models: Iterable[FoundationModel]) -> None:
        for model in models:
            self.register(model)

    # -- lookup -------------------------------------------------------------- #
    @property
    def models(self) -> List[FoundationModel]:
        return list(self._models)

    def get(self, name: str) -> Optional[FoundationModel]:
        needle = (name or "").strip().lower()
        for model in self._models:
            if needle in {model.key.lower(), model.name.lower()}:
                return model
        return None

    def family(self, modality: str = "", capability: str = "") -> List[FoundationModel]:
        """Models filtered by modality and/or capability."""
        result = list(self._models)
        if modality:
            result = [m for m in result if m.modality == modality]
        if capability:
            result = [m for m in result if capability in m.capabilities]
        return result

    def describe(self) -> List[Dict[str, Any]]:
        return [model.describe() for model in self._models]

    # -- dispatch ------------------------------------------------------------ #
    def _resolve(
        self, model: str, capability: str, property: str = "", modality: str = ""
    ) -> FoundationModel:
        if model:
            chosen = self.get(model)
            if chosen is None:
                raise FoundationUnavailable(f"unknown foundation model {model!r}")
            if capability not in chosen.capabilities:
                raise FoundationUnavailable(
                    f"{chosen.name} does not support {capability!r}"
                )
            return chosen
        for candidate in self._models:
            if capability not in candidate.capabilities:
                continue
            if modality and candidate.modality != modality:
                continue
            if property and "*" not in candidate.properties:
                if property not in candidate.properties:
                    continue
            if candidate.available():
                return candidate
        raise FoundationUnavailable(
            f"no foundation model can serve {capability!r}"
            + (f" for {property!r}" if property else "")
        )

    def embed(
        self,
        items: Sequence[str],
        *,
        model: str = "",
        modality: str = "molecule",
        dimension: Optional[int] = None,
        seed: int = 20240521,
    ) -> List[List[float]]:
        """Embed every item into a unit vector."""
        chosen = self._resolve(model, "embed", modality=modality)
        vectors: List[List[float]] = []
        for item in items:
            vector = unit(chosen.encode(item, dimension=dimension, seed=seed))
            vectors.append([float(value) for value in vector])
        return vectors

    def similarity(
        self,
        first: str,
        second: str,
        *,
        model: str = "",
        modality: str = "molecule",
        metric: str = "cosine",
        seed: int = 20240521,
    ) -> float:
        """Similarity between two systems (0..1)."""
        chosen = self._resolve(model, "similarity", modality=modality)
        left = unit(chosen.encode(first, seed=seed))
        right = unit(chosen.encode(second, seed=seed))
        if metric == "euclidean":
            return float(1.0 / (1.0 + float(np.linalg.norm(left - right))))
        # cosine is the universal fallback
        value = float(np.dot(left, right))
        return float(max(-1.0, min(1.0, value)))

    def predict(
        self,
        items: Sequence[str],
        *,
        property: str = "logp",
        model: str = "",
        modality: str = "molecule",
    ) -> List[Dict[str, Any]]:
        """Predict ``property`` for every item."""
        chosen = self._resolve(model, "predict", property=property, modality=modality)
        rows: List[Dict[str, Any]] = []
        for item in items:
            row = chosen.predict(item, property=property)
            row.setdefault("model", chosen.name)
            row.setdefault("property", property)
            rows.append(row)
        return rows


#: Process wide registry.
registry = FoundationRegistry()

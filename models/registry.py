"""Model registry: which chemical foundation models are available.

The registry keeps a manifest of the shipped / downloadable models and returns
the right wrapper for a node.  Everything is offline friendly: the models that
need weights fall back to a deterministic, structure based encoder when the
weights are not present.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from .mpnn import MPNNConfig, create_model, HAS_TORCH

__all__ = ["ModelSpec", "MODEL_CATALOG", "list_models", "get_model", "describe_models"]

ROOT = Path(__file__).resolve().parents[1]
CHECKPOINT_DIR = ROOT / "models" / "checkpoints"


@dataclass
class ModelSpec:
    """Description of a chemical foundation model."""

    key: str
    name: str
    family: str
    task: str
    input: str
    output: str
    backend: str
    requires_weights: bool = False
    notes: str = ""
    embedding_dim: int = 384
    reference: str = ""


MODEL_CATALOG: List[ModelSpec] = [
    ModelSpec(
        key="uni-mol",
        name="Uni-Mol",
        family="3D transformer",
        task="molecular representation / property prediction",
        input="3D conformer (atoms + coordinates)",
        output="atom & graph embeddings",
        backend="torch" if HAS_TORCH else "numpy",
        requires_weights=True,
        embedding_dim=512,
        notes=(
            "When the Uni-Mol checkpoint is absent the node falls back to the "
            "structure encoder (descriptors + Morgan fingerprint)."
        ),
        reference="Zhou et al., Nat. Mach. Intell./ICLR 2023, Uni-Mol",
    ),
    ModelSpec(
        key="chemberta",
        name="ChemBERTa",
        family="SMILES transformer",
        task="property prediction / fingerprint",
        input="SMILES string",
        output="embedding + property head",
        backend="torch" if HAS_TORCH else "numpy",
        requires_weights=True,
        embedding_dim=384,
        notes="Falls back to a hashed SMILES n-gram encoder without weights.",
        reference="Chithrananda et al., 2020, ChemBERTa",
    ),
    ModelSpec(
        key="grover",
        name="GROVER",
        family="graph transformer",
        task="self-supervised molecular representation",
        input="molecular graph",
        output="graph embedding",
        backend="torch" if HAS_TORCH else "numpy",
        requires_weights=True,
        embedding_dim=512,
        notes="Falls back to the message passing encoder.",
        reference="Rong et al., NeurIPS 2020, GROVER",
    ),
    ModelSpec(
        key="graphormer",
        name="Graphormer",
        family="graph transformer",
        task="quantum property regression",
        input="molecular graph",
        output="graph embedding + property",
        backend="torch" if HAS_TORCH else "numpy",
        requires_weights=True,
        embedding_dim=768,
        notes="Falls back to the message passing encoder.",
        reference="Ying et al., NeurIPS 2021, Graphormer",
    ),
    ModelSpec(
        key="mpnn-local",
        name="ChemML-MPNN",
        family="message passing neural network",
        task="property prediction",
        input="molecular graph",
        output="embedding + property",
        backend="torch" if HAS_TORCH else "numpy",
        requires_weights=False,
        embedding_dim=128,
        notes="Trains on the shipped benchmark dataset (see ``datasets/``).",
        reference="Gilmer et al., ICML 2017, MPNN",
    ),
    ModelSpec(
        key="clip-mol",
        name="Mol-CLIP",
        family="contrastive vision-language",
        task="spectrum/structure alignment",
        input="spectrum + structure",
        output="joint embedding",
        backend="numpy",
        requires_weights=True,
        embedding_dim=512,
        notes="Used by the Vision AI node for image/spectrum retrieval.",
        reference="Radford et al., 2021, CLIP",
    ),
]


def list_models() -> List[Dict[str, Any]]:
    """Return the model catalog as dictionaries."""
    return [asdict(spec) for spec in MODEL_CATALOG]


def describe_models() -> str:
    """Human readable listing of the catalog."""
    lines = []
    for spec in MODEL_CATALOG:
        lines.append(
            f"{spec.key:12} {spec.name:12} [{spec.family}] -> {spec.task}"
        )
    return "\n".join(lines)


def get_model(key: str = "mpnn-local", **overrides: Any):
    """Instantiate the wrapper for ``key``.

    Unknown keys fall back to ``mpnn-local``.  ``overrides`` are forwarded to
    :class:`~models.mpnn.MPNNConfig`.
    """
    spec = next((item for item in MODEL_CATALOG if item.key == key), None)
    if spec is None:
        spec = next(item for item in MODEL_CATALOG if item.key == "mpnn-local")
    config = MPNNConfig()
    for name, value in overrides.items():
        if hasattr(config, name):
            setattr(config, name, value)
    model = create_model(config, backend=spec.backend)
    model.spec = spec  # type: ignore[attr-defined]
    return model

"""Chemical machine-learning models shipped with the platform.

The package is intentionally RDKit-free: the molecular graph is produced by the
built-in SMILES parser (:mod:`models.smiles`), descriptors are computed with
:mod:`models.descriptors`, circular fingerprints with
:mod:`models.fingerprints` and the learned representation with
:mod:`models.mpnn` (PyTorch when available, NumPy ridge otherwise).
"""

from __future__ import annotations

from .descriptors import (
    DESCRIPTOR_KEYS,
    QED,
    compute_descriptors,
    descriptor_vector,
    lipinski_violations,
)
from .features import (
    ATOM_FEATURE_DIM,
    BOND_FEATURE_DIM,
    atom_features,
    bond_features,
    graph_to_arrays,
)
from .fingerprints import (
    dice,
    morgan_bits,
    morgan_counts,
    morgan_fingerprint,
    smiles_similarity,
    tanimoto,
)
from .mpnn import (
    HAS_TORCH,
    MPNNConfig,
    RidgeMPNN,
    create_model,
    evaluate_model,
    train_model,
)
from .registry import MODEL_CATALOG, describe_models, get_model, list_models
from .smiles import (
    MolecularGraph,
    SmilesParseError,
    parse_smiles,
    to_smiles,
    validate_smiles,
)

__version__ = "0.7.1"

__all__ = [
    "MolecularGraph",
    "SmilesParseError",
    "parse_smiles",
    "to_smiles",
    "validate_smiles",
    "compute_descriptors",
    "descriptor_vector",
    "DESCRIPTOR_KEYS",
    "lipinski_violations",
    "QED",
    "morgan_fingerprint",
    "morgan_counts",
    "morgan_bits",
    "tanimoto",
    "dice",
    "smiles_similarity",
    "atom_features",
    "bond_features",
    "graph_to_arrays",
    "ATOM_FEATURE_DIM",
    "BOND_FEATURE_DIM",
    "HAS_TORCH",
    "MPNNConfig",
    "RidgeMPNN",
    "create_model",
    "train_model",
    "evaluate_model",
    "MODEL_CATALOG",
    "list_models",
    "get_model",
    "describe_models",
    "__version__",
]

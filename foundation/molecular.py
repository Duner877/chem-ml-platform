"""Molecular foundation models.

Two kinds of model live here:

* **Encoders** turn a molecule (SMILES string or
  :class:`~models.smiles.MolecularGraph`) into a fixed length vector:
  ``ChemBERTa`` (hashed SMILES n-grams), ``GROVER`` (message passing),
  ``Graphormer`` (graph transformer with shortest path encodings),
  ``Uni-Mol`` (3D distance aware attention), ``Morgan`` (circular fingerprint)
  and ``DescriptorVector`` (physicochemical descriptor vector).
* **Property predictors** answer ``predict(smiles, property=...)`` queries:
  ``Physchem`` covers logP, molecular weight, TPSA, HBD/HBA, rotatable bonds,
  aromatic rings, QED, ESOL solubility and Lipinski violations.

Everything is deterministic (fixed seeds) and runs on NumPy plus the
platform's own ``models`` engines, so a molecule can always be embedded even
without any external checkpoint.
"""

from __future__ import annotations

from collections import deque
from typing import Any, Dict, List, Optional

import numpy as np

from foundation.base import FoundationModel, FoundationUnavailable, seed_vector, unit
from models.descriptors import QED, compute_descriptors, lipinski_violations
from models.fingerprints import morgan_bits
from models.geometry import guess_coordinates
from models.smiles import MolecularGraph, parse_smiles, to_smiles

__all__ = [
    "MOLECULAR_MODELS",
    "ChemBERTaModel",
    "GROVERModel",
    "GraphormerModel",
    "UniMolModel",
    "MorganModel",
    "DescriptorVectorModel",
    "PhyschemModel",
    "esol_logs",
    "descriptor_bundle",
]


def _as_graph(system: Any) -> MolecularGraph:
    """Coerce ``system`` (SMILES or graph) into a :class:`MolecularGraph`."""
    if isinstance(system, MolecularGraph):
        return system
    if isinstance(system, str):
        return parse_smiles(system)
    smiles = getattr(system, "smiles", "")
    if smiles:
        return parse_smiles(str(smiles))
    raise FoundationUnavailable(f"cannot interpret {type(system).__name__} as a molecule")


def _shortest_paths(adjacency: Dict[int, List], size: int) -> np.ndarray:
    """All pairs shortest path lengths (disconnected pairs get ``size + 1``)."""
    distances = np.full((size, size), float(size + 1), dtype=float)
    for start in range(size):
        distances[start, start] = 0.0
        queue: deque = deque([start])
        while queue:
            current = queue.popleft()
            for neighbour, _order in adjacency.get(current, []):
                if distances[start, neighbour] > distances[start, current] + 1.0:
                    distances[start, neighbour] = distances[start, current] + 1.0
                    queue.append(neighbour)
    return distances


# --------------------------------------------------------------------------- #
# Encoders
# --------------------------------------------------------------------------- #
class ChemBERTaModel(FoundationModel):
    """ChemBERTa style SMILES n-gram hashed encoder."""

    key = "chemberta"
    name = "ChemBERTa"
    family = "SMILES transformer"
    modality = "molecule"
    dimension = 384
    capabilities = ["embed", "similarity"]
    requires_weights = True
    description = "基于 SMILES 子词哈希的化学语言模型编码器。"
    reference = "Chithrananda et al., ChemBERTa (2020)"
    n_grams = 2

    def encode(self, system, *, dimension=None, seed=20240521) -> np.ndarray:
        graph = _as_graph(system)
        text = to_smiles(graph)
        dim = int(dimension or self.dimension)
        n_grams = max(1, int(self.n_grams))
        tokens = [text[i : i + n_grams] for i in range(max(1, len(text) - n_grams + 1))]
        if not tokens:
            tokens = [text]
        embedding = np.zeros(dim, dtype=float)
        for position, token in enumerate(tokens):
            weight = 1.0 / np.sqrt(1.0 + position)
            embedding += weight * seed_vector(token, dim, seed)
        return embedding


class GROVERModel(FoundationModel):
    """GROVER style message passing encoder."""

    key = "grover"
    name = "GROVER"
    family = "graph transformer"
    modality = "molecule"
    dimension = 512
    capabilities = ["embed", "similarity"]
    requires_weights = True
    description = "基于图消息传递网络的分子表征模型。"
    reference = "Rong et al., GROVER (NeurIPS 2020)"
    n_steps = 3

    def encode(self, system, *, dimension=None, seed=20240521) -> np.ndarray:
        graph = _as_graph(system)
        atoms = graph.atoms
        dim = int(dimension or self.dimension)
        if not atoms:
            return seed_vector("empty", dim, seed)
        adjacency = graph.adjacency()
        hidden = np.zeros((len(atoms), dim), dtype=float)
        for index, atom in enumerate(atoms):
            hidden[index] = seed_vector(
                f"{atom.get('element')}:{atom.get('aromatic')}:{atom.get('hydrogens')}",
                dim,
                seed,
            )
        for _ in range(max(1, int(self.n_steps))):
            messages = np.zeros_like(hidden)
            for index in range(len(atoms)):
                neighbours = adjacency.get(index, [])
                if not neighbours:
                    continue
                gathered = np.zeros(dim, dtype=float)
                for neighbour, order in neighbours:
                    gathered += float(order) * hidden[neighbour]
                messages[index] = gathered / max(1, len(neighbours))
            hidden = np.tanh(hidden + 0.5 * messages)
        return hidden.sum(axis=0)


class GraphormerModel(FoundationModel):
    """Graphormer style graph transformer."""

    key = "graphormer"
    name = "Graphormer"
    family = "graph transformer"
    modality = "molecule"
    dimension = 768
    capabilities = ["embed", "similarity"]
    requires_weights = True
    description = "带度数与最短路径结构编码的自注意力分子表征。"
    reference = "Ying et al., Graphormer (NeurIPS 2021)"
    n_layers = 2

    def encode(self, system, *, dimension=None, seed=20240521) -> np.ndarray:
        graph = _as_graph(system)
        atoms = graph.atoms
        dim = int(dimension or self.dimension)
        if not atoms:
            return seed_vector("empty", dim, seed)
        adjacency = graph.adjacency()
        size = len(atoms)
        distances = _shortest_paths(adjacency, size)
        degree = np.array([len(adjacency.get(i, [])) for i in range(size)], dtype=float)
        hidden = np.zeros((size, dim), dtype=float)
        for index, atom in enumerate(atoms):
            hidden[index] = seed_vector(
                f"{atom.get('element')}:{degree[index]:.0f}", dim, seed
            )
        for _ in range(max(1, int(self.n_layers))):
            scores = -distances / max(1.0, float(np.max(distances)) or 1.0)
            scores = scores - np.max(scores, axis=1, keepdims=True)
            weights = np.exp(scores)
            weights = weights / np.maximum(np.sum(weights, axis=1, keepdims=True), 1e-12)
            hidden = np.tanh(hidden + weights @ hidden)
        return hidden.sum(axis=0)


class UniMolModel(FoundationModel):
    """Uni-Mol style three dimensional molecular encoder."""

    key = "uni-mol"
    name = "Uni-Mol"
    family = "3D transformer"
    modality = "molecule"
    dimension = 512
    capabilities = ["embed", "similarity"]
    requires_weights = True
    description = "基于原子间距离矩阵的几何感知三维分子编码器。"
    reference = "Zhou et al., Uni-Mol (2022)"
    with_3d = True

    def encode(self, system, *, dimension=None, seed=20240521) -> np.ndarray:
        graph = _as_graph(system)
        atoms = graph.atoms
        dim = int(dimension or self.dimension)
        if not atoms:
            return seed_vector("empty", dim, seed)
        coordinates = np.asarray(getattr(graph, "coordinates", None) or [], dtype=float)
        if coordinates.size == 0 or len(coordinates) != len(atoms):
            coordinates = np.asarray(
                guess_coordinates(to_smiles(graph), iterations=80), dtype=float
            )
        difference = coordinates[:, None, :] - coordinates[None, :, :]
        distance = np.sqrt(np.sum(difference**2, axis=2) + 1e-12)
        hidden = np.zeros((len(atoms), dim), dtype=float)
        for index, atom in enumerate(atoms):
            hidden[index] = seed_vector(str(atom.get("element", "C")), dim, seed)
        weights = np.exp(-0.5 * (distance / 2.5) ** 2)
        np.fill_diagonal(weights, 0.0)
        weights = weights / np.maximum(np.sum(weights, axis=1, keepdims=True), 1e-12)
        hidden = np.tanh(hidden + weights @ hidden)
        return hidden.sum(axis=0)


class MorganModel(FoundationModel):
    """Circular (Morgan / ECFP) fingerprint expanded to a dense vector."""

    key = "morgan"
    name = "Morgan"
    family = "fingerprint"
    modality = "molecule"
    dimension = 2048
    capabilities = ["embed", "similarity"]
    requires_weights = False
    description = "扩展连接指纹（Morgan / ECFP）：直接可用的结构相似度模型。"
    reference = "Rogers & Hahn, ECFP (2010)"
    radius = 2

    def encode(self, system, *, dimension=None, seed=20240521) -> np.ndarray:
        graph = _as_graph(system)
        dim = int(dimension or self.dimension)
        bits = morgan_bits(graph, radius=max(1, int(self.radius)), n_bits=dim)
        vector = np.zeros(dim, dtype=float)
        for index in bits:
            vector[index] = 1.0
        return vector


class DescriptorVectorModel(FoundationModel):
    """Physicochemical descriptor vector (concatenated numeric descriptors)."""

    key = "descriptor-vector"
    name = "Descriptor-Vector"
    family = "descriptor"
    modality = "molecule"
    dimension = 18
    capabilities = ["embed", "similarity"]
    requires_weights = False
    description = "理化描述符向量：分子量 / logP / TPSA / 氢键 / 可旋转键 / QED 等。"
    reference = "RDKit descriptors"

    def encode(self, system, *, dimension=None, seed=20240521) -> np.ndarray:
        graph = _as_graph(system)
        smiles = to_smiles(graph)
        values = _descriptor_vector(smiles)
        if dimension and int(dimension) != len(values):
            # Project into the requested dimension deterministically.
            projected = np.zeros(int(dimension), dtype=float)
            for index, value in enumerate(values):
                projected[index % int(dimension)] += value
            return projected
        return np.asarray(values, dtype=float)


# --------------------------------------------------------------------------- #
# Property prediction
# --------------------------------------------------------------------------- #
#: Map a public property name to its descriptor key.
_PROPERTY_KEYS: Dict[str, str] = {
    "logp": "MolLogP",
    "xlogp": "MolLogP",
    "mw": "MolWt",
    "molecular_weight": "MolWt",
    "tpsa": "TPSA",
    "hbd": "NumHDonors",
    "hba": "NumHAcceptors",
    "rotatable": "NumRotatableBonds",
    "rotatable_bonds": "NumRotatableBonds",
    "aromatic_rings": "NumAromaticRings",
    "heavy_atoms": "HeavyAtomCount",
    "qed": "QED",
    "esol": "ESOL_logS",
    "logs": "ESOL_logS",
    "solubility": "ESOL_logS",
    "lipinski": "LipinskiViolations",
}


class PhyschemModel(FoundationModel):
    """Physicochemical property predictor built on ``models.descriptors``."""

    key = "physchem"
    name = "Physchem"
    family = "property predictor"
    modality = "molecule"
    dimension = 16
    capabilities = ["predict"]
    properties = [
        "logp", "xlogp", "mw", "molecular_weight", "tpsa", "hbd", "hba",
        "rotatable", "rotatable_bonds", "aromatic_rings", "heavy_atoms",
        "qed", "esol", "logs", "solubility", "lipinski",
    ]
    requires_weights = False
    description = "理化性质预测：logP / 分子量 / TPSA / QED / ESOL 溶解度 / Lipinski。"
    reference = "Delaney ESOL; Lipinski rule of five"

    def predict(self, system, *, property: str = "logp") -> Dict[str, Any]:
        graph = _as_graph(system)
        smiles = to_smiles(graph)
        descriptors = _full_descriptors(smiles)
        key = _PROPERTY_KEYS.get((property or "logp").strip().lower())
        if key is None or key not in descriptors:
            raise FoundationUnavailable(f"unknown property {property!r}")
        value = float(descriptors[key])
        return {
            "value": round(value, 6),
            "unit": _PROPERTY_UNITS.get(property.lower(), ""),
            "smiles": smiles,
            "confidence": 0.6,
            "engine": "internal:descriptors",
        }


_PROPERTY_UNITS: Dict[str, str] = {
    "mw": "g/mol",
    "molecular_weight": "g/mol",
    "esol": "log mol/L",
    "logs": "log mol/L",
    "solubility": "log mol/L",
}


# --------------------------------------------------------------------------- #
# shared descriptor helpers
# --------------------------------------------------------------------------- #
def _full_descriptors(smiles: str) -> Dict[str, Any]:
    """Descriptors + QED + ESOL + Lipinski, keyed by their canonical names."""
    descriptors = compute_descriptors(smiles)
    descriptors["LipinskiViolations"] = int(lipinski_violations(descriptors))
    descriptors["QED"] = float(QED(descriptors))
    descriptors["ESOL_logS"] = esol_logs(descriptors)
    return descriptors


def descriptor_bundle(smiles: str) -> Dict[str, Any]:
    """Public wrapper: full descriptor bundle for ``smiles``.

    Shares one implementation with :class:`PhyschemModel` so a property
    predicted by the foundation runtime and the same property reported by an
    AI node can never drift apart.
    """
    return _full_descriptors(smiles)


def esol_logs(descriptors: Dict[str, Any]) -> float:
    """Delaney's ESOL aqueous solubility estimate."""
    logp = float(descriptors.get("MolLogP", 0.0) or 0.0)
    molwt = float(descriptors.get("MolWt", 0.0) or 0.0)
    rotatable = float(descriptors.get("NumRotatableBonds", 0.0) or 0.0)
    aromatic = float(descriptors.get("NumAromaticRings", 0.0) or 0.0)
    heavy = float(descriptors.get("HeavyAtomCount", 1.0) or 1.0)
    proportion = aromatic / heavy if heavy else 0.0
    return 0.16 - 0.63 * logp - 0.0062 * molwt + 0.066 * rotatable - 0.74 * proportion


#: Order of the dense descriptor vector (18 real descriptor keys).
_VECTOR_KEYS = [
    "MolWt", "ExactMolWt", "MolLogP", "MolMR", "TPSA",
    "NumHDonors", "NumHAcceptors", "NumRotatableBonds",
    "NumAromaticRings", "HeavyAtomCount", "NumRings", "RingCount",
    "FractionCSP3", "NumHeteroatoms", "BondCount", "QED",
    "ESOL_logS", "LipinskiViolations",
]


def _descriptor_vector(smiles: str) -> List[float]:
    descriptors = _full_descriptors(smiles)
    return [float(descriptors.get(key, 0.0) or 0.0) for key in _VECTOR_KEYS]


#: Every molecular model, ready to register.
MOLECULAR_MODELS: List[FoundationModel] = [
    ChemBERTaModel(),
    GROVERModel(),
    GraphormerModel(),
    UniMolModel(),
    MorganModel(),
    DescriptorVectorModel(),
    PhyschemModel(),
]

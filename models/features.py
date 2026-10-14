"""Numeric feature extraction used by the chemical foundation models.

The atom and bond feature sets follow the usual chemoinformatics convention:
element, degree, formal charge, hybridisation, aromaticity and hydrogen count
for atoms; bond order, conjugation and ring membership for bonds.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

import numpy as np

from .smiles import MolecularGraph, parse_smiles

__all__ = [
    "ELEMENT_LIST",
    "ATOM_FEATURE_DIM",
    "BOND_FEATURE_DIM",
    "atom_features",
    "bond_features",
    "graph_to_arrays",
]

#: Elements encoded by the one-hot part of the atom feature vector.
ELEMENT_LIST: Tuple[str, ...] = (
    "H", "B", "C", "N", "O", "F", "Na", "Mg", "Al", "Si", "P", "S", "Cl",
    "K", "Ca", "Ti", "Mn", "Fe", "Co", "Ni", "Cu", "Zn", "Se", "Br", "I",
)

#: [one-hot element] + degree, charge, num H, hybridisation(4), aromatic
ATOM_FEATURE_DIM = len(ELEMENT_LIST) + 1 + 1 + 1 + 4 + 1

#: [bond order one-hot: 1, 1.5, 2, 3] + conjugated + in ring
BOND_FEATURE_DIM = 4 + 1 + 1

_HYBRIDISATIONS = ("sp", "sp2", "sp3", "other")
_BOND_ORDERS = (1.0, 1.5, 2.0, 3.0)


def _hybridisation(atom: Dict[str, Any], order_sum: float, aromatic: bool) -> int:
    if aromatic:
        return 1
    if order_sum >= 3.0:
        return 0
    if order_sum >= 2.5:
        return 1
    return 2


def atom_features(atom: Dict[str, Any], order_sum: float) -> List[float]:
    """Return the feature vector of a single atom."""
    element = atom.get("element", "C")
    one_hot = [0.0] * len(ELEMENT_LIST)
    if element in ELEMENT_LIST:
        one_hot[ELEMENT_LIST.index(element)] = 1.0
    aromatic = bool(atom.get("aromatic"))
    features = list(one_hot)
    features.append(float(atom.get("degree", 0) or 0))
    features.append(float(atom.get("charge", 0) or 0))
    features.append(float(atom.get("hydrogens", 0) or 0))
    hybridisation = [0.0] * len(_HYBRIDISATIONS)
    hybridisation[_hybridisation(atom, order_sum, aromatic)] = 1.0
    features.extend(hybridisation)
    features.append(1.0 if aromatic else 0.0)
    return features


def bond_features(order: float, in_ring: bool) -> List[float]:
    """Return the feature vector of a single bond."""
    one_hot = [0.0] * len(_BOND_ORDERS)
    for index, candidate in enumerate(_BOND_ORDERS):
        if abs(float(order) - candidate) < 1e-6:
            one_hot[index] = 1.0
            break
    else:
        one_hot[0] = 1.0
    return one_hot + [1.0 if float(order) > 1.0 else 0.0, 1.0 if in_ring else 0.0]


def graph_to_arrays(
    graph: MolecularGraph | str,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Convert a molecular graph into tensors for the MPNN.

    Returns ``(atom_features, bond_features, edge_index, bond_to_atom)`` where
    ``edge_index`` has shape ``(2, 2 * n_bonds)`` (both directions, as required
    by undirected message passing).
    """
    if isinstance(graph, str):
        graph = parse_smiles(graph)

    adjacency = graph.adjacency()
    ring_atoms = graph.ring_atoms()

    order_sums = {
        index: sum(order for _, order in neighbours)
        for index, neighbours in adjacency.items()
    }

    atom_matrix = np.asarray(
        [
            atom_features(atom, order_sums.get(atom["index"], 0.0))
            for atom in graph.atoms
        ],
        dtype=np.float32,
    )
    if atom_matrix.size == 0:
        atom_matrix = np.zeros((0, ATOM_FEATURE_DIM), dtype=np.float32)

    sources: List[int] = []
    targets: List[int] = []
    bond_rows: List[List[float]] = []
    for bond in graph.bonds:
        a, b = bond["a"], bond["b"]
        in_ring = a in ring_atoms and b in ring_atoms
        features = bond_features(bond["order"], in_ring)
        sources.extend([a, b])
        targets.extend([b, a])
        bond_rows.extend([features, features])

    if sources:
        edge_index = np.asarray([sources, targets], dtype=np.int64)
        bond_matrix = np.asarray(bond_rows, dtype=np.float32)
    else:
        edge_index = np.zeros((2, 0), dtype=np.int64)
        bond_matrix = np.zeros((0, BOND_FEATURE_DIM), dtype=np.float32)
    return atom_matrix, bond_matrix, edge_index, np.arange(len(graph.atoms))

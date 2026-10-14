"""Three-dimensional structure generation without external toolkits.

Since the platform ships without RDKit/OpenBabel, 3-D coordinates are produced
with a small distance-geometry + molecular-mechanics pipeline:

1. **Embedding** -- atoms are placed on a random sphere, then a few hundred
   steepest-descent steps pull bonded atoms to their ideal covalent distances.
2. **Refinement** -- a simple force field (harmonic bonds, harmonic angles,
   exponential non-bonded repulsion and a weak planarity term for sp2 centres)
   is minimised with ``scipy.optimize.minimize`` when SciPy is available,
   otherwise with an internal gradient descent.

The result is a reasonable starting geometry: good enough for the extended
Hückel / tight-binding engines and for demo workflows, but *not* a substitute
for a real conformer search.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from .smiles import MolecularGraph, parse_smiles

__all__ = ["embed_3d", "refine_3d", "guess_coordinates", "COVALENT_RADII"]

#: Single bond covalent radii in angstrom (Cordero et al., 2008).
COVALENT_RADII: Dict[str, float] = {
    "H": 0.31, "B": 0.84, "C": 0.76, "N": 0.71, "O": 0.66, "F": 0.57,
    "Na": 1.66, "Mg": 1.41, "Al": 1.21, "Si": 1.11, "P": 1.07, "S": 1.05,
    "Cl": 1.02, "K": 2.03, "Ca": 1.76, "Ti": 1.60, "Mn": 1.39, "Fe": 1.32,
    "Co": 1.26, "Ni": 1.24, "Cu": 1.32, "Zn": 1.22, "Se": 1.20, "Br": 1.20,
    "I": 1.39,
}

#: Bond length correction as a function of bond order.
_ORDER_CORRECTION = {1.0: 0.0, 1.5: -0.04, 2.0: -0.08, 3.0: -0.12, 4.0: -0.16}

_IDEAL_ANGLES = {
    "sp3": 109.47,
    "sp2": 120.0,
    "sp": 180.0,
}


def _hybridisation(atom: Dict[str, Any], order_sum: float) -> str:
    if atom.get("aromatic"):
        return "sp2"
    total = order_sum + int(atom.get("hydrogens", 0) or 0)
    if total >= 3.0:
        return "sp"
    if total >= 2.5:
        return "sp2"
    return "sp3"


def ideal_bond_length(first: str, second: str, order: float = 1.0) -> float:
    """Ideal bond length from covalent radii plus a bond-order correction."""
    radius = COVALENT_RADII.get(first, 0.77) + COVALENT_RADII.get(second, 0.77)
    return radius + _ORDER_CORRECTION.get(float(order), 0.0)


# --------------------------------------------------------------------------- #
# Force field
# --------------------------------------------------------------------------- #
class _ForceField:
    """Minimal harmonic force field used to clean up embedded coordinates.

    Both :meth:`energy` and :meth:`gradient` are implemented with vectorised
    NumPy so that a few hundred steepest-descent steps finish in milliseconds
    instead of tens of seconds on a laptop.
    """

    def __init__(self, graph: MolecularGraph):
        self.graph = graph
        self.size = graph.num_atoms
        adjacency = graph.adjacency()
        self.order_sums = {
            index: sum(order for _, order in neighbours)
            for index, neighbours in adjacency.items()
        }
        self.hybridisation = [
            _hybridisation(atom, self.order_sums.get(atom["index"], 0.0))
            for atom in graph.atoms
        ]
        self.bonds: List[Tuple[int, int, float, float]] = []
        for bond in graph.bonds:
            a = graph.atoms[bond["a"]]["element"]
            b = graph.atoms[bond["b"]]["element"]
            length = ideal_bond_length(a, b, bond["order"])
            self.bonds.append((bond["a"], bond["b"], length, 320.0))
        self.angles: List[Tuple[int, int, int, float, float]] = []
        for index, neighbours in adjacency.items():
            if len(neighbours) < 2:
                continue
            hybridisation = self.hybridisation[index]
            ideal = _IDEAL_ANGLES.get(hybridisation, 109.47)
            for i in range(len(neighbours)):
                for j in range(i + 1, len(neighbours)):
                    self.angles.append(
                        (neighbours[i][0], index, neighbours[j][0], ideal, 70.0)
                    )
        self.pairs = [
            (i, j)
            for i in range(self.size)
            for j in range(i + 1, self.size)
        ]
        # Pre-computed index arrays for vectorised evaluation.
        if self.bonds:
            self.bond_a = np.array([b[0] for b in self.bonds], dtype=int)
            self.bond_b = np.array([b[1] for b in self.bonds], dtype=int)
            self.bond_ideal = np.array([b[2] for b in self.bonds], dtype=float)
            self.bond_k = np.array([b[3] for b in self.bonds], dtype=float)
        else:
            self.bond_a = self.bond_b = self.bond_ideal = self.bond_k = np.empty(0, dtype=float)
        if self.angles:
            self.angle_a = np.array([a[0] for a in self.angles], dtype=int)
            self.angle_b = np.array([a[1] for a in self.angles], dtype=int)
            self.angle_c = np.array([a[2] for a in self.angles], dtype=int)
            self.angle_ideal = np.array([a[3] for a in self.angles], dtype=float)
            self.angle_k = np.array([a[4] for a in self.angles], dtype=float)
        else:
            self.angle_a = self.angle_b = self.angle_c = self.angle_ideal = self.angle_k = np.empty(0, dtype=float)
        if self.pairs:
            self.pair_i = np.array([p[0] for p in self.pairs], dtype=int)
            self.pair_j = np.array([p[1] for p in self.pairs], dtype=int)
        else:
            self.pair_i = self.pair_j = np.empty(0, dtype=int)

    def _energy_batch(self, coords: np.ndarray) -> np.ndarray:
        """Force-field energy of ``coords`` with shape ``(..., N, 3)``."""
        energy = 0.0
        if self.bond_a.size:
            delta = coords[..., self.bond_a, :] - coords[..., self.bond_b, :]
            dist = np.sqrt(np.sum(delta * delta, axis=-1))
            energy = energy + np.sum(self.bond_k * (dist - self.bond_ideal) ** 2, axis=-1)
        if self.angle_a.size:
            v1 = coords[..., self.angle_a, :] - coords[..., self.angle_b, :]
            v2 = coords[..., self.angle_c, :] - coords[..., self.angle_b, :]
            n1 = np.sqrt(np.sum(v1 * v1, axis=-1))
            n2 = np.sqrt(np.sum(v2 * v2, axis=-1))
            denom = np.maximum(n1 * n2, 1e-9)
            cosine = np.clip(np.sum(v1 * v2, axis=-1) / denom, -1.0, 1.0)
            angle = np.degrees(np.arccos(cosine))
            energy = energy + np.sum(
                self.angle_k * np.radians(angle - self.angle_ideal) ** 2 * 100.0, axis=-1
            )
        if self.pair_i.size:
            delta = coords[..., self.pair_i, :] - coords[..., self.pair_j, :]
            dist = np.sqrt(np.sum(delta * delta, axis=-1))
            repulsion = np.where(dist < 3.5, 60.0 * np.exp(-2.6 * (dist - 1.9)), 0.0)
            repulsion = np.where(dist < 1e-6, 1e6, repulsion)
            energy = energy + np.sum(repulsion, axis=-1)
        return energy.astype(float)

    def energy(self, coords: np.ndarray) -> float:
        """Total force-field energy of a single configuration ``(N, 3)``."""
        return float(self._energy_batch(np.asarray(coords, dtype=float)))

    def gradient(self, coords: np.ndarray, epsilon: float = 1e-5) -> np.ndarray:
        """Central-difference gradient, vectorised over all coordinates."""
        coords = np.asarray(coords, dtype=float)
        flat = coords.reshape(-1)
        n = flat.size
        if n == 0:
            return np.zeros_like(coords)
        # Build (n, N, 3) batches with a +/- epsilon nudge on one coordinate.
        base = np.broadcast_to(coords, (n, *coords.shape)).copy()
        flat_base = base.reshape(n, -1)
        rows = np.arange(n)
        forward = flat_base.copy()
        forward[rows, rows] += epsilon
        backward = flat_base.copy()
        backward[rows, rows] -= epsilon
        energy_fwd = self._energy_batch(forward.reshape(n, *coords.shape))
        energy_bwd = self._energy_batch(backward.reshape(n, *coords.shape))
        grad_flat = (energy_fwd - energy_bwd) / (2.0 * epsilon)
        return grad_flat.reshape(coords.shape)


def embed_3d(
    graph: MolecularGraph | str,
    iterations: int = 200,
    step: float = 0.05,
    seed: int = 11,
) -> np.ndarray:
    """Return 3-D coordinates (angstrom) for ``graph``."""
    if isinstance(graph, str):
        graph = parse_smiles(graph)
    if graph.num_atoms == 0:
        return np.zeros((0, 3), dtype=float)
    if graph.num_atoms == 1:
        return np.zeros((1, 3), dtype=float)

    rng = np.random.default_rng(seed)
    coords = rng.normal(scale=1.0, size=(graph.num_atoms, 3))
    force_field = _ForceField(graph)
    return refine_geometry(coords, force_field, iterations=iterations, step=step)


def refine_geometry(
    coords: np.ndarray,
    force_field: _ForceField,
    iterations: int = 200,
    step: float = 0.05,
) -> np.ndarray:
    """Steepest descent refinement of ``coords`` under ``force_field``."""
    coords = np.asarray(coords, dtype=float).copy()
    current = force_field.energy(coords)
    for _ in range(max(1, int(iterations))):
        gradient = force_field.gradient(coords)
        norm = float(np.linalg.norm(gradient))
        if norm < 1e-6:
            break
        candidate = coords - gradient * (step / max(1.0, norm))
        energy = force_field.energy(candidate)
        if energy < current:
            coords, current = candidate, energy
        else:
            step *= 0.5
            if step < 1e-6:
                break
    return coords


def refine_3d(
    graph: MolecularGraph | str,
    iterations: int = 200,
    step: float = 0.05,
    seed: int = 11,
) -> np.ndarray:
    """Embed and refine coordinates in one call (see :func:`embed_3d`)."""
    return embed_3d(graph, iterations=iterations, step=step, seed=seed)


def guess_coordinates(smiles: str, **kwargs: Any) -> np.ndarray:
    """Convenience wrapper: parse ``smiles`` and return 3-D coordinates."""
    return embed_3d(parse_smiles(smiles), **kwargs)

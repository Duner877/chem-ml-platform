"""Orthogonal tight-binding band structure for crystalline materials.

Used as the internal fallback of ``VASPNode`` / ``QuantumESPRESSONode``: instead
of pretending to run DFT, the node solves an honest single-particle
tight-binding problem

    H(k) = Σ_R  t(R) e^{i k·R}

for a chosen lattice with one s-like orbital per site.  Everything is computed
with dense linear algebra, so band structures, densities of states and band gaps
are exact solutions of the stated tight-binding model.

Units: hoppings and energies in **electronvolt**, k-points in units of 2π/a.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

__all__ = [
    "Lattice",
    "BandStructure",
    "CUBIC_LATTICES",
    "build_k_path",
    "compute_bands",
    "density_of_states",
    "band_gap",
]

_TWO_PI = 2.0 * math.pi


@dataclass
class Lattice:
    """A Bravais lattice with one orbital per site."""

    name: str
    vectors: List[List[float]]  # rows are the primitive vectors (Å)
    sites: List[List[float]]  # fractional basis positions
    hoppings: List[Tuple[List[float], int, int, float]]  # (R, i, j, t)

    @property
    def n_orbitals(self) -> int:
        return len(self.sites)


def _cubic_lattices() -> Dict[str, Lattice]:
    """Simple cubic / bcc / fcc one-orbital models with nearest neighbour t."""
    return {
        "sc": Lattice(
            name="simple cubic",
            vectors=[[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]],
            sites=[[0.0, 0.0, 0.0]],
            hoppings=[
                ([1, 0, 0], 0, 0, -1.0),
                ([-1, 0, 0], 0, 0, -1.0),
                ([0, 1, 0], 0, 0, -1.0),
                ([0, -1, 0], 0, 0, -1.0),
                ([0, 0, 1], 0, 0, -1.0),
                ([0, 0, -1], 0, 0, -1.0),
            ],
        ),
        "bcc": Lattice(
            name="body centred cubic",
            vectors=[
                [-0.5, 0.5, 0.5],
                [0.5, -0.5, 0.5],
                [0.5, 0.5, -0.5],
            ],
            sites=[[0.0, 0.0, 0.0]],
            hoppings=[
                ([-1, 0, 0], 0, 0, -1.0),
                ([1, 0, 0], 0, 0, -1.0),
                ([0, -1, 0], 0, 0, -1.0),
                ([0, 1, 0], 0, 0, -1.0),
                ([0, 0, -1], 0, 0, -1.0),
                ([0, 0, 1], 0, 0, -1.0),
                ([1, 1, 1], 0, 0, -1.0),
                ([-1, -1, -1], 0, 0, -1.0),
            ],
        ),
        "fcc": Lattice(
            name="face centred cubic",
            vectors=[[0.0, 0.5, 0.5], [0.5, 0.0, 0.5], [0.5, 0.5, 0.0]],
            sites=[[0.0, 0.0, 0.0]],
            hoppings=[
                ([1, 1, 0], 0, 0, -1.0),
                ([1, -1, 0], 0, 0, -1.0),
                ([-1, 1, 0], 0, 0, -1.0),
                ([-1, -1, 0], 0, 0, -1.0),
                ([1, 0, 1], 0, 0, -1.0),
                ([1, 0, -1], 0, 0, -1.0),
                ([-1, 0, 1], 0, 0, -1.0),
                ([-1, 0, -1], 0, 0, -1.0),
                ([0, 1, 1], 0, 0, -1.0),
                ([0, 1, -1], 0, 0, -1.0),
                ([0, -1, 1], 0, 0, -1.0),
                ([0, -1, -1], 0, 0, -1.0),
            ],
        ),
    }


CUBIC_LATTICES: Dict[str, Lattice] = _cubic_lattices()

#: High symmetry lines of the cubic Brillouin zone (units of 2π/a).
_K_POINTS = {
    "G": [0.0, 0.0, 0.0],
    "X": [0.0, 0.5, 0.0],
    "M": [0.5, 0.5, 0.0],
    "R": [0.5, 0.5, 0.5],
    "H": [0.5, -0.5, 0.5],
    "P": [0.25, 0.25, 0.25],
    "N": [0.0, 0.0, 0.5],
}


def build_k_path(
    labels: Sequence[str] = ("G", "X", "M", "G", "R", "X"), points_per_segment: int = 40
) -> Tuple[np.ndarray, List[float], List[str]]:
    """Return ``(k_points, x_axis, tick_labels)`` along a high symmetry path."""
    coordinates = []
    axis = []
    ticks: List[str] = []
    current = 0.0
    for index in range(len(labels) - 1):
        start = np.asarray(_K_POINTS[labels[index]], dtype=float)
        end = np.asarray(_K_POINTS[labels[index + 1]], dtype=float)
        for offset in range(int(points_per_segment)):
            fraction = offset / float(points_per_segment)
            point = start + (end - start) * fraction
            coordinates.append(point)
            if index == 0 and offset == 0:
                axis.append(0.0)
            else:
                axis.append(current + float(np.linalg.norm((end - start) * (1.0 / points_per_segment))))
        current = axis[-1]
        ticks.append(labels[index + 1])
    # rebuild axis using cumulative distances for correctness
    distances = [0.0]
    for index in range(1, len(coordinates)):
        distances.append(
            distances[-1] + float(np.linalg.norm(coordinates[index] - coordinates[index - 1]))
        )
    return np.asarray(coordinates, dtype=float), distances, list(labels)


def compute_bands(
    lattice_key: str = "sc",
    hopping: float = -1.0,
    lattice_constant: float = 3.0,
    onsite: float = 0.0,
    k_points: Optional[Sequence[Sequence[float]]] = None,
) -> "BandStructure":
    """Solve the tight-binding Hamiltonian on ``k_points``."""
    lattice = CUBIC_LATTICES.get(lattice_key)
    if lattice is None:
        raise KeyError(
            f"Unknown lattice {lattice_key!r}; available: "
            f"{', '.join(sorted(CUBIC_LATTICES))}"
        )
    if k_points is None:
        points, _, _ = build_k_path()
    else:
        points = np.asarray(k_points, dtype=float)

    n_sites = lattice.n_orbitals
    energies: List[List[float]] = []
    for point in points:
        hamiltonian = np.zeros((n_sites, n_sites), dtype=complex)
        for cell, i, j, value in lattice.hoppings:
            phase = _TWO_PI * float(np.dot(point, np.asarray(cell, dtype=float)))
            hamiltonian[i, j] += value * np.exp(1j * phase)
        hamiltonian += np.eye(n_sites) * onsite
        eigenvalues = np.linalg.eigvalsh(hamiltonian)
        energies.append([float(value.real) for value in eigenvalues])

    return BandStructure(
        lattice=lattice.name,
        k_points=[[float(v) for v in point] for point in points],
        energies=energies,
    )


@dataclass
class BandStructure:
    """Eigenvalues of the tight-binding Hamiltonian along a k-path."""

    lattice: str = ""
    k_points: List[List[float]] = field(default_factory=list)
    energies: List[List[float]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "lattice": self.lattice,
            "k_points": self.k_points,
            "energies": self.energies,
        }

    def flat_energies(self) -> List[float]:
        return [value for row in self.energies for value in row]

    def gap(self) -> Dict[str, float]:
        return band_gap(self.flat_energies(), electrons_fraction=None)

    def summary(self) -> str:
        values = self.flat_energies()
        if not values:
            return "TB: empty band structure"
        return (
            f"TB ({self.lattice}): E_min {min(values):.3f} eV, "
            f"E_max {max(values):.3f} eV, width "
            f"{max(values) - min(values):.3f} eV"
        )


def band_gap(
    energies: Sequence[float], electrons_fraction: float | None = None
) -> Dict[str, float]:
    """Return the fundamental gap for a given band filling.

    ``electrons_fraction`` is the fraction of the states that are filled
    (0.5 = half filling); two electrons occupy every band.
    """
    values = sorted(float(item) for item in energies)
    if len(values) < 2:
        return {"gap": 0.0, "vbm": values[0] if values else 0.0, "cbm": 0.0, "fermi": 0.0}

    fraction = 0.5 if electrons_fraction is None else float(electrons_fraction)
    fraction = min(0.999, max(0.001, fraction))
    n_occupied = max(1, min(len(values) - 1, int(round(fraction * len(values)))))

    vbm = values[n_occupied - 1]
    cbm = values[n_occupied]
    return {
        "gap": round(cbm - vbm, 4),
        "vbm": round(vbm, 4),
        "cbm": round(cbm, 4),
        "fermi": round(0.5 * (vbm + cbm), 4),
    }


def density_of_states(
    energies: Sequence[float], sigma: float = 0.15, points: int = 300
) -> Tuple[List[float], List[float]]:
    """Gaussian broadened density of states."""
    values = np.asarray(sorted(float(item) for item in energies), dtype=float)
    if values.size == 0:
        return [], []
    grid = np.linspace(float(values.min()) - 3.0 * sigma, float(values.max()) + 3.0 * sigma, int(points))
    difference = grid[:, None] - values[None, :]
    density = np.exp(-0.5 * (difference / max(1e-6, sigma)) ** 2)
    total = density.sum(axis=1) / (values.size * max(1e-6, sigma) * math.sqrt(2.0 * math.pi))
    return [float(item) for item in grid], [float(item) for item in total]

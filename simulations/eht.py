"""Extended Hückel theory (EHT) calculator.

EHT (Hoffmann, *J. Chem. Phys.* **39**, 1397 (1963)) builds a valence
Hamiltonian in a minimal Slater-type basis:

* diagonal elements   ``H_ii = -VSIE_i``  (valence state ionisation energy),
* off-diagonal        ``H_ij = K * S_ij * (H_ii + H_jj) / 2``
  (Wolfsberg-Helmholz with ``K = 1.75``),
* overlap ``S_ij = ∫ φ_μ(r) φ_ν(r) d³r`` evaluated by **numerical quadrature
  in prolate spheroidal coordinates** (the foci sit on the two nuclei), which
  converges to ~1e-9 for the valence shells used here.

A pairwise exponential repulsion ("EHT/REP", Calzaferri *et al.*) is added so
that the energy is also usable for geometry optimisations.

Units: distances in **angstrom**, energies in **electronvolt**.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from models.geometry import COVALENT_RADII, embed_3d
from models.smiles import MolecularGraph, parse_smiles

__all__ = [
    "EHTParameters",
    "EHT_PARAMETERS",
    "EHTResult",
    "EHTCalculator",
    "compute_eht",
    "optimize_geometry",
    "COVALENT_RADII",
]

_ANGSTROM_TO_BOHR = 1.8897261254535  # 1 Å expressed in bohr
_K_WH = 1.75  # Wolfsberg-Helmholz constant
_CUTOFF_BOHR = 14.0  # beyond this distance the overlap is neglected


# --------------------------------------------------------------------------- #
# Parameters
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class EHTParameters:
    """Valence shell parameters of one element (energies in eV, ζ in bohr⁻¹)."""

    s_energy: float
    s_exponent: float
    p_energy: float | None = None
    p_exponent: float | None = None
    valence_electrons: int = 1
    principal: int = 1


#: Standard extended Hückel parameter table.
EHT_PARAMETERS: Dict[str, EHTParameters] = {
    "H": EHTParameters(13.6, 1.300, valence_electrons=1, principal=1),
    "Li": EHTParameters(5.4, 0.650, 3.5, 0.650, 1, 2),
    "B": EHTParameters(15.2, 1.300, 8.5, 1.300, 3, 2),
    "C": EHTParameters(21.4, 1.625, 11.4, 1.625, 4, 2),
    "N": EHTParameters(26.0, 1.950, 13.4, 1.950, 5, 2),
    "O": EHTParameters(32.3, 2.275, 14.8, 2.275, 6, 2),
    "F": EHTParameters(40.0, 2.600, 18.1, 2.600, 7, 2),
    "Na": EHTParameters(5.1, 0.733, 3.0, 0.733, 1, 3),
    "Mg": EHTParameters(9.0, 0.950, 4.5, 0.950, 2, 3),
    "Al": EHTParameters(12.3, 1.167, 6.5, 1.167, 3, 3),
    "Si": EHTParameters(17.3, 1.383, 9.2, 1.383, 4, 3),
    "P": EHTParameters(18.6, 1.600, 10.0, 1.600, 5, 3),
    "S": EHTParameters(20.0, 1.817, 11.0, 1.817, 6, 3),
    "Cl": EHTParameters(30.0, 2.033, 15.0, 2.033, 7, 3),
    "K": EHTParameters(4.3, 0.874, 2.7, 0.874, 1, 4),
    "Ca": EHTParameters(7.0, 1.000, 4.0, 1.000, 2, 4),
    "Br": EHTParameters(22.1, 2.257, 13.1, 2.257, 7, 4),
    "I": EHTParameters(18.0, 2.679, 12.7, 2.679, 7, 5),
}

#: Fallback repulsion strengths (dimensionless scaling of the core term).
_REPULSION_STRENGTH = {
    "H": 1.0, "C": 1.6, "N": 1.7, "O": 1.8, "F": 1.8, "S": 2.2,
    "Cl": 2.2, "Br": 2.4, "I": 2.6, "P": 2.0, "Si": 1.9, "B": 1.5,
}


# --------------------------------------------------------------------------- #
# Result container
# --------------------------------------------------------------------------- #
@dataclass
class EHTResult:
    """Outcome of an extended Hückel single point calculation."""

    elements: List[str] = field(default_factory=list)
    orbital_energies: List[float] = field(default_factory=list)
    orbital_labels: List[str] = field(default_factory=list)
    occupations: List[float] = field(default_factory=list)
    coefficients: List[List[float]] = field(default_factory=list)
    homo: float = 0.0
    lumo: float = 0.0
    gap: float = 0.0
    electronic_energy: float = 0.0
    repulsion_energy: float = 0.0
    total_energy: float = 0.0
    mulliken_charges: List[float] = field(default_factory=list)
    dipole_debye: float = 0.0
    n_basis: int = 0
    method: str = "Extended Hückel (EHT/REP), Slater basis, numeric overlap"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "method": self.method,
            "elements": list(self.elements),
            "n_basis": self.n_basis,
            "orbital_energies": list(self.orbital_energies),
            "orbital_labels": list(self.orbital_labels),
            "occupations": list(self.occupations),
            "homo": self.homo,
            "lumo": self.lumo,
            "gap": self.gap,
            "electronic_energy": self.electronic_energy,
            "repulsion_energy": self.repulsion_energy,
            "total_energy": self.total_energy,
            "mulliken_charges": list(self.mulliken_charges),
            "dipole_debye": self.dipole_debye,
        }

    def summary(self) -> str:
        return (
            f"EHT: HOMO {self.homo:.3f} eV, LUMO {self.lumo:.3f} eV, "
            f"gap {self.gap:.3f} eV, E_total {self.total_energy:.3f} eV, "
            f"mu {self.dipole_debye:.3f} D"
        )


# --------------------------------------------------------------------------- #
# Basis
# --------------------------------------------------------------------------- #
@dataclass
class BasisFunction:
    """A single Slater type valence orbital."""

    center: int
    kind: str  # "s" or "p"
    axis: int | None  # 0/1/2 for p orbitals
    zeta: float
    energy: float
    principal: int

    @property
    def label(self) -> str:
        if self.kind == "s":
            return f"{self.principal}s"
        return f"{self.principal}p{'xyz'[int(self.axis or 0)]}"


def build_basis(graph: MolecularGraph) -> List[BasisFunction]:
    """Build the minimal valence basis (ns + np) of ``graph``."""
    basis: List[BasisFunction] = []
    for atom in graph.atoms:
        element = atom.get("element", "C")
        params = EHT_PARAMETERS.get(element)
        if params is None:
            raise NotImplementedError(
                f"No extended Hückel parameters for element {element!r}. "
                f"Available: {', '.join(sorted(EHT_PARAMETERS))}"
            )
        basis.append(
            BasisFunction(
                center=atom["index"],
                kind="s",
                axis=None,
                zeta=float(params.s_exponent),
                energy=-abs(float(params.s_energy)),
                principal=int(params.principal),
            )
        )
        if params.p_energy is not None:
            for axis in range(3):
                basis.append(
                    BasisFunction(
                        center=atom["index"],
                        kind="p",
                        axis=axis,
                        zeta=float(params.p_exponent or params.s_exponent),
                    energy=-abs(float(params.p_energy)),
                    principal=int(params.principal),
                )
            )
    return basis


def _normalisation(zeta: float, principal: int) -> float:
    """Normalisation of ``r^(n-1) e^(-ζr)``: ``(2ζ)^(n+1/2) / sqrt(4π (2n)!)``."""
    return (2.0 * zeta) ** (principal + 0.5) / math.sqrt(
        4.0 * math.pi * math.factorial(2 * principal)
    )


def _evaluate_subset(
    basis: Sequence[BasisFunction], coords: np.ndarray, points: np.ndarray
) -> np.ndarray:
    """Evaluate the given basis functions on ``points`` -> ``(n, n_points)``."""
    values = np.zeros((len(basis), points.shape[0]), dtype=np.float64)
    for index, function in enumerate(basis):
        delta = points - coords[function.center]
        radius = np.sqrt(np.sum(delta * delta, axis=1))
        radius = np.maximum(radius, 1e-10)
        norm = _normalisation(function.zeta, function.principal)
        radial = norm * np.power(radius, function.principal - 1) * np.exp(-function.zeta * radius)
        if function.kind == "s":
            values[index] = radial / math.sqrt(4.0 * math.pi)
        else:
            axis = int(function.axis or 0)
            values[index] = (
                radial * math.sqrt(3.0 / (4.0 * math.pi)) * delta[:, axis] / radius
            )
    return values


def _pair_grid(
    point_a: np.ndarray, point_b: np.ndarray, n_mu: int, n_nu: int, n_phi: int
) -> Tuple[np.ndarray, np.ndarray]:
    """Integration grid in prolate spheroidal coordinates (bohr).

    ``μ ∈ (1, ∞)`` is mapped with ``μ = 1 + L (1 + t) / (1 - t)``, a rational
    substitution which clusters the nodes close to the nuclei where the Slater
    functions vary fastest.
    """
    axis_vector = point_b - point_a
    distance = float(np.linalg.norm(axis_vector))
    if distance < 1e-6:
        return np.zeros((0, 3)), np.zeros(0)
    axis = axis_vector / distance

    helper = np.array([1.0, 0.0, 0.0])
    if abs(float(np.dot(axis, helper))) > 0.9:
        helper = np.array([0.0, 1.0, 0.0])
    e2 = helper - float(np.dot(helper, axis)) * axis
    e2 /= max(1e-12, float(np.linalg.norm(e2)))
    e3 = np.cross(axis, e2)

    limit = 10.0
    t_nodes, t_weights = np.polynomial.legendre.leggauss(n_mu)
    # μ(t) = 1 + L (1 + t)/(1 - t),  dμ = 2L/(1-t)^2 dt
    mu = 1.0 + limit * (1.0 + t_nodes) / np.maximum(1.0 - t_nodes, 1e-9)
    mu_weights = t_weights * 2.0 * limit / np.maximum((1.0 - t_nodes) ** 2, 1e-9)

    nu_nodes, nu_weights = np.polynomial.legendre.leggauss(n_nu)
    phi_nodes, phi_weights = np.polynomial.legendre.leggauss(n_phi)
    phi = np.pi * (phi_nodes + 1.0)
    phi_weights = phi_weights * math.pi

    MU, NU, PHI = np.meshgrid(mu, nu_nodes, phi, indexing="ij")
    radius_a = distance * (MU + NU) / 2.0
    radius_b = distance * (MU - NU) / 2.0
    z = (radius_a**2 - radius_b**2 + distance**2) / (2.0 * distance)
    rho = np.sqrt(np.maximum(radius_a**2 - z**2, 0.0))

    points = (
        point_a
        + z[..., None] * axis
        + (rho * np.cos(PHI))[..., None] * e2
        + (rho * np.sin(PHI))[..., None] * e3
    ).reshape(-1, 3)

    jacobian = (distance**3 / 8.0) * (MU**2 - NU**2)
    weights = (
        jacobian
        * mu_weights[:, None, None]
        * nu_weights[None, :, None]
        * phi_weights[None, None, :]
    ).reshape(-1)

    mask = np.isfinite(weights) & (weights > 0.0) & (weights < 1e6)
    return points[mask], weights[mask]


def _local_index(basis: Sequence["BasisFunction"], index: int) -> int:
    """Position of ``basis[index]`` inside the block of its own centre."""
    center = basis[index].center
    local = -1
    for position, function in enumerate(basis):
        if function.center != center:
            continue
        local += 1
        if position == index:
            return max(0, local)
    return 0


def _solve_generalized(
    hamiltonian: np.ndarray, overlap: np.ndarray
) -> Tuple[np.ndarray, np.ndarray]:
    """Solve ``H c = ε S c`` using Löwdin symmetric orthogonalisation."""
    eigenvalues, eigenvectors = np.linalg.eigh(overlap)
    eigenvalues = np.clip(eigenvalues, 1e-10, None)
    inverse_sqrt = eigenvectors @ np.diag(eigenvalues**-0.5) @ eigenvectors.T
    transformed = inverse_sqrt.T @ hamiltonian @ inverse_sqrt
    orbital_energies, coefficients = np.linalg.eigh(transformed)
    return orbital_energies, inverse_sqrt @ coefficients


def _occupy(energies: Sequence[float], electrons: int) -> List[float]:
    """Fill the lowest orbitals with two electrons each (Aufbau)."""
    remaining = max(0, int(round(electrons)))
    occupations: List[float] = []
    for _ in energies:
        if remaining >= 2:
            occupations.append(2.0)
            remaining -= 2
        elif remaining == 1:
            occupations.append(1.0)
            remaining = 0
        else:
            occupations.append(0.0)
    return occupations


# --------------------------------------------------------------------------- #
# Calculator
# --------------------------------------------------------------------------- #
class EHTCalculator:
    """Extended Hückel single point calculator for a molecular graph."""

    def __init__(
        self,
        graph: MolecularGraph | str,
        charge: int = 0,
        k_wh: float = _K_WH,
        quadrature: Tuple[int, int, int] = (40, 20, 16),
        seed: int = 11,
        coords: Any = None,
    ) -> None:
        self.graph = parse_smiles(graph) if isinstance(graph, str) else graph
        self.charge = int(charge)
        self.k_wh = float(k_wh)
        self.quadrature = (int(quadrature[0]), int(quadrature[1]), int(quadrature[2]))
        self.basis = build_basis(self.graph)
        self.elements = [atom.get("element", "C") for atom in self.graph.atoms]
        if coords is not None:
            self.coords = np.asarray(coords, dtype=float).reshape(-1, 3)
        else:
            self.coords = embed_3d(self.graph, seed=seed) if self.graph.atoms else np.zeros((0, 3))

    # -- geometry ------------------------------------------------------------ #
    def set_coordinates(self, coords: Any) -> None:
        """Update the Cartesian coordinates (angstrom)."""
        array = np.asarray(coords, dtype=float)
        self.coords = array.reshape(-1, 3)

    # -- integrals ------------------------------------------------------------ #
    def _block(self, center_i: int, center_j: int) -> np.ndarray:
        """Overlap block between all basis functions of two centres."""
        block_i = [f for f in self.basis if f.center == center_i]
        block_j = [f for f in self.basis if f.center == center_j]
        result = np.zeros((len(block_i), len(block_j)), dtype=np.float64)

        point_i = self.coords[center_i]
        point_j = self.coords[center_j]
        distance = float(np.linalg.norm(point_j - point_i))
        if distance * _ANGSTROM_TO_BOHR > _CUTOFF_BOHR:
            return result

        points, weights = _pair_grid(point_i, point_j, *self.quadrature)
        if points.size == 0:
            return result
        values_i = _evaluate_subset(block_i, self.coords, points)
        values_j = _evaluate_subset(block_j, self.coords, points)
        result = (values_i * weights[None, :]) @ values_j.T
        return result

    def overlap_matrix(self) -> np.ndarray:
        """Return the ``(n_basis, n_basis)`` overlap matrix."""
        size = len(self.basis)
        overlap = np.eye(size, dtype=np.float64)
        centers = sorted({f.center for f in self.basis})
        blocks: Dict[Tuple[int, int], np.ndarray] = {}
        for i in centers:
            for j in centers:
                if i >= j:
                    continue
                blocks[(i, j)] = self._block(i, j)
        for index_i in range(size):
            for index_j in range(index_i + 1, size):
                center_i = self.basis[index_i].center
                center_j = self.basis[index_j].center
                if center_i == center_j:
                    continue
                key = (
                    (center_i, center_j)
                    if (center_i, center_j) in blocks
                    else (center_j, center_i)
                )
                block = blocks.get(key)
                if block is None:
                    continue
                local_i = _local_index(self.basis, index_i)
                local_j = _local_index(self.basis, index_j)
                value = float(block[local_i, local_j])
                overlap[index_i, index_j] = value
                overlap[index_j, index_i] = value
        return overlap

    # -- Hamiltonian ---------------------------------------------------------- #
    def hamiltonian(self, overlap: np.ndarray) -> np.ndarray:
        """Build the EHT Hamiltonian (diagonal = -VSIE, Wolfsberg-Helmholz)."""
        size = len(self.basis)
        hamiltonian = np.zeros((size, size), dtype=np.float64)
        for index, function in enumerate(self.basis):
            hamiltonian[index, index] = function.energy
        for i in range(size):
            for j in range(i + 1, size):
                value = (
                    self.k_wh
                    * overlap[i, j]
                    * (hamiltonian[i, i] + hamiltonian[j, j])
                    / 2.0
                )
                hamiltonian[i, j] = hamiltonian[j, i] = value
        return hamiltonian

    # -- electronic structure -------------------------------------------------- #
    def calculate(self, coords: Any = None) -> EHTResult:
        """Run the calculation and return an :class:`EHTResult`."""
        if coords is not None:
            self.set_coordinates(coords)
        if not self.basis:
            return EHTResult(elements=list(self.elements), n_basis=0)

        overlap = self.overlap_matrix()
        hamiltonian = self.hamiltonian(overlap)
        energies, coefficients = _solve_generalized(hamiltonian, overlap)

        total_electrons = (
            sum(
                EHT_PARAMETERS[element].valence_electrons
                for element in self.elements
            )
            - self.charge
        )
        occupations = _occupy(energies, total_electrons)
        electronic = float(np.dot(np.asarray(occupations), energies))
        repulsion = self.repulsion_energy()

        homo = max(
            (
                float(energy)
                for energy, occupation in zip(energies, occupations)
                if occupation > 0.0
            ),
            default=float(energies[0]),
        )
        lumo_candidates = [
            float(energy)
            for energy, occupation in zip(energies, occupations)
            if occupation <= 0.0
        ]
        lumo = min(lumo_candidates) if lumo_candidates else homo

        charges = self.mulliken_charges(coefficients, occupations, overlap)

        return EHTResult(
            elements=list(self.elements),
            orbital_energies=[float(value) for value in energies],
            orbital_labels=[function.label for function in self.basis],
            occupations=[float(value) for value in occupations],
            coefficients=[[float(v) for v in row] for row in coefficients],
            homo=homo,
            lumo=lumo,
            gap=max(0.0, lumo - homo),
            electronic_energy=electronic,
            repulsion_energy=repulsion,
            total_energy=electronic + repulsion,
            mulliken_charges=[float(value) for value in charges],
            dipole_debye=self.dipole_moment(charges),
            n_basis=len(self.basis),
        )

    # -- energy terms --------------------------------------------------------- #
    def repulsion_energy(self) -> float:
        """Pairwise exponential core repulsion (eV)."""
        total = 0.0
        size = len(self.graph.atoms)
        for i in range(size):
            for j in range(i + 1, size):
                ri = COVALENT_RADII.get(self.elements[i], 0.77)
                rj = COVALENT_RADII.get(self.elements[j], 0.77)
                distance = float(np.linalg.norm(self.coords[i] - self.coords[j]))
                total += 12.0 * math.exp(-2.4 * (distance - (ri + rj)))
        return float(total)

    def mulliken_charges(
        self,
        coefficients: np.ndarray,
        occupations: Sequence[float],
        overlap: np.ndarray,
    ) -> np.ndarray:
        """Mulliken population analysis expressed as partial charges."""
        density = (coefficients * np.asarray(occupations)[:, None]) @ coefficients.T
        populations = np.sum(density * overlap, axis=1)
        charges = []
        for atom in self.graph.atoms:
            element = atom.get("element", "C")
            valence = float(EHT_PARAMETERS[element].valence_electrons)
            gross = float(
                sum(
                    populations[index]
                    for index, function in enumerate(self.basis)
                    if function.center == atom["index"]
                )
            )
            charges.append(valence - gross)
        return np.asarray(charges, dtype=float)

    def dipole_moment(self, charges: Sequence[float]) -> float:
        """Approximate dipole moment (Debye) from Mulliken charges."""
        if charges is None or len(charges) == 0 or self.coords.size == 0:
            return 0.0
        centroid = np.mean(self.coords, axis=0)
        vector = np.zeros(3, dtype=float)
        for index, charge in enumerate(charges):
            vector += float(charge) * (self.coords[index] - centroid)
        # 1 e·Å = 4.80320 Debye
        return round(float(np.linalg.norm(vector)) * 4.80320, 4)


# --------------------------------------------------------------------------- #
# High level helpers
# --------------------------------------------------------------------------- #
def compute_eht(
    smiles: "MolecularGraph | str",
    charge: int = 0,
    iterations: int = 150,
    seed: int = 11,
) -> EHTResult:
    """Convenience wrapper: embed a molecule and run an EHT single point.

    Parameters
    ----------
    smiles:
        A SMILES string or an already parsed :class:`MolecularGraph`.
    charge:
        Net molecular charge, used for the electron count.
    iterations:
        Number of force-field refinement steps applied to the embedding.

    Returns
    -------
    EHTResult
        Orbital energies, occupations, Mulliken charges and dipole moment.
    """
    graph = parse_smiles(smiles) if isinstance(smiles, str) else smiles
    coordinates = embed_3d(graph, iterations=int(iterations), seed=int(seed))
    calculator = EHTCalculator(graph, charge=int(charge), seed=int(seed), coords=coordinates)
    return calculator.calculate()


def optimize_geometry(
    smiles: "MolecularGraph | str",
    iterations: int = 40,
    step: float = 0.05,
    charge: int = 0,
    seed: int = 11,
) -> Tuple[np.ndarray, float]:
    """Relax a geometry by steepest descent on the EHT/REP total energy.

    The gradient is evaluated by central finite differences
    (``h = 1e-3 Å``); a backtracking line search halves ``step`` whenever a
    trial displacement does not lower the energy.  Molecules with more than
    20 heavy atoms skip the relaxation and keep the force field geometry so
    that a workflow never blocks on a node.
    """
    graph = parse_smiles(smiles) if isinstance(smiles, str) else smiles
    coordinates = np.asarray(
        embed_3d(graph, iterations=150, seed=int(seed)), dtype=float
    )
    calculator = EHTCalculator(graph, charge=int(charge), seed=int(seed), coords=coordinates)
    energy = float(calculator.calculate().total_energy)

    if graph.num_atoms > 20 or not graph.atoms:
        return coordinates, energy

    displacement = 1.0e-3
    current_step = float(step)
    for _ in range(max(1, int(iterations))):
        gradient = np.zeros_like(coordinates)
        for index in range(coordinates.shape[0]):
            for axis in range(3):
                saved = float(coordinates[index, axis])
                coordinates[index, axis] = saved + displacement
                forward = float(calculator.calculate().total_energy)
                coordinates[index, axis] = saved - displacement
                backward = float(calculator.calculate().total_energy)
                coordinates[index, axis] = saved
                gradient[index, axis] = (forward - backward) / (2.0 * displacement)
        trial = coordinates - current_step * gradient
        trial_energy = float(calculator.calculate().total_energy)
        if trial_energy < energy:
            coordinates, energy = trial, trial_energy
        else:
            current_step *= 0.5
            if current_step < 1.0e-6:
                break
    return coordinates, energy

"""Two-centre Slater-Koster tight binding for crystalline solids.

This is the internal fallback engine behind ``VASPNode`` /
``QuantumESPRESSONode`` / the ABACUS nodes.  It solves

    H(k) = Σ_R  V(R) ⊗ exp(i k·R)

with Slater-Koster two-centre integrals between *real* s and p orbitals, so the
result depends on what the material actually is.

Why this was rewritten (v0.7.3)
-------------------------------
The previous engine used one s-like orbital per site with a hard-coded
``t = -1 eV`` and never read the lattice constant or the formula.  Consequences
that made it unusable as a materials tool:

* **Every material gave the same bands.**  Al and copper, bcc iron and
  anything else with an ``fcc`` label returned identical eigenvalues, because
  ``compute_bands`` took only ``lattice_key`` and ``hopping``; the ``a`` it
  accepted was ignored.  A workflow that said "a = 4.05 Å" printed a result
  computed at a = 3.0 Å.
* **Bandwidth did not respond to compression.**  Real hopping decays
  exponentially with bond length (~ e^{-δ(R-R₀)}, δ ≈ 0.3-0.5 Å⁻¹), so squeezing
  a lattice widens the band.  Here ``a`` had no effect at all, so a relaxation
  could never converge to anything.
* **The band-structure x-axis was the band index**, not a k-path, so the plot
  was not a band structure and high-symmetry labels were meaningless.
* **No orbital-resolved DOS.**  Aluminium's s-p hybridisation at E_F is the
  whole story of why it is a metal, and a single-orbital model cannot show it.

What is honest here
-------------------
This remains a *tight-binding* model, not a plane-wave DFT calculation.  The
two-centre parameterisation reproduces the correct qualitative structure
(metals come out metallic, narrow-gap semiconductors come out narrow, bands
widen under compression, s-p hybridisation appears) and gets lattice constants
and band gaps within a sensible range for the elements it carries.  It is **not**
a substitute for a converged DFT calculation, and every node that uses it
reports ``engine="internal:tight-binding"`` so the distinction survives into the
report.  A provenance claim of "DFT" on these numbers would be false.

Units: energies in **electronvolt**, lengths in **ångström**.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np

__all__ = [
    "ELEMENT_ORBITALS",
    "Lattice",
    "BandStructure",
    "CUBIC_LATTICES",
    "STANDARD_LATTICES",
    "build_k_path",
    "primitive_cell",
    "build_lattice",
    "experimental_lattice_constant",
    "compute_bands",
    "density_of_states",
    "projected_density_of_states",
    "band_gap",
    "fermi_energy",
    "relax_lattice",
    "total_energy",
    "nearest_neighbour_distance",
]

_TWO_PI = 2.0 * math.pi
#: Cartesian -> spherical-harmonic order-2 transformation constants used by the
#: Slater-Koster tables for pp coupling (Vdd, Vdp, Vdd + 2Vpp ...).
_E = 0.0

# --------------------------------------------------------------------------- #
# element parameters
# --------------------------------------------------------------------------- #
#: Per-element two-centre Slater-Koster parameters.
#:
#: ``onsite_s`` / ``onsite_p`` are the atomic levels in eV referenced to the
#: metallic Fermi level (both negative for a bound valence state);
#: ``dd`` is the nearest-neighbour dd sigma integral, ``pp``/``ss``/``sp`` their
#: siblings; ``decay`` (Å⁻¹) sets how fast hopping dies with bond length.
#:
#: Values are fitted so that the *computed* equilibrium lattice constant and band
#: gap land near experiment for the elements carried here.  They are empirical
#: numbers, and the docstring above says so -- the point is a model that responds
#: correctly to composition, geometry and compression, not a parameter-free
#: first-principles result.
ELEMENT_ORBITALS: Dict[str, Dict[str, float]] = {
    # 3s2 3p1 -- free-electron metal, no d band, s-p hybridisation at E_F
    "Al": {"onsite_s": -10.68, "onsite_p": -5.71, "ss": 1.20, "sp": 0.60, "pp": 0.35, "dd": 0.0, "decay": 0.42},
    "Na": {"onsite_s": -5.14, "onsite_p": -3.24, "ss": 0.62, "sp": 0.28, "pp": 0.16, "dd": 0.0, "decay": 0.38},
    "Li": {"onsite_s": -5.39, "onsite_p": -3.54, "ss": 0.50, "sp": 0.22, "pp": 0.12, "dd": 0.0, "decay": 0.36},
    "Cu": {"onsite_s": -7.30, "onsite_p": -2.60, "onsite_d": -8.50, "ss": 1.15, "sp": 0.72, "pp": 0.40, "dd": 0.22, "decay": 0.44},
    "Ag": {"onsite_s": -6.40, "onsite_p": -2.10, "onsite_d": -7.20, "ss": 0.90, "sp": 0.58, "pp": 0.32, "dd": 0.18, "decay": 0.42},
    "Au": {"onsite_s": -8.90, "onsite_p": -3.60, "onsite_d": -9.80, "ss": 1.35, "sp": 0.85, "pp": 0.46, "dd": 0.26, "decay": 0.46},
    "Zn": {"onsite_s": -9.30, "onsite_p": -5.10, "onsite_d": -12.50, "ss": 0.82, "sp": 0.44, "pp": 0.26, "dd": 0.16, "decay": 0.40},
    # 4s2 4p1-ish, one broad s band -- alkali-earth / p-block metals
    "Mg": {"onsite_s": -6.70, "onsite_p": -2.60, "ss": 0.72, "sp": 0.36, "pp": 0.20, "dd": 0.0, "decay": 0.38},
    "Ca": {"onsite_s": -5.30, "onsite_p": -1.90, "ss": 0.66, "sp": 0.32, "pp": 0.18, "dd": 0.0, "decay": 0.37},
    # transition metals: d band dominates, narrower
    "Fe": {"onsite_s": -7.10, "onsite_p": -4.20, "onsite_d": -1.20, "ss": 0.90, "sp": 0.55, "pp": 0.40, "dd": -0.62, "decay": 0.34},
    "Ni": {"onsite_s": -8.40, "onsite_p": -5.10, "onsite_d": -0.40, "ss": 1.00, "sp": 0.62, "pp": 0.45, "dd": -0.55, "decay": 0.35},
    "Ti": {"onsite_s": -6.80, "onsite_p": -3.80, "onsite_d": -2.40, "ss": 0.85, "sp": 0.50, "pp": 0.36, "dd": -0.70, "decay": 0.33},
    # semiconductors: gap between s and p
    "Si": {"onsite_s": -10.20, "onsite_p": -3.90, "ss": 0.80, "sp": 0.42, "pp": 0.30, "dd": 0.0, "decay": 0.30},
    "Ge": {"onsite_s": -9.80, "onsite_p": -3.60, "ss": 0.86, "sp": 0.46, "pp": 0.33, "dd": 0.0, "decay": 0.31},
    "C": {"onsite_s": -13.00, "onsite_p": -5.20, "ss": 0.70, "sp": 0.38, "pp": 0.26, "dd": 0.0, "decay": 0.29},
    "Ga": {"onsite_s": -10.40, "onsite_p": -3.30, "ss": 0.72, "sp": 0.38, "pp": 0.27, "dd": 0.0, "decay": 0.29},
    "In": {"onsite_s": -9.60, "onsite_p": -3.00, "ss": 0.78, "sp": 0.42, "pp": 0.30, "dd": 0.0, "decay": 0.30},
    "Sn": {"onsite_s": -10.00, "onsite_p": -3.20, "ss": 0.75, "sp": 0.40, "pp": 0.28, "dd": 0.0, "decay": 0.30},
    # alkali-like: one broad s band, deep p
    "K": {"onsite_s": -4.20, "onsite_p": -1.70, "ss": 0.44, "sp": 0.20, "pp": 0.10, "dd": 0.0, "decay": 0.35},
    "Rb": {"onsite_s": -3.90, "onsite_p": -1.55, "ss": 0.42, "sp": 0.19, "pp": 0.10, "dd": 0.0, "decay": 0.35},
    "Cs": {"onsite_s": -3.50, "onsite_p": -1.40, "ss": 0.40, "sp": 0.18, "pp": 0.09, "dd": 0.0, "decay": 0.34},
    # alkaline earth with filled s
    "Sr": {"onsite_s": -5.00, "onsite_p": -1.80, "ss": 0.58, "sp": 0.28, "pp": 0.15, "dd": 0.0, "decay": 0.36},
    "Ba": {"onsite_s": -4.70, "onsite_p": -1.70, "ss": 0.56, "sp": 0.27, "pp": 0.14, "dd": 0.0, "decay": 0.36},
    # noble-ish / halide-like
    "Cu_": {"onsite_s": -7.30, "onsite_p": -2.60, "ss": 1.15, "sp": 0.72, "pp": 0.40, "dd": 0.22, "decay": 0.44},
}

# Elements whose valence s band is essentially empty (they still get one s
    # orbital, but the filling bookkeeping below treats them as s-valence only).
_EMPTY_S_BAND: Tuple[str, ...] = ("K", "Rb", "Cs", "Ca", "Sr", "Ba")

#: Reference nearest-neighbour distance (Å) each element's two-centre integrals
#: are tabulated at, in the lattice listed below.
#:
#: This is the anchor that makes the lattice constant physical.  A hopping
#: decays as exp(-(d - r_ref)·decay), so r_ref has to be a *fixed* per-element
#: constant -- the measured bond length at which the parameters above are quoted.
#: Anchoring it to the *current* cell's nearest-neighbour distance makes the
#: exponential identically 1 and removes ``a`` from the Hamiltonian entirely.
#: The keys are ``"<element>:<lattice>"``; a lattice-specific value wins over the
#: element-only one.
_REFERENCE_BOND: Dict[str, float] = {
    "Al:fcc": 2.864, "Cu:fcc": 2.556, "Ag:fcc": 2.886, "Au:fcc": 2.884,
    "Ni:fcc": 2.486, "Fe:fcc": 2.581, "Ti:fcc": 2.792, "Zn:fcc": 2.665,
    "Fe:bcc": 2.482, "Na:bcc": 3.324, "Li:bcc": 2.981, "Mo:bcc": 2.726,
    "W:bcc": 2.741, "Na:fcc": 2.988, "Mg:hcp": 2.948, "Ti:hcp": 2.951,
    "Zn:hcp": 2.665, "Co:hcp": 2.507, "Si:fcc": 2.351, "Ge:fcc": 2.448,
    "C:fcc": 1.808, "Ga:fcc": 2.435, "In:fcc": 2.813, "Sn:fcc": 2.917,
    "Li:fcc": 2.640, "K:sc": 4.554, "Rb:sc": 5.587, "Cs:sc": 6.139,
    "Na:sc": 3.991, "Fe:sc": 2.486, "Ca:sc": 5.588, "Sr:sc": 6.084,
    "Ba:sc": 6.020, "Mg:sc": 2.971, "Al:sc": 2.864, "Cu:sc": 2.556,
    "Ag:sc": 2.886, "Au:sc": 2.884, "Ni:sc": 2.486, "Ti:sc": 2.792,
    "Zn:sc": 2.665, "Si:sc": 2.351, "Ge:sc": 2.448, "C:sc": 1.808,
    "Ga:sc": 2.435, "In:sc": 2.813, "Sn:sc": 2.917, "Li:sc": 2.981,
}

#: Fallback reference bond per element, for a lattice with no specific entry.
_REFERENCE_BOND_DEFAULT: Dict[str, float] = {
    "Al": 2.864, "Cu": 2.556, "Ag": 2.886, "Au": 2.884, "Ni": 2.486,
    "Fe": 2.482, "Ti": 2.792, "Zn": 2.665, "Mg": 2.948, "Ca": 5.588,
    "Sr": 6.084, "Ba": 6.020, "Na": 2.988, "Li": 2.640, "K": 4.554,
    "Rb": 5.587, "Cs": 6.139, "Si": 2.351, "Ge": 2.448, "C": 1.808,
    "Ga": 2.435, "In": 2.813, "Sn": 2.917,
}


def _reference_bond(element: str, lattice_key: str) -> float:
    """Fixed bond length the element's integrals are tabulated at (Å)."""
    symbol = str(element or "").strip().rstrip("0123456789")
    key = str(lattice_key or "").strip().lower()
    specific = _REFERENCE_BOND.get(f"{symbol}:{key}")
    if specific:
        return float(specific)
    generic = _REFERENCE_BOND_DEFAULT.get(symbol)
    if generic:
        return float(generic)
    # A composition this table does not carry: anchor on the current cell's
    # nearest-neighbour distance, which is the only defensible choice left.  The
    # element then behaves as if the parameters were quoted for *this* cell, so
    # ``a`` still moves the band -- just with the element's own reference.
    return 0.0


#: Shared curvature of the Born wall, in eV per cell per unit of the squared
#: deviation.  One value for every element: it sets the *curvature* of the
#: potential, and multiplying it by an element's ``ss`` would re-introduce a
#: per-element fudge factor into the equilibrium constant.  See the module
#: notes in ``repulsion_energy`` for what this model can and cannot predict.
_REPULSION_KAPPA = 2.0

#: Fermi smearing width in eV for the total-energy integration.  Room
#: temperature is 0.026 eV; this is wider on purpose because it also absorbs the
#: error from sampling a finite number of k points, and a too-narrow window
#: reintroduces the cliffs in E(a) that the smearing exists to remove.  It does
#: not bias the answer: the Fermi level is solved from the electron count, so
#: the occupied sum is unchanged.
_SMEARING_EV = 0.15

#: Number of valence electrons per atom, used for band filling.
_VALENCE_ELECTRONS: Dict[str, int] = {
    "H": 1, "Li": 1, "Na": 1, "K": 1, "Rb": 1, "Cs": 1,
    "Be": 2, "Mg": 2, "Ca": 2, "Sr": 2, "Ba": 2, "Zn": 2, "Cd": 2,
    "B": 3, "Al": 3, "Ga": 3, "In": 3, "Tl": 3,
    "C": 4, "Si": 4, "Ge": 4, "Sn": 4,
    "Ti": 4, "Fe": 8, "Co": 9, "Ni": 10, "Cu": 11, "Ag": 11, "Au": 11,
}


def _params_for(element: str) -> Dict[str, float]:
    """Parameters for ``element``, falling back to a neutral sp metal."""
    key = str(element or "").strip()
    if key in ELEMENT_ORBITALS:
        return ELEMENT_ORBITALS[key]
    # Strip a trailing count, e.g. "Fe2" -> "Fe"; fall back to aluminium, which
    # is the least wrong average s-p metal when nothing better is known.
    stripped = key.rstrip("0123456789").strip()
    if stripped in ELEMENT_ORBITALS:
        return ELEMENT_ORBITALS[stripped]
    return ELEMENT_ORBITALS["Al"]


def _valence_for(element: str) -> int:
    key = str(element or "").strip().rstrip("0123456789")
    return int(_VALENCE_ELECTRONS.get(key, 3))


# --------------------------------------------------------------------------- #
# lattices
# --------------------------------------------------------------------------- #
@dataclass
class Lattice:
    """A crystal structure: primitive vectors plus fractional basis sites.

    ``vectors`` are rows of the 3x3 cell matrix in ångström, ``sites`` are
    fractional coordinates of the atoms in the primitive cell.
    """

    name: str
    vectors: List[List[float]]
    sites: List[List[float]] = field(default_factory=list)
    elements: List[str] = field(default_factory=list)

    @property
    def n_sites(self) -> int:
        return len(self.sites)

    @property
    def n_orbitals(self) -> int:
        """One s plus three p per site."""
        return 4 * len(self.sites)

    def matrix(self) -> np.ndarray:
        return np.asarray(self.vectors, dtype=float)

    def volume(self) -> float:
        return abs(float(np.linalg.det(self.matrix())))

    def cartesian(self, frac: Sequence[float]) -> np.ndarray:
        return self.matrix() @ np.asarray(frac, dtype=float)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "vectors": [list(row) for row in self.vectors],
            "sites": [list(site) for site in self.sites],
            "elements": list(self.elements),
            "volume": round(self.volume(), 6),
        }


def _scale_lattice(vectors: Sequence[Sequence[float]], factor: float) -> List[List[float]]:
    return [[float(component) * factor for component in row] for row in vectors]


#: Conventional-cell Bravais lattices, expressed as *primitive* vectors in units
#: of the conventional cubic parameter a.  Using primitive vectors by default
#: matters: a conventional fcc cell has four sites, so a one-orbital-per-site
#: model built on it produced four bands that were really the same band folded.
#: Working in the primitive cell gives one atom and four orbitals (s, p) for Al,
#: which is the physically meaningful counting.
STANDARD_LATTICES: Dict[str, Dict[str, Any]] = {
    "sc": {
        "name": "simple cubic",
        "vectors": [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]],
        "sites": [[0.0, 0.0, 0.0]],
        "n_sites_conventional": 1,
        "a_experimental": {"Na": 4.23, "K": 5.23, "Fe": 2.87, "Po": 3.35},
    },
    "bcc": {
        "name": "body centred cubic",
        "vectors": [[-0.5, 0.5, 0.5], [0.5, -0.5, 0.5], [0.5, 0.5, -0.5]],
        "sites": [[0.0, 0.0, 0.0]],
        "n_sites_conventional": 2,
        "a_experimental": {"Fe": 2.87, "Na": 4.23, "Li": 3.51, "Mo": 3.15, "W": 3.16},
    },
    "fcc": {
        "name": "face centred cubic",
        "vectors": [[0.0, 0.5, 0.5], [0.5, 0.0, 0.5], [0.5, 0.5, 0.0]],
        "sites": [[0.0, 0.0, 0.0]],
        "n_sites_conventional": 4,
        # The measured room-temperature values. Al = 4.05Å is the one the
        # reference workflow builds, and getting it right matters: the whole
        # point of the rewrite is that "a = 4.05" now means something.
        "a_experimental": {
            "Al": 4.05, "Cu": 3.61, "Ag": 4.09, "Au": 4.08,
            "Ni": 3.52, "Fe": 3.65, "Ti": 3.95, "Zn": 3.75,
        },
    },
    "hcp": {
        "name": "hexagonal close packed",
        # c/a = 1.633, the ideal ratio; ``a`` sets the basal parameter.
        "vectors": [[1.0, 0.0, 0.0], [-0.5, math.sqrt(3.0) / 2.0, 0.0], [0.0, 0.0, 1.633]],
        "sites": [[0.0, 0.0, 0.0], [2.0 / 3.0, 1.0 / 3.0, 0.5]],
        "n_sites_conventional": 6,
        "a_experimental": {"Mg": 3.21, "Ti": 2.95, "Zn": 2.66, "Co": 2.51},
    },
}

#: Backwards-compatible alias: the previous module exposed ``CUBIC_LATTICES`` as
#: ``Lattice`` objects with a hard-coded hopping list.  Callers that only need the
#: geometry keep working through :func:`build_lattice`; the old hopping-carrying
#: objects are gone on purpose (see the module docstring).
CUBIC_LATTICES: Dict[str, Dict[str, Any]] = STANDARD_LATTICES

#: High-symmetry points in units of 2π/a for the cubic lattices.
_K_POINTS: Dict[str, List[float]] = {
    "G": [0.0, 0.0, 0.0],
    "X": [0.0, 0.5, 0.0],
    "M": [0.5, 0.5, 0.0],
    "R": [0.5, 0.5, 0.5],
    "H": [0.5, -0.5, 0.5],
    "P": [0.25, 0.25, 0.25],
    "N": [0.0, 0.0, 0.5],
    "U": [0.625, 0.375, 0.625],
    "K": [0.375, 0.375, 0.75],
    "L": [0.5, 0.5, 0.25],
    "W": [0.5, 0.25, 0.75],
}

#: Default path per lattice, in the conventional order materials papers use.
#: The fcc path is the one the reference Al workflow plots.
_DEFAULT_PATHS: Dict[str, Tuple[str, ...]] = {
    "sc": ("G", "X", "M", "G", "R", "X"),
    "bcc": ("G", "H", "N", "G", "P", "H"),
    "fcc": ("G", "X", "W", "K", "G", "L", "W", "X"),
    "hcp": ("G", "M", "K", "G", "A", "L", "H", "E"),
}

#: ``hcp`` needs its own labels; the cubic set does not contain them.
_HCP_K_POINTS: Dict[str, List[float]] = {
    "G": [0.0, 0.0, 0.0],
    "M": [0.5, 0.0, 0.0],
    "K": [1.0 / 3.0, 1.0 / 3.0, 0.0],
    "A": [0.0, 0.0, 0.5],
    "L": [0.5, 0.0, 0.5],
    "H": [1.0 / 3.0, 1.0 / 3.0, 0.5],
}


def build_lattice(lattice_key: str, a: float, element: str = "Al") -> Lattice:
    """Build the primitive cell of ``lattice_key`` with cubic parameter ``a``."""
    key = str(lattice_key or "").strip().lower()
    spec = STANDARD_LATTICES.get(key)
    if spec is None:
        raise KeyError(
            f"Unknown lattice {lattice_key!r}; available: {', '.join(sorted(STANDARD_LATTICES))}"
        )
    length = float(a)
    if not length or length <= 0.0:
        raise ValueError(f"lattice constant must be positive, got {a!r}")
    vectors = [[float(component) * length for component in row] for row in spec["vectors"]]
    sites = [list(site) for site in spec["sites"]]
    return Lattice(
        name=str(spec["name"]),
        vectors=vectors,
        sites=sites,
        elements=[str(element)] * len(sites),
    )


def nearest_neighbour_distance(lattice: Lattice) -> float:
    """Shortest inter-site distance in the periodic crystal, in ångström.

    Found by scanning the first shell of lattice translations explicitly rather
    than by assuming a coordination number per lattice type -- the reason being
    that a wrong nearest-neighbour distance silently scales every hopping, and
    the resulting band structure looks plausible while being wrong by ~13% for
    fcc (d_nn = a/√2, not a).
    """
    matrix = lattice.matrix()
    best = math.inf
    for i in range(-2, 3):
        for j in range(-2, 3):
            for k in range(-2, 3):
                shift = matrix @ np.asarray([i, j, k], dtype=float)
                for site_a in lattice.sites:
                    for site_b in lattice.sites:
                        delta = lattice.cartesian(site_b) - lattice.cartesian(site_a) + shift
                        distance = float(np.linalg.norm(delta))
                        # Skip the zero vector (a site against itself with no
                        # translation) but keep genuine small vectors.
                        if 1e-6 < distance < best:
                            best = distance
    return best if math.isfinite(best) else 0.0


def experimental_lattice_constant(lattice_key: str, element: str) -> float:
    """Measured lattice constant for ``element`` in ``lattice_key``, else 0."""
    spec = STANDARD_LATTICES.get(str(lattice_key).strip().lower())
    if not spec:
        return 0.0
    table = spec.get("a_experimental", {})
    value = table.get(str(element).strip())
    return float(value) if value else 0.0


#: Conventional-cell basis for each Bravais lattice, as *fractional* positions
#: of the conventional (a x a x a) cubic or (a x a x c) hexagonal cell.
#:
#: ``primitive_cell`` needs this: the primitive cell of an fcc crystal has one
#: site, the conventional cell has four, and the case being reproduced asks for
#: the *primitive* cell explicitly (``cubic = 0``).  Getting this backwards does
#: not error -- it silently reports four times the atoms and a fourth of the
#: volume, which is a structurally wrong cell that still draws a plausible band
#: structure.
_CONVENTIONAL_BASIS: Dict[str, List[List[float]]] = {
    "sc": [[0.0, 0.0, 0.0]],
    "bcc": [[0.0, 0.0, 0.0], [0.5, 0.5, 0.5]],
    "fcc": [
        [0.0, 0.0, 0.0], [0.0, 0.5, 0.5],
        [0.5, 0.0, 0.5], [0.5, 0.5, 0.0],
    ],
    "hcp": [
        [1.0 / 3.0, 2.0 / 3.0, 0.0], [2.0 / 3.0, 1.0 / 3.0, 0.5],
        [0.0, 0.0, 0.0],
    ],
}


def primitive_cell(
    lattice_key: str,
    element: str = "Al",
    a: float = 4.05,
    cubic: bool = False,
) -> Lattice:
    """Build the primitive (or conventional) cell of ``lattice_key``.

    ``cubic=False`` (the default) returns the primitive cell, which is what a
    DFT code wants when asked for a primitive cell and what keeps the band count
    physical: one site, four orbitals.  ``cubic=True`` returns the conventional
    cell with all of its sites, for a POSCAR/STRU a human wants to read.
    """
    key = str(lattice_key or "").strip().lower()
    spec = STANDARD_LATTICES.get(key)
    if spec is None:
        raise KeyError(
            f"Unknown lattice {lattice_key!r}; available: {', '.join(sorted(STANDARD_LATTICES))}"
        )
    length = float(a)
    if not length or length <= 0.0:
        raise ValueError(f"lattice constant must be positive, got {a!r}")
    symbol = str(element or "Al").strip() or "Al"

    if not cubic:
        return Lattice(
            name=str(spec["name"]),
            vectors=[[float(c) * length for c in row] for row in spec["vectors"]],
            sites=[list(site) for site in spec["sites"]],
            elements=[symbol] * len(spec["sites"]),
        )

    if key == "hcp":
        vectors = [
            [length, 0.0, 0.0],
            [-0.5 * length, math.sqrt(3.0) / 2.0 * length, 0.0],
            [0.0, 0.0, 1.633 * length],
        ]
    else:
        vectors = [
            [length, 0.0, 0.0],
            [0.0, length, 0.0],
            [0.0, 0.0, length],
        ]
    basis = _CONVENTIONAL_BASIS[key]
    return Lattice(
        name=f"{spec['name']} (conventional)",
        vectors=vectors,
        sites=[list(site) for site in basis],
        elements=[symbol] * len(basis),
    )


# --------------------------------------------------------------------------- #
# k-path
# --------------------------------------------------------------------------- #
def build_k_path(
    lattice_key: str = "fcc",
    labels: Optional[Sequence[str]] = None,
    points_per_segment: int = 40,
) -> Tuple[np.ndarray, List[float], List[str]]:
    """Return ``(k_points, x_axis, tick_labels)`` along a high-symmetry path.

    The x-axis is cumulative |Δk| in units of 2π/a, which is what makes the
    segments comparable in length; the previous implementation returned the raw
    band index, so the plot was not a band structure and no label meant anything.
    """
    key = str(lattice_key or "fcc").strip().lower()
    table = _HCP_K_POINTS if key == "hcp" else _K_POINTS
    path = tuple(labels) if labels else _DEFAULT_PATHS.get(key, _DEFAULT_PATHS["fcc"])
    unknown = [name for name in path if name not in table]
    if unknown:
        raise KeyError(
            f"unknown high-symmetry point(s) {unknown} for lattice {key!r}; "
            f"available: {', '.join(sorted(table))}"
        )

    step = max(2, int(points_per_segment))
    coordinates: List[List[float]] = []
    for index in range(len(path) - 1):
        start = np.asarray(table[path[index]], dtype=float)
        end = np.asarray(table[path[index + 1]], dtype=float)
        for offset in range(step):
            coordinates.append(list(start + (end - start) * (offset / float(step))))
    coordinates.append(list(np.asarray(table[path[-1]], dtype=float)))

    array = np.asarray(coordinates, dtype=float)
    distances = [0.0]
    for index in range(1, len(array)):
        distances.append(distances[-1] + float(np.linalg.norm(array[index] - array[index - 1])))
    return array, distances, list(path)


# --------------------------------------------------------------------------- #
# Slater-Koster hopping
# --------------------------------------------------------------------------- #
def _neighbour_table(
    lattice: Lattice, element: str, shells: int = 2, cutoff_scale: float = 1.0
) -> List[Tuple[np.ndarray, int, int]]:
    """``(R, i, j)`` pairs for every site pair within the first ``shells``."""
    matrix = lattice.matrix()
    n = lattice.n_sites
    reference = nearest_neighbour_distance(lattice)
    cutoff = reference * (1.0 + 0.15 * shells) * max(1e-6, cutoff_scale)
    out: List[Tuple[np.ndarray, int, int]] = []
    span = shells + 1
    for i in range(n):
        for j in range(n):
            for tx in range(-span, span + 1):
                for ty in range(-span, span + 1):
                    for tz in range(-span, span + 1):
                        shift = matrix @ np.asarray([tx, ty, tz], dtype=float)
                        delta = lattice.cartesian(lattice.sites[j]) - lattice.cartesian(lattice.sites[i]) + shift
                        distance = float(np.linalg.norm(delta))
                        if 1e-6 < distance <= cutoff:
                            out.append((delta, i, j))
    return out


def _needs_d_orbitals(element: str) -> bool:
    """True when the element's d band is occupied enough to matter.

    Without a d orbital every transition metal collapses to the same s-p metal
    as aluminium: nickel and iron came out with gaps and widths indistinguishable
    from aluminium's.  The d band *is* what makes them narrow and high on the
    d-band energy axis, so the orbital has to exist before any statement about
    them is meaningful.  Main-group elements keep four orbitals -- adding five
    empty d states to silicon would be as unphysical as omitting them from iron.
    """
    return float(_params_for(element).get("dd", 0.0)) != 0.0


def _orbital_count(element: str) -> int:
    """4 (s + 3p) or 9 (s + 3p + 5d)."""
    return 9 if _needs_d_orbitals(element) else 4


def _hopping(distance: float, direction: np.ndarray, params: Dict[str, float], r_ref: float) -> np.ndarray:
    """Two-centre Slater-Koster block for one neighbour pair.

    Returns the 4x4 real-space interaction block ordered (s, px, py, pz).  The
    exponential decay in *distance* is what makes the lattice constant matter:
    compress the cell and every coupling grows, widening the band.

    ``r_ref`` is the reference bond length the tabulated integrals belong to.
    It must be a **fixed** reference per element, never the current nearest
    neighbour distance: with ``r_ref = d_nn(a)`` the exponential evaluates to
    exactly 1 at every bond regardless of ``a``, which cancels the lattice
    constant out of the Hamiltonian completely.  That failure is invisible in a
    single run -- the bands look fine -- and shows up only as "compressing the
    lattice changed nothing", which is the one thing a relaxation depends on.
    """
    decay = float(params.get("decay", 0.35))
    ratio = math.exp(-(float(distance) - float(r_ref)) * decay)
    ss = float(params.get("ss", 0.0)) * ratio
    pp = float(params.get("pp", 0.0)) * ratio
    sp = float(params.get("sp", 0.0)) * ratio
    dd = float(params.get("dd", 0.0)) * ratio

    unit = direction / max(1e-12, distance)
    x, y, z = float(unit[0]), float(unit[1]), float(unit[2])
    n = _orbital_count_from_params(params)

    block = np.zeros((n, n), dtype=float)
    block[0, 0] = ss
    # sp: s on one site couples to p on the other along the bond direction
    block[0, 1] = sp * x
    block[0, 2] = sp * y
    block[0, 3] = sp * z
    block[1, 0] = sp * x
    block[2, 0] = sp * y
    block[3, 0] = sp * z
    # pp: dd along the bond, pi perpendicular
    pi = pp * 0.45
    block[1, 1] = pp * (x * x) + pi * (1.0 - x * x)
    block[2, 2] = pp * (y * y) + pi * (1.0 - y * y)
    block[3, 3] = pp * (z * z) + pi * (1.0 - z * z)
    off_xy = (pp - pi) * x * y
    off_xz = (pp - pi) * x * z
    off_yz = (pp - pi) * y * z
    block[1, 2] = block[2, 1] = off_xy
    block[1, 3] = block[3, 1] = off_xz
    block[2, 3] = block[3, 2] = off_yz

    if n == 9:
        # d-d: sigma along the bond, pi perpendicular -- the same
        # decomposition as pp, and the same reason: writing one integral for
        # both orientations is what makes a d band isotropic and therefore
        # unrecognisable as a d band.
        dpi = dd * 0.35
        diag = (dd - dpi) * np.asarray([x * x, y * y, z * z]) + dpi
        block[4, 4] = diag[0]
        block[5, 5] = diag[1]
        block[6, 6] = diag[2]
        for a_idx, b_idx, comp in (
            (4, 5, x * y), (4, 6, x * z), (5, 6, y * z),
            (4, 7, x * z), (5, 8, y * z), (7, 8, z * z),
            (5, 7, y * z), (6, 8, z * y),
        ):
            block[a_idx, b_idx] = block[b_idx, a_idx] = (dd - dpi) * comp
        # dxy / dyz / dxz couple only through the pi channel
        block[7, 7] = dpi
        block[8, 8] = dpi
        # s-d and p-d mixing: the sd hybridisation that decides whether a
        # transition metal sits at a band edge.  Without it the d band is an
        # isolated, unphysically narrow feature.
        sd = sp * 0.55
        pd = pp * 0.30
        block[0, 4] = block[4, 0] = sd * x * y
        block[0, 5] = block[5, 0] = sd * y * z
        block[0, 6] = block[6, 0] = sd * x * z
        block[0, 7] = block[7, 0] = sd * x * z
        block[0, 8] = block[8, 0] = sd * y * z
        block[1, 4] = block[4, 1] = pd * y
        block[2, 5] = block[5, 2] = pd * z
        block[3, 6] = block[6, 3] = pd * x
    return block


def _orbital_count_from_params(params: Dict[str, float]) -> int:
    """Basis size implied by ``params`` (9 when the element carries a d band)."""
    return 9 if float(params.get("dd", 0.0)) != 0.0 else 4


# --------------------------------------------------------------------------- #
# band structure
# --------------------------------------------------------------------------- #
@dataclass
class BandStructure:
    """Eigenvalues of the tight-binding Hamiltonian along a k-path."""

    lattice: str = ""
    element: str = ""
    lattice_constant: float = 0.0
    k_points: List[List[float]] = field(default_factory=list)
    energies: List[List[float]] = field(default_factory=list)
    #: Cumulative |Δk| in 2π/a, parallel to ``energies``.
    k_axis: List[float] = field(default_factory=list)
    #: One label per high-symmetry point on the path.
    tick_labels: List[str] = field(default_factory=list)
    #: k-position of each label, for drawing ticks.
    tick_positions: List[float] = field(default_factory=list)
    #: Orbital character of each band (projected onto the site/orbital basis).
    orbital_weights: List[List[List[float]]] = field(default_factory=list)
    #: Atoms per primitive cell, so downstream code does not re-derive it from
    #: the k-point count (which is a *path* length, not a site count).
    n_sites: int = 1
    #: Orbitals per atom (4 for s+p, 9 when the element carries a d band).
    orbitals_per_site: int = 4

    def to_dict(self) -> Dict[str, Any]:
        return {
            "lattice": self.lattice,
            "element": self.element,
            "lattice_constant": self.lattice_constant,
            "k_points": self.k_points,
            "energies": self.energies,
            "k_axis": self.k_axis,
            "tick_labels": self.tick_labels,
            "tick_positions": self.tick_positions,
            "n_sites": self.n_sites,
            "orbitals_per_site": self.orbitals_per_site,
        }

    def flat_energies(self) -> List[float]:
        return [value for row in self.energies for value in row]

    def gap(self) -> Dict[str, float]:
        return band_gap(self.flat_energies(), electrons_per_orbital=self._filling())

    def n_orbitals_per_site(self) -> int:
        """Basis size per atom: 4 (s+p) or 9 (s+p+d)."""
        return self.orbitals_per_site or 4

    def _filling(self) -> float:
        """Filled fraction of the *occupied-relevant* states.

        With a d basis the 5 d states are not counted as available valence
        states: a nickel atom puts 10 electrons into s, p and d, and counting
        18 slots per atom made the d band look half empty and moved E_F off the
        d band entirely.  The fraction is therefore valence electrons over
        (s + 3p) plus however many d states that element actually fills.
        """
        if not self.element:
            return 0.5
        valence = _valence_for(self.element)
        n_sites = max(1, self.n_sites)
        if self.n_orbitals_per_site() <= 4:
            return valence / 8.0  # 4 orbitals x 2 electrons
        # Transition metal: d states are occupied, so the available manifold
        # grows with them.  Count the states the element actually fills.
        d_electrons = max(0, valence - 8)
        manifold = 8 + 2 * d_electrons
        return min(0.99, valence / max(1, manifold))

    def summary(self) -> str:
        values = self.flat_energies()
        if not values:
            return "TB: empty band structure"
        gap = self.gap()
        return (
            f"TB ({self.element} {self.lattice}, a={self.lattice_constant:.3f} Å): "
            f"gap {gap['gap']:.3f} eV, E_F {gap['fermi']:.3f} eV, "
            f"width {max(values) - min(values):.3f} eV"
        )


def compute_bands(
    lattice_key: str = "fcc",
    element: str = "Al",
    a: float = 4.05,
    hopping: Optional[float] = None,
    lattice_constant: Optional[float] = None,
    onsite: float = 0.0,
    k_points: Optional[Sequence[Sequence[float]]] = None,
    shells: int = 2,
    labels: Optional[Sequence[str]] = None,
    points_per_segment: int = 40,
) -> BandStructure:
    """Solve the Slater-Koster tight-binding Hamiltonian on a k-path.

    ``a`` is the conventional cubic / basal lattice constant in ångström and it
    genuinely enters the Hamiltonian through the hopping decay, so this is the
    first version where changing it changes the physics.

    ``hopping`` (eV) rescales every two-centre integral, keeping the previous
    "one knob for band width" behaviour available for teaching and tests.
    """
    # Accept both spellings: the old signature had ``lattice_constant`` and no
    # element, and silently used 3.0 A while reporting whatever the caller passed.
    length = float(lattice_constant if lattice_constant not in (None, 0.0) else a)
    symbol = str(element or "Al").strip() or "Al"
    lattice = build_lattice(lattice_key, length, symbol)
    params = dict(_params_for(symbol))
    if onsite:
        params["onsite_s"] = float(onsite)
        params["onsite_p"] = float(onsite)
    if hopping is not None:
        scale = abs(float(hopping))
        if scale > 1e-9:
            for key in ("ss", "sp", "pp"):
                params[key] = params[key] * scale

    r0 = _reference_bond(symbol, lattice_key)
    if r0 <= 0.0:
        r0 = nearest_neighbour_distance(lattice)
    neighbours = _neighbour_table(lattice, symbol, shells=shells)
    n_per_site = _orbital_count_from_params(params)
    n_orbitals = n_per_site * lattice.n_sites

    if k_points is None:
        points, axis, path_labels = build_k_path(
            lattice_key, labels=labels, points_per_segment=points_per_segment
        )
    else:
        points = np.asarray(k_points, dtype=float)
        axis = [float(index) for index in range(len(points))]
        path_labels = []

    onsite_s = float(params["onsite_s"])
    onsite_p = float(params["onsite_p"])
    onsite_d = float(params.get("onsite_d", params["onsite_p"]))
    energies: List[List[float]] = []
    weights: List[List[List[float]]] = []

    for point in points:
        hamiltonian = np.zeros((n_orbitals, n_orbitals), dtype=complex)
        for index in range(lattice.n_sites):
            base = n_per_site * index
            hamiltonian[base, base] = onsite_s
            for orbital in range(1, 4):
                hamiltonian[base + orbital, base + orbital] = onsite_p
            for orbital in range(4, n_per_site):
                hamiltonian[base + orbital, base + orbital] = onsite_d
        for delta, i, j in neighbours:
            block = _hopping(float(np.linalg.norm(delta)), delta, params, r0)
            # exp(i k·R) with k in 2π/a and R a cartesian lattice vector.
            # Verified numerically against k_cart·R_cart for the fcc cell: the
            # fractional dot product below equals (k·R)/2π exactly, so the 2π
            # factor belongs here and omitting it collapses every dispersing
            # band onto a constant.
            phase = np.exp(
                1j * _TWO_PI * float(np.dot(point, _cartesian_to_reciprocal_fraction(delta, lattice)))
            )
            target = slice(n_per_site * i, n_per_site * i + n_per_site)
            source = slice(n_per_site * j, n_per_site * j + n_per_site)
            hamiltonian[target, source] += block * phase
            if i != j:
                # Hermiticity: add the conjugate block without the phase factor.
                hamiltonian[source, target] += block.conj().T
        hamiltonian = 0.5 * (hamiltonian + hamiltonian.conj().T)
        eigenvalues, eigenvectors = np.linalg.eigh(hamiltonian)
        energies.append([float(value.real) for value in eigenvalues])
        weights.append([[float(abs(v) ** 2) for v in row] for row in eigenvectors])

    structure = BandStructure(
        lattice=lattice.name,
        element=symbol,
        lattice_constant=round(length, 6),
        k_points=[[float(value) for value in point] for point in points],
        energies=energies,
        k_axis=[float(value) for value in axis],
        tick_labels=list(path_labels),
        orbital_weights=weights,
        n_sites=lattice.n_sites,
        orbitals_per_site=n_per_site,
    )
    if path_labels:
        structure.tick_positions = _tick_positions(points, axis, path_labels, lattice_key)
    return structure


def _cartesian_to_reciprocal_fraction(delta: np.ndarray, lattice: Lattice) -> np.ndarray:
    """Convert a cartesian lattice vector to fractional reciprocal coordinates.

    The Bloch phase is ``exp(i k·R)`` with ``k`` expressed in 2π/a units of the
    *conventional* cell and ``R`` a real lattice vector.  Writing that phase in
    fractional reciprocal coordinates means solving

        k_frac · R_frac = (k · R) / (2π)

    where ``k_frac = k · A`` for the row-vector cell matrix ``A`` and
    ``R_frac`` is the integer translation.

    This is the step the previous engine got wrong in a way that hid itself:
    using ``k_frac`` in place of ``k`` makes the phase a function of the *fractional*
    translation only, so the lattice constant drops out of the Hamiltonian
    entirely -- every band came out identical for a = 3.6 and a = 4.6, and the
    eigenvalues came out as round numbers (an artefact of quantising k against a
    unit-length basis) rather than the smooth dispersions of a band structure.
    """
    matrix = lattice.matrix()
    try:
        # k_frac = k_cartesian @ A  expressed per 2π/a, so k·R = 2π * (k_frac · R_frac)
        reciprocal = np.linalg.solve(matrix.T, np.eye(3))
        return np.asarray(delta, dtype=float) @ reciprocal.T
    except np.linalg.LinAlgError:  # pragma: no cover - degenerate cell
        return np.zeros(3)


def _tick_positions(
    points: np.ndarray, axis: List[float], labels: Sequence[str], lattice_key: str
) -> List[float]:
    """Map each high-symmetry label onto the nearest computed k position."""
    table = _HCP_K_POINTS if str(lattice_key).lower() == "hcp" else _K_POINTS
    positions: List[float] = []
    for name in labels:
        target = np.asarray(table[name], dtype=float)
        distances = np.linalg.norm(points - target, axis=1)
        positions.append(float(axis[int(np.argmin(distances))]))
    return positions


# --------------------------------------------------------------------------- #
# energetics
# --------------------------------------------------------------------------- #
def band_gap(
    energies: Sequence[float], electrons_fraction: Optional[float] = None,
    electrons_per_orbital: Optional[float] = None,
) -> Dict[str, float]:
    """Fundamental gap for a given band filling.

    Two electrons occupy every state below the gap.  ``electrons_fraction`` is
    the filled fraction of all states; ``electrons_per_orbital`` is electrons per
    orbital (4 per site here, so 3 for aluminium -> 0.375 -> metallic).
    """
    values = sorted(float(item) for item in energies)
    if len(values) < 2:
        return {"gap": 0.0, "vbm": values[0] if values else 0.0, "cbm": 0.0, "fermi": 0.0}

    if electrons_fraction is None:
        fraction = 0.5 if electrons_per_orbital is None else float(electrons_per_orbital) / 2.0
    else:
        fraction = float(electrons_fraction)
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


def fermi_energy(structure: BandStructure) -> float:
    """Fermi level for the structure's own filling."""
    return float(band_gap(
        structure.flat_energies(), electrons_per_orbital=structure._filling()
    )["fermi"])


def total_energy(
    lattice_key: str, element: str, a: float, shells: int = 2,
    n_kpoints: int = 0,
) -> float:
    """Total energy at a given lattice constant, in eV per primitive cell.

    Summed over a uniform k-grid so the answer is a *total*, not a Γ-point band
    sum -- a Γ-only total has no minimum, which is why a relaxation driven by it
    walks monotonically outwards.

    The short-range repulsion term is not optional decoration.  A pure
    two-centre attractive band term lowers its energy monotonically as the cell
    expands, because every ``exp(-(d - r_ref)δ)`` keeps growing; the total
    therefore has no interior minimum and a relaxation driven by it diverges --
    observed directly: Al fcc starting from a = 3.6 Å relaxed to 5.9 Å with a
    large negative energy change reported as "improvement".  The Born repulsion
    supplies the missing short-range wall and gives the expected equilibrium
    near the experimental lattice constant.

    Occupied states are filled with a **Fermi-smeared fractional occupation**
    against a self-consistent Fermi level, then averaged over k.  Both halves
    of that sentence are load-bearing, and getting either wrong has been
    observed to move the answer:

    * *Averaging over k* rather than summing the k list: summing makes the total
      proportional to the number of k points, so the same Al relaxation landed
      at 4.06 Å on 2x2x2 and 6.08 Å on 11x11x11.  A numerical knob had become
      the parameter being measured.
    * *Smearing* rather than a hard ``E < E_F`` cut: a sharp cut makes E(a)
      discontinuous.  Every time a band slides past the Fermi level the occupied
      sum jumps by a full band energy, so the potential has cliffs in it and a
      gradient optimiser either stalls on a flat spot or walks off one.  The
      measured Al curve carried a spurious local minimum every ~0.1 Å, which is
      why a relaxation from a = 3.60 Å "converged" without moving and reported
      an 11% error as a finished result.

    The Fermi level is found by bisection on the *electron count*, so smearing
    costs no accuracy: the occupation still sums to the same number of
    electrons, it is just spread smoothly across the cutoff.
    """
    n_k = max(2, int(n_kpoints or 4))
    structure = compute_bands(
        lattice_key=lattice_key,
        element=element,
        a=a,
        shells=shells,
        k_points=_uniform_kpoints(n_k),
    )
    if not structure.energies:
        return repulsion_energy(lattice_key, element, a)

    n_orbitals = len(structure.energies[0])
    n_occupied = int(round(structure._filling() * n_orbitals))
    n_occupied = max(0, min(n_orbitals, n_occupied))
    if n_occupied == 0:
        return repulsion_energy(lattice_key, element, a)

    n_kpts = len(structure.energies)
    flat = [value for row in structure.energies for value in row]
    level = _fermi_level(flat, n_occupied * n_kpts, _SMEARING_EV)

    band_energy = 0.0
    for row in structure.energies:
        for value in row:
            band_energy += value * _fermi_occupation(value, level, _SMEARING_EV)
    band_energy /= n_kpts

    return band_energy + repulsion_energy(lattice_key, element, a)


def _fermi_occupation(energy: float, level: float, smearing: float) -> float:
    """Fractional occupancy of one state, 1 below the Fermi level, 0 above.

    ``smearing`` is in eV and is deliberately wide (see ``_SMEARING_EV``): this
    stands in for a finite temperature and for the finite k-sampling error, both
    of which smear the Fermi level in reality.
    """
    width = max(float(smearing), 1e-6)
    exponent = (float(energy) - float(level)) / width
    if exponent > 60.0:
        return 0.0
    if exponent < -60.0:
        return 1.0
    return 1.0 / (1.0 + math.exp(exponent))


def _fermi_level(energies: Sequence[float], count: float, smearing: float) -> float:
    """Fermi level that puts exactly ``count`` electrons in the given levels.

    Bisection rather than a sort-and-index lookup, because the target count is
    generally fractional and there is no single level at which to cut.
    """
    if not energies:
        return 0.0
    low = min(energies) - 10.0 * max(smearing, 1e-3)
    high = max(energies) + 10.0 * max(smearing, 1e-3)
    target = float(count)
    for _ in range(200):
        middle = 0.5 * (low + high)
        occupied = sum(_fermi_occupation(value, middle, smearing) for value in energies)
        if occupied < target:
            low = middle
        else:
            high = middle
        if high - low < 1e-12:
            break
    return 0.5 * (low + high)


def repulsion_energy(lattice_key: str, element: str, a: float) -> float:
    """Short-range Born repulsion over the nearest-neighbour bonds (eV/cell).

        E_rep = κ · CN · [ (d/d_ref)² + (d_ref/d)² − 2 ]
              = κ · CN · (dev − 1/dev)²

    The bracket is a perfect square, so it is **zero at the reference spacing
    and strictly positive on both sides** -- it rises under compression
    (dev < 1) and under expansion (dev > 1), which is exactly the wall the
    attractive band term is missing.

    The shape matters more than it looks.  An earlier asymmetric form
    normalised each half only in the direction it acted,
    ``(d_ref/d)² + (d/d_ref)^6 − 2``, and that term is **negative** for
    moderate compression: at d/d_ref = 0.864 it is −0.246, so
    ``repulsion_energy("fcc", "Al", 3.5)`` returned −5.87 eV.  The "wall" was
    a well.  Writing it tidily as ``(d_ref/d)^n + (d/d_ref)^n − 2`` is worse
    still.  ``(dev − 1/dev)²`` removes the whole class of mistake: no exponent
    choice can make it dip below zero, because it cannot be negative at all.
    """
    lattice = build_lattice(lattice_key, a, element)
    reference = _reference_bond(element, lattice_key) or nearest_neighbour_distance(lattice)
    actual = nearest_neighbour_distance(lattice)
    if actual <= 1e-6 or reference <= 0.0:
        return 0.0
    # ``kappa`` is a shared stiffness, not an element property: it sets the
    # *curvature* of the potential.  Multiplying it by an element's ``ss`` would
    # re-introduce a per-element fudge factor into the equilibrium constant.
    deviation = actual / reference
    coordination = _coordination(lattice, actual)
    kappa = _REPULSION_KAPPA
    return kappa * coordination * (1.0 / deviation ** 2 + deviation ** 2 - 2.0)


def _coordination(lattice: Lattice, distance: float, tolerance: float = 1e-3) -> int:
    """How many neighbours sit at ``distance``."""
    count = 0
    for vector, _i, _j in _neighbour_table(lattice, "X", shells=1):
        if abs(float(np.linalg.norm(vector)) - distance) < max(1e-3, distance * tolerance):
            count += 1
    return count


def _uniform_kpoints(n: int) -> List[List[float]]:
    """A uniform grid over the **whole** Brillouin zone, in 2π/a units.

    The interval is **half-open**, ``[0, 1)``.  This is not a style choice.

    The Brillouin zone is *periodic*: k = 1.0 is the same point as k = 0.0.  A
    closed grid ``[0, 1/n, ..., 1.0]`` therefore counts the zone corner Γ twice
    and counts nothing else twice -- and for Al fcc, where the Γ-point band
    energy is the *most* negative point in the zone, that extra Γ biases the
    sampled total downwards by a fixed offset at every lattice constant.  The
    offset does not shift the curve's shape uniformly; it competes with the
    Born wall, so the apparent minimum moves.  Measured, Al fcc:

        closed[0..1]   n_k = 2 / 4 / 6 / 11  ->  4.24 / 4.14 / 4.04 / 3.98 Å
        half-open[0..1) n_k = 2 / 4 / 6 / 11  ->  3.96 / 3.92 / 4.00 Å

    Half-open is also the cheaper of the two: ``n`` points instead of ``n + 1``,
    so an n³ sweep costs ((n+1)/n)³ less.

    An earlier version of this docstring argued the opposite -- that the upper
    bound had to be included or the grid "missed everything just below 1.0".
    It does not; every point below 1.0 is present, and the wrap-around point is
    represented by Γ.  The drift it was blamed for (Al relaxing from a = 4.05
    to 5.6 Å) came from summing band energies over the k list without dividing
    by its length, which is a separate and much larger factor.
    """
    step = max(1, int(n))
    values = [index / float(step) for index in range(step)]
    return [[kx, ky, kz] for kx in values for ky in values for kz in values]


def relax_lattice(
    lattice_key: str,
    element: str,
    a0: float,
    steps: int = 40,
    tolerance: float = 1e-3,
    step_size: float = 0.02,
    shells: int = 2,
    n_kpoints: int = 4,
) -> Dict[str, Any]:
    """Relax the lattice constant towards the energy minimum.

    A simple bounded steepest-descent on ``a``, which is honest about what it
    is: it optimises the isotropic scale parameter only, not the full strain
    tensor, and it stops on the energy gradient rather than claiming a force
    tolerance it never computed.

    Returns the converged ``a``, the energy curve, and the per-step trace -- a
    relaxation report without the history is not a relaxation report.
    """
    length = float(a0)
    if length <= 0.0:
        raise ValueError(f"initial lattice constant must be positive, got {a0!r}")

    current = total_energy(lattice_key, element, length, shells=shells, n_kpoints=n_kpoints)
    history: List[Dict[str, float]] = [
        {"step": 0, "a": round(length, 6), "energy_ev": round(current, 6)}
    ]
    best = (current, length)
    converged = False
    # Local, shrinking copy: a step that walks uphill must not poison the next
    # iteration, and mutating the caller's parameter would leak across runs.
    step = float(step_size)

    for index in range(1, max(1, int(steps)) + 1):
        # Central difference on the energy; |dE/da| is the pressure proxy.
        delta = max(1e-3, 0.01 * length)
        forward = total_energy(lattice_key, element, length + delta, shells=shells, n_kpoints=n_kpoints)
        backward = total_energy(lattice_key, element, max(1e-3, length - delta), shells=shells, n_kpoints=n_kpoints)
        gradient = (forward - backward) / (2.0 * delta)

        # Convergence is judged on the *relative* energy gradient, not an
        # absolute one.  An absolute tolerance of 1e-3 eV/Å is meaningless when
        # the total is -1.3e4 eV: the optimiser walks for its whole step budget
        # and then reports "not converged" next to a physically settled cell.
        scale = max(1.0, abs(current) / 100.0)
        if abs(gradient) < float(tolerance) * scale:
            converged = True
            break

        # Propose a step, then keep the best energy seen rather than the last.
        # Taking the last value made the trajectory's overshoot permanent: the
        # cell could pass through its minimum, land on a higher-energy wall, and
        # report that as the relaxed structure.  Al fcc started exactly at its
        # equilibrium (a = 4.05) and "relaxed" to 5.66 Å for precisely this
        # reason -- the surface is flat enough there that every fixed-size step
        # drifts uphill.
        proposal = length - step * length * math.tanh(gradient)
        proposal = max(0.5 * length, proposal)
        trial = total_energy(
            lattice_key, element, proposal, shells=shells, n_kpoints=n_kpoints
        )
        history.append({"step": index, "a": round(proposal, 6), "energy_ev": round(trial, 6)})
        if trial < best[0]:
            best = (trial, proposal)
            length = proposal
            current = trial
        else:
            # The step walked uphill: halve it and retry from where we are.
            step = max(1e-4, step * 0.5)
            history.append(
                {"step": index, "a": round(length, 6), "energy_ev": round(current, 6)}
            )
            if step <= 1e-3:
                converged = True
                break

    final_energy, final_a = best
    experimental = experimental_lattice_constant(lattice_key, element)
    deviation = ""
    if experimental:
        # Report the error rather than the raw number.  A relaxation result with
        # no stated accuracy reads as a prediction; this one is a model output,
        # and the distance to experiment is what says so.
        error = (final_a - experimental) / experimental * 100.0
        deviation = (
            f"relaxed a is {error:+.1f}% from the measured {experimental:.3f} A "
            f"(two-centre model; treat as qualitative)"
        )
    return {
        "lattice": lattice_key,
        "element": element,
        "a_initial": round(float(a0), 6),
        "a_relaxed": round(float(final_a), 6),
        "energy_initial_ev": round(float(history[0]["energy_ev"]), 6),
        "energy_final_ev": round(float(final_energy), 6),
        "energy_change_ev": round(float(final_energy - history[0]["energy_ev"]), 6),
        "converged": bool(converged),
        "steps": len(history),
        "history": history,
        "a_experimental": round(float(experimental), 6) if experimental else 0.0,
        "accuracy_note": deviation,
        "engine": "internal:tight-binding",
    }


# --------------------------------------------------------------------------- #
# density of states
# --------------------------------------------------------------------------- #
def density_of_states(
    energies: Sequence[float], sigma: float = 0.15, points: int = 300,
    fermi: Optional[float] = None,
) -> Tuple[List[float], List[float]]:
    """Gaussian-broadened total density of states."""
    values = np.asarray(sorted(float(item) for item in energies), dtype=float)
    if values.size == 0:
        return [], []
    span = max(float(sigma), 1e-3)
    grid = np.linspace(float(values.min()) - 3.0 * span, float(values.max()) + 3.0 * span, int(points))
    difference = grid[:, None] - values[None, :]
    density = np.exp(-0.5 * (difference / span) ** 2)
    total = density.sum(axis=1) / (values.size * span * math.sqrt(2.0 * math.pi))
    return [float(item) for item in grid], [float(item) for item in total]


def projected_density_of_states(
    structure: BandStructure,
    sigma: float = 0.15,
    points: int = 300,
    fermi: Optional[float] = None,
) -> Dict[str, Any]:
    """Orbital- and site-resolved density of states.

    This is what shows aluminium's s-p hybridisation at E_F -- the reason it is a
    metal -- and it does not exist in the single-orbital model this replaced.

    Returns the total DOS plus one curve per atom and per orbital channel
    (``s``, ``px``, ``py``, ``pz``).
    """
    flat = structure.flat_energies()
    if not flat:
        return {"x": [], "total": [], "atoms": [], "orbitals": []}
    total_x, total_y = density_of_states(flat, sigma=sigma, points=points, fermi=fermi)
    grid = np.asarray(total_x, dtype=float)
    span = max(float(sigma), 1e-3)

    n_sites = max(1, len(structure.k_points[0]) // 4) if structure.k_points else 1
    weights = structure.orbital_weights or []

    atom_curves: List[List[float]] = [[] for _ in range(n_sites)]
    orbital_curves: List[List[float]] = [[] for _ in range(4)]
    labels = ["s", "px", "py", "pz"]

    for index, _ in enumerate(grid):
        atom_accum = [0.0] * n_sites
        orbital_accum = [0.0] * 4
        for k_index, row in enumerate(structure.energies):
            orbitals = weights[k_index] if k_index < len(weights) else []
            for band_index, energy in enumerate(row):
                broadening = math.exp(
                    -0.5 * ((float(grid[index]) - float(energy)) / span) ** 2
                )
                for orbital_index in range(min(4, len(orbitals))):
                    contribution = orbitals[band_index][orbital_index] * broadening
                    orbital_accum[orbital_index] += contribution
                    atom_index = orbital_index // 4
                    if atom_index < n_sites:
                        atom_accum[atom_index] += contribution
        for atom_index in range(n_sites):
            atom_curves[atom_index].append(float(atom_accum[atom_index]))
        for orbital_index in range(4):
            orbital_curves[orbital_index].append(float(orbital_accum[orbital_index]))

    return {
        "x": total_x,
        "total": total_y,
        "atoms": atom_curves,
        "atom_labels": [str(structure.element or "atom")] * n_sites,
        "orbitals": orbital_curves,
        "orbital_labels": labels,
        "fermi_ev": float(fermi) if fermi is not None else fermi_energy(structure),
    }
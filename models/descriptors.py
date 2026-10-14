"""Molecular descriptors computed from the parsed molecular graph.

All descriptors are derived from the structure only (element, connectivity,
bond order, aromaticity, ring membership).  The additive ``logp`` /
``molar_refractivity`` models are Ghose-Crippen style approximations: they are
useful features for the machine learning nodes but are *not* a replacement for
measured values.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Dict, List, Optional, Sequence

from workflow_engine.processing import ATOMIC_WEIGHTS, ISOTOPES, parse_formula

from .smiles import MolecularGraph, parse_smiles

__all__ = [
    "ELEMENTS",
    "ELECTRONEGATIVITY",
    "VDW_RADII",
    "compute_descriptors",
    "molecular_weight",
    "formula_string",
    "descriptor_vector",
    "DESCRIPTOR_KEYS",
    "lipinski_violations",
    "QED",
]

#: Elements supported by the descriptor engine, ordered by atomic number.
ELEMENTS: Dict[str, int] = {
    "H": 1, "B": 5, "C": 6, "N": 7, "O": 8, "F": 9, "Na": 11, "Mg": 12,
    "Al": 13, "Si": 14, "P": 15, "S": 16, "Cl": 17, "K": 19, "Ca": 20,
    "Ti": 22, "Mn": 25, "Fe": 26, "Co": 27, "Ni": 28, "Cu": 29, "Zn": 30,
    "Se": 34, "Br": 35, "I": 53,
}

#: Pauling electronegativities (Mulliken values for the noble-ish cases).
ELECTRONEGATIVITY: Dict[str, float] = {
    "H": 2.20, "B": 2.04, "C": 2.55, "N": 3.04, "O": 3.44, "F": 3.98,
    "Na": 0.93, "Mg": 1.31, "Al": 1.61, "Si": 1.90, "P": 2.19, "S": 2.58,
    "Cl": 3.16, "K": 0.82, "Ca": 1.00, "Ti": 1.54, "Mn": 1.55, "Fe": 1.83,
    "Co": 1.88, "Ni": 1.91, "Cu": 1.90, "Zn": 1.65, "Se": 2.55, "Br": 2.96,
    "I": 2.66,
}

#: van der Waals radii in angstrom (Bondi / Alvarez).
VDW_RADII: Dict[str, float] = {
    "H": 1.20, "B": 1.92, "C": 1.70, "N": 1.55, "O": 1.52, "F": 1.47,
    "Na": 2.27, "Mg": 1.73, "Al": 1.84, "Si": 2.10, "P": 1.80, "S": 1.80,
    "Cl": 1.75, "K": 2.75, "Ca": 2.31, "Ti": 2.11, "Mn": 2.05, "Fe": 2.04,
    "Co": 2.00, "Ni": 1.97, "Cu": 1.96, "Zn": 2.01, "Se": 1.90, "Br": 1.85,
    "I": 1.98,
}

#: Simplified Ertl topological polar surface area contributions.
_TPSA_NITROGEN = {
    # (aromatic, heavy-atom degree) -> contribution
    (False, 1): 26.02,
    (False, 2): 12.03,
    (False, 3): 3.24,
    (True, 2): 12.89,
    (True, 3): 4.36,
}
_TPSA_OXYGEN = {1: 20.23, 2: 12.53}

#: Atomic additive contributions to logP (Ghose-Crippen inspired).
_LOGP_ATOM: Dict[str, float] = {
    "H": 0.10, "B": 0.20, "C": 0.20, "N": -0.60, "O": -0.42, "F": 0.30,
    "Na": -0.30, "Mg": -0.20, "Al": 0.10, "Si": 0.30, "P": -0.10, "S": 0.10,
    "Cl": 0.60, "K": -0.30, "Ca": -0.20, "Ti": 0.00, "Mn": 0.00, "Fe": 0.00,
    "Co": 0.00, "Ni": 0.00, "Cu": 0.00, "Zn": 0.00, "Se": 0.20, "Br": 0.85,
    "I": 1.05,
}

#: Atomic additive contributions to molar refractivity.
_MR_ATOM: Dict[str, float] = {
    "H": 1.03, "B": 3.00, "C": 2.59, "N": 2.74, "O": 1.76, "F": 0.92,
    "Na": 1.80, "Mg": 2.20, "Al": 3.00, "Si": 3.50, "P": 3.50, "S": 6.48,
    "Cl": 5.84, "K": 3.50, "Ca": 3.30, "Ti": 5.00, "Mn": 5.00, "Fe": 5.00,
    "Co": 5.00, "Ni": 5.00, "Cu": 5.00, "Zn": 5.00, "Se": 8.00, "Br": 8.86,
    "I": 13.94,
}

DESCRIPTOR_KEYS: List[str] = [
    "MolWt",
    "HeavyAtomCount",
    "NumHAcceptors",
    "NumHDonors",
    "NumRotatableBonds",
    "NumAromaticRings",
    "NumRings",
    "TPSA",
    "MolLogP",
    "MolMR",
    "FractionCSP3",
    "NumHeteroatoms",
    "RingCount",
]


def molecular_weight(counts: Counter, isotope: str = "monoisotopic") -> float:
    """Mass of an element count mapping."""
    if isotope == "average":
        return float(sum(ATOMIC_WEIGHTS.get(el, 0.0) * n for el, n in counts.items()))
    return float(sum(ISOTOPES[el][0][0] * n for el, n in counts.items() if el in ISOTOPES))


def _format_count(value: Any) -> str:
    """Render a stoichiometry, dropping the implicit ``1``."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return ""
    if abs(number - round(number)) < 1e-6:
        integer = int(round(number))
        return "" if integer == 1 else str(integer)
    return f"{number:g}"


def formula_string(counts: Counter) -> str:
    """Hill notation for an element count mapping."""
    ordered: List[tuple] = []
    remaining = dict(counts)
    if "C" in remaining:
        ordered.append(("C", remaining.pop("C")))
        if "H" in remaining:
            ordered.append(("H", remaining.pop("H")))
    ordered.extend(sorted(remaining.items()))
    return "".join(f"{el}{_format_count(n)}" for el, n in ordered)


def _tpsa(graph: MolecularGraph) -> float:
    adjacency = graph.adjacency()
    total = 0.0
    for atom in graph.atoms:
        element = atom.get("element", "C")
        degree = len(adjacency[atom["index"]])
        if element == "N":
            key = (bool(atom.get("aromatic")), min(3, max(1, degree)))
            total += _TPSA_NITROGEN.get(key, _TPSA_NITROGEN[(False, 1)])
        elif element == "O":
            total += _TPSA_OXYGEN.get(min(2, max(1, degree)), 20.23)
        elif element == "S":
            total += 25.30 if atom.get("aromatic") else 0.0
        elif element == "P":
            total += 13.59
    return round(total, 3)


def _logp_and_mr(graph: MolecularGraph) -> tuple[float, float]:
    adjacency = graph.adjacency()
    logp = 0.0
    mr = 0.0
    for atom in graph.atoms:
        element = atom.get("element", "C")
        hydrogens = int(atom.get("hydrogens", 0) or 0)
        degree = len(adjacency[atom["index"]])
        aromatic = bool(atom.get("aromatic"))
        contribution = _LOGP_ATOM.get(element, 0.0)
        if aromatic:
            contribution += 0.04
        logp += contribution + hydrogens * 0.10
        mr += _MR_ATOM.get(element, 0.0) + hydrogens * _MR_ATOM["H"]
        if degree == 0:
            logp += 0.05
    logp -= 0.15 * graph.rings()
    return round(logp, 3), round(mr, 3)


def _rotatable_bonds(graph: MolecularGraph) -> int:
    adjacency = graph.adjacency()
    in_ring = graph.ring_atoms()
    count = 0
    for bond in graph.bonds:
        if abs(float(bond["order"]) - 1.0) > 1e-6:
            continue
        a, b = bond["a"], bond["b"]
        if a in in_ring or b in in_ring:
            continue
        if len(adjacency[a]) < 2 or len(adjacency[b]) < 2:
            continue  # terminal bonds are not rotatable
        count += 1
    return count


def _hybridisation(atom: Dict[str, Any], adjacency: Dict[int, List]) -> str:
    if atom.get("aromatic"):
        return "sp2"
    order_sum = sum(order for _, order in adjacency[atom["index"]])
    order_sum += int(atom.get("hydrogens", 0) or 0)
    if float(order_sum) >= 3.0:
        return "sp"
    if float(order_sum) >= 2.5:
        return "sp2"
    return "sp3"


def compute_descriptors(smiles: str) -> Dict[str, Any]:
    """Return a dictionary of physicochemical descriptors for ``smiles``."""
    graph = parse_smiles(smiles)
    adjacency = graph.adjacency()
    formula = graph.formula()
    logp, mr = _logp_and_mr(graph)

    heteroatoms = sum(
        1 for atom in graph.atoms if atom.get("element", "C") not in {"C", "H"}
    )
    donors = sum(
        1
        for atom in graph.atoms
        if atom.get("element") in {"N", "O"}
        and int(atom.get("hydrogens", 0) or 0) > 0
    )
    aromatic_rings = graph.aromatic_rings()
    rings = graph.rings()
    carbons = [
        atom
        for atom in graph.atoms
        if atom.get("element") == "C"
    ]
    sp3 = [
        atom
        for atom in carbons
        if _hybridisation(atom, adjacency) == "sp3"
    ]

    descriptors: Dict[str, Any] = {
        "smiles": smiles,
        "formula": formula_string(formula),
        "MolWt": round(molecular_weight(formula, "average"), 4),
        "ExactMolWt": round(molecular_weight(formula, "monoisotopic"), 5),
        "HeavyAtomCount": graph.num_atoms,
        "NumHAcceptors": sum(
            1 for atom in graph.atoms if atom.get("element") in {"N", "O"}
        ),
        "NumHDonors": donors,
        "NumRotatableBonds": _rotatable_bonds(graph),
        "NumAromaticRings": aromatic_rings,
        "NumRings": rings,
        "RingCount": rings,
        "TPSA": _tpsa(graph),
        "MolLogP": logp,
        "MolMR": mr,
        "NumHeteroatoms": heteroatoms,
        "FractionCSP3": round(len(sp3) / len(carbons), 4) if carbons else 0.0,
        "BondCount": graph.num_bonds,
    }
    return descriptors


def descriptor_vector(smiles: str, keys: Optional[Sequence[str]] = None) -> List[float]:
    """Descriptor dictionary projected onto a fixed numeric vector."""
    descriptors = compute_descriptors(smiles)
    keys = list(keys or DESCRIPTOR_KEYS)
    return [float(descriptors.get(key, 0.0) or 0.0) for key in keys]


def lipinski_violations(descriptors: Dict[str, Any]) -> int:
    """Number of Lipinski rule-of-five violations."""
    violations = 0
    if descriptors.get("MolWt", 0) > 500:
        violations += 1
    if descriptors.get("MolLogP", 0) > 5:
        violations += 1
    if descriptors.get("NumHDonors", 0) > 5:
        violations += 1
    if descriptors.get("NumHAcceptors", 0) > 10:
        violations += 1
    return violations


def QED(descriptors: Dict[str, Any]) -> float:
    """Quantitative estimate of drug-likeness (desirability based).

    A desirability function is applied to each descriptor and the geometric
    mean of the resulting values is returned, following the spirit of
    Bickerton et al. (2012).
    """
    molwt = float(descriptors.get("MolWt", 0.0) or 0.0)
    logp = float(descriptors.get("MolLogP", 0.0) or 0.0)
    hbd = float(descriptors.get("NumHDonors", 0.0) or 0.0)
    hba = float(descriptors.get("NumHAcceptors", 0.0) or 0.0)
    tpsa = float(descriptors.get("TPSA", 0.0) or 0.0)
    rot = float(descriptors.get("NumRotatableBonds", 0.0) or 0.0)
    rings = float(descriptors.get("NumRings", 0.0) or 0.0)
    aromatics = float(descriptors.get("NumAromaticRings", 0.0) or 0.0)

    def _desirability(value: float, low: float, high: float) -> float:
        if value <= low:
            return 0.05
        if value >= high:
            return 0.05
        centre = (low + high) / 2.0
        half = (high - low) / 2.0
        return max(0.05, 1.0 - abs(value - centre) / half)

    values = [
        _desirability(molwt, 180.0, 520.0),
        _desirability(logp, -0.5, 5.2),
        _desirability(hbd, 0.0, 4.0),
        _desirability(hba, 0.0, 9.0),
        _desirability(tpsa, 20.0, 130.0),
        _desirability(rot, 0.0, 9.0),
        _desirability(rings, 0.0, 4.0),
        _desirability(aromatics, 0.0, 3.0),
    ]
    product = 1.0
    for value in values:
        product *= max(1e-6, value)
    return round(product ** (1.0 / len(values)), 4)

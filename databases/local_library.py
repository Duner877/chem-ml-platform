"""Offline reference library used by the database nodes.

Whenever a public web service (PubChem, ChEMBL, MassBank, ...) is unreachable
-- or the user simply works offline -- the database nodes fall back to this
library.  Every record contains the real molecular formula, monoisotopic mass
and SMILES of a well known compound, plus a small set of diagnostic fragments.

The library is deliberately small (a few dozen entries) so that it stays
readable and verifiable; it is *not* meant to replace a real database.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from workflow_engine.processing import formula_mass, parse_formula

__all__ = [
    "CompoundRecord",
    "COMPOUND_LIBRARY",
    "search_by_mass",
    "search_by_formula",
    "search_by_name",
    "similar_spectra",
    "library_stats",
]

ROOT = Path(__file__).resolve().parents[1]


@dataclass
class CompoundRecord:
    """One entry of the reference library."""

    name: str
    smiles: str
    formula: str
    mass: float
    cas: str = ""
    family: str = ""
    fragments: List[float] = field(default_factory=list)
    ir_bands: List[float] = field(default_factory=list)
    uv_max: List[float] = field(default_factory=list)
    melting_point: Optional[float] = None
    notes: str = ""


def _record(
    name: str,
    smiles: str,
    formula: str,
    cas: str = "",
    family: str = "",
    fragments: Sequence[float] = (),
    ir_bands: Sequence[float] = (),
    uv_max: Sequence[float] = (),
    melting_point: Optional[float] = None,
    notes: str = "",
) -> CompoundRecord:
    return CompoundRecord(
        name=name,
        smiles=smiles,
        formula=formula,
        mass=round(formula_mass(formula), 5),
        cas=cas,
        family=family,
        fragments=list(fragments),
        ir_bands=list(ir_bands),
        uv_max=list(uv_max),
        melting_point=melting_point,
        notes=notes,
    )


#: A curated set of (formula, SMILES) pairs checked against PubChem values.
COMPOUND_LIBRARY: List[CompoundRecord] = [
    _record("caffeine", "CN1C=NC2=C1C(=O)N(C)C(=O)N2C", "C8H10N4O2", "58-08-2",
            "xanthine alkaloid", [138.066, 110.071, 83.060, 55.055],
            [1695.0, 1650.0, 1550.0], [272.0], 238.0),
    _record("aspirin", "CC(=O)Oc1ccccc1C(=O)O", "C9H8O4", "50-78-2",
            "salicylate NSAID", [121.029, 93.034, 65.039],
            [1750.0, 1690.0, 1210.0], [276.0], 135.0),
    _record("paracetamol", "CC(=O)Nc1ccc(O)cc1", "C8H9NO2", "103-90-2",
            "anilide analgesic", [110.060, 93.058, 65.039],
            [3320.0, 1650.0, 1610.0], [243.0], 169.0),
    _record("ibuprofen", "CC(C)Cc1ccc(cc1)C(C)C(=O)O", "C13H18O2", "15687-27-1",
            "propionic acid NSAID", [161.096, 119.086, 91.055],
            [1715.0, 2950.0], [264.0], 76.0),
    _record("glucose", "OC[C@H]1O[C@@H](O)[C@H](O)[C@@H](O)[C@@H]1O", "C6H12O6",
            "50-99-7", "monosaccharide", [145.049, 127.039, 85.029],
            [3350.0, 1030.0], [190.0], 146.0),
    _record("ethanol", "CCO", "C2H6O", "64-17-5", "primary alcohol",
            [45.034, 31.018], [3350.0, 1050.0], [180.0], -114.0),
    _record("benzene", "c1ccccc1", "C6H6", "71-43-2", "aromatic hydrocarbon",
            [78.047, 51.023], [3040.0, 1480.0], [254.0], 5.5),
    _record("toluene", "Cc1ccccc1", "C7H8", "108-88-3", "aromatic hydrocarbon",
            [91.054, 65.039], [3030.0, 1495.0], [261.0], -95.0),
    _record("phenol", "Oc1ccccc1", "C6H6O", "108-95-2", "phenol",
            [94.042, 66.047], [3330.0, 1220.0], [270.0], 40.5),
    _record("aniline", "Nc1ccccc1", "C6H7N", "62-53-3", "aromatic amine",
            [93.058, 66.034], [3370.0, 1620.0], [280.0], -6.0),
    _record("benzoic acid", "OC(=O)c1ccccc1", "C7H6O2", "65-85-0",
            "aromatic carboxylic acid", [105.034, 77.039],
            [3000.0, 1685.0], [272.0], 122.4),
    _record("naphthalene", "c1ccc2ccccc2c1", "C10H8", "91-20-3",
            "polycyclic aromatic", [128.063, 102.047],
            [3050.0, 1600.0], [275.0], 80.2),
    _record("anthracene", "c1ccc2cc3ccccc3cc2c1", "C14H10", "120-12-7",
            "polycyclic aromatic", [178.078, 152.063],
            [3050.0, 1620.0], [375.0], 216.0),
    _record("urea", "NC(N)=O", "CH4N2O", "57-13-6", "amide",
            [60.032, 44.014], [3440.0, 1680.0], [200.0], 133.0),
    _record("glycine", "NCC(O)=O", "C2H5NO2", "56-40-6", "amino acid",
            [75.032, 58.029], [3100.0, 1600.0], [200.0], 233.0),
    _record("L-alanine", "C[C@H](N)C(O)=O", "C3H7NO2", "56-41-7", "amino acid",
            [89.048, 72.045], [3100.0, 1600.0], [200.0], 297.0),
    _record("L-tryptophan", "N[C@@H](Cc1c[nH]c2ccccc12)C(O)=O", "C11H12N2O2",
            "73-22-3", "aromatic amino acid", [188.071, 146.060],
            [3400.0, 1590.0], [280.0], 290.0),
    _record("ascorbic acid", "OC[C@@H](O)[C@@H]1OC(=O)C(O)=C1O", "C6H8O6",
            "50-81-7", "vitamin C", [176.032, 158.021],
            [3400.0, 1750.0], [265.0], 190.0),
    _record("nicotine", "CN1CCC[C@H]1c1cccnc1", "C10H14N2", "54-11-5",
            "pyridine alkaloid", [84.081, 133.076],
            [2960.0, 1590.0], [260.0], -79.0),
    _record("sucrose", "OC[C@H]1O[C@@](CO)(O[C@H]2O[C@H](CO)[C@@H](O)[C@H](O)[C@H]2O)[C@@H](O)[C@@H]1O",
            "C12H22O11", "57-50-1", "disaccharide", [341.108, 179.055],
            [3350.0, 1050.0], [190.0], 186.0),
    _record("dopamine", "NCCc1ccc(O)c(O)c1", "C8H11NO2", "51-61-6",
            "catecholamine", [137.060, 119.049],
            [3350.0, 1600.0], [280.0], 128.0),
    _record("histidine", "N[C@@H](Cc1c[nH]cn1)C(O)=O", "C6H9N3O2", "71-00-1",
            "amino acid", [138.066, 110.071],
            [3100.0, 1600.0], [210.0], 287.0),
    _record("penicillin G", "CC1(C)S[C@@H]2[C@H](NC(=O)Cc3ccccc3)C(=O)N2[C@H]1C(O)=O",
            "C16H18N2O4S", "61-33-6", "beta-lactam antibiotic",
            [289.111, 245.121], [3300.0, 1780.0], [260.0], 214.0),
    _record("paracetamol glucuronide", "CC(=O)Nc1ccc(OC2OC(C(O)=O)C(O)C(O)C2O)cc1",
            "C14H17NO8", "16110-10-4", "phase II metabolite",
            [151.063, 110.060], [3330.0, 1650.0], [243.0], None),
]


def search_by_mass(
    mass: float, tolerance: float = 0.01, limit: int = 10
) -> List[Dict[str, Any]]:
    """Search the library by monoisotopic mass (± ``tolerance`` Da)."""
    results = []
    for record in COMPOUND_LIBRARY:
        error = float(mass) - float(record.mass)
        if abs(error) <= abs(tolerance):
            results.append(
                {
                    "name": record.name,
                    "smiles": record.smiles,
                    "formula": record.formula,
                    "mass": record.mass,
                    "error": round(error, 5),
                    "error_ppm": round(error / max(1e-9, record.mass) * 1e6, 2),
                    "family": record.family,
                    "cas": record.cas,
                    "score": round(1.0 / (1.0 + abs(error) * 100.0), 4),
                }
            )
    results.sort(key=lambda item: abs(item["error"]))
    return results[: max(1, int(limit))]


def search_by_formula(formula: str) -> List[Dict[str, Any]]:
    """Return every record whose element counts match ``formula``."""
    target = parse_formula(formula)
    matches = []
    for record in COMPOUND_LIBRARY:
        if parse_formula(record.formula) == target:
            matches.append(asdict(record))
    return matches


def search_by_name(query: str, limit: int = 10) -> List[Dict[str, Any]]:
    """Substring search on the compound name."""
    needle = str(query or "").strip().lower()
    if not needle:
        return []
    matches = [
        asdict(record)
        for record in COMPOUND_LIBRARY
        if needle in record.name.lower()
    ]
    return matches[: max(1, int(limit))]


def similar_spectra(
    query_x: Sequence[float],
    query_y: Sequence[float],
    tolerance: float = 0.02,
    limit: int = 10,
) -> List[Dict[str, Any]]:
    """Match a query peak list against the library fragment lists.

    The score is the weighted cosine similarity (GNPS style) between the query
    and each library entry expanded into a synthetic peak list.
    """
    from workflow_engine.processing import cosine_similarity

    scores = []
    for record in COMPOUND_LIBRARY:
        reference_x = [float(record.mass) + 1.00728] + [
            float(item) for item in record.fragments
        ]
        reference_y = [100.0] + [
            45.0 / (index + 1) for index in range(len(record.fragments))
        ]
        score = cosine_similarity(
            query_x, query_y, reference_x, reference_y, tolerance=tolerance
        )
        scores.append(
            {
                "name": record.name,
                "smiles": record.smiles,
                "formula": record.formula,
                "score": round(float(score), 4),
            }
        )
    scores.sort(key=lambda item: -item["score"])
    return scores[: max(1, int(limit))]


def library_stats() -> Dict[str, Any]:
    """Small summary used by ``/api/databases``."""
    families: Dict[str, int] = {}
    for record in COMPOUND_LIBRARY:
        families[record.family or "other"] = families.get(record.family or "other", 0) + 1
    return {
        "compounds": len(COMPOUND_LIBRARY),
        "families": families,
        "mass_range": [
            min(record.mass for record in COMPOUND_LIBRARY),
            max(record.mass for record in COMPOUND_LIBRARY),
        ],
    }

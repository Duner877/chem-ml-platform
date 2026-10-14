"""Offline materials reference library.

Same philosophy as :mod:`databases.local_library`: a small, hand checked set of
well known compounds used whenever the online services (Materials Project,
COD, AFLOW, ...) are unreachable.  Each record carries a real crystal system,
space group and lattice parameters together with a few application properties
so that the materials nodes can return physically meaningful objects offline.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from workflow_engine.processing import parse_formula

__all__ = [
    "MaterialRecord",
    "MATERIALS_LIBRARY",
    "search_by_formula",
    "search_by_name",
    "search_by_element",
    "similar_cell",
    "materials_stats",
]


@dataclass
class MaterialRecord:
    """One entry of the offline materials library."""

    name: str
    formula: str
    crystal_system: str
    spacegroup: str
    a: float
    b: float
    c: float
    alpha: float = 90.0
    beta: float = 90.0
    gamma: float = 90.0
    family: str = ""
    band_gap_ev: Optional[float] = None
    density_g_cm3: Optional[float] = None
    application: str = ""
    notes: str = ""


MATERIALS_LIBRARY: List[MaterialRecord] = [
    MaterialRecord(
        name="Lithium iron phosphate",
        formula="LiFePO4",
        crystal_system="orthorhombic",
        spacegroup="Pnma",
        a=10.33, b=6.01, c=4.69,
        family="battery cathode",
        band_gap_ev=0.3,
        density_g_cm3=3.60,
        application="Li-ion battery cathode (olivine)",
        notes="Flat 3.45 V plateau vs Li/Li+, excellent thermal stability.",
    ),
    MaterialRecord(
        name="Lithium cobalt oxide",
        formula="LiCoO2",
        crystal_system="rhombohedral",
        spacegroup="R-3m",
        a=2.82, b=2.82, c=14.05, alpha=90.0, beta=90.0, gamma=120.0,
        family="battery cathode",
        band_gap_ev=1.1,
        density_g_cm3=5.05,
        application="Layered Li-ion cathode",
    ),
    MaterialRecord(
        name="NMC811",
        formula="LiNi0.8Mn0.1Co0.1O2",
        crystal_system="rhombohedral",
        spacegroup="R-3m",
        a=2.87, b=2.87, c=14.23, alpha=90.0, beta=90.0, gamma=120.0,
        family="battery cathode",
        band_gap_ev=0.9,
        density_g_cm3=4.80,
        application="High-Ni layered cathode",
    ),
    MaterialRecord(
        name="Graphite",
        formula="C",
        crystal_system="hexagonal",
        spacegroup="P63/mmc",
        a=2.46, b=2.46, c=6.71, alpha=90.0, beta=90.0, gamma=120.0,
        family="battery anode",
        band_gap_ev=0.0,
        density_g_cm3=2.26,
        application="Li-ion anode (intercalation)",
    ),
    MaterialRecord(
        name="Silicon",
        formula="Si",
        crystal_system="cubic",
        spacegroup="Fd-3m",
        a=5.43, b=5.43, c=5.43,
        family="semiconductor",
        band_gap_ev=1.12,
        density_g_cm3=2.33,
        application="Wafer / high capacity anode",
    ),
    MaterialRecord(
        name="Anatase TiO2",
        formula="TiO2",
        crystal_system="tetragonal",
        spacegroup="I41/amd",
        a=3.78, b=3.78, c=9.51,
        family="photocatalyst",
        band_gap_ev=3.20,
        density_g_cm3=3.89,
        application="Photocatalysis, dye sensitised solar cells",
    ),
    MaterialRecord(
        name="Rutile TiO2",
        formula="TiO2",
        crystal_system="tetragonal",
        spacegroup="P42/mnm",
        a=4.59, b=4.59, c=2.96,
        family="photocatalyst",
        band_gap_ev=3.02,
        density_g_cm3=4.23,
        application="Pigment, photocatalysis",
    ),
    MaterialRecord(
        name="Zinc oxide",
        formula="ZnO",
        crystal_system="hexagonal",
        spacegroup="P63mc",
        a=3.25, b=3.25, c=5.21, alpha=90.0, beta=90.0, gamma=120.0,
        family="semiconductor",
        band_gap_ev=3.30,
        density_g_cm3=5.61,
        application="Transparent conducting oxide, sensors",
    ),
    MaterialRecord(
        name="Molybdenum disulfide",
        formula="MoS2",
        crystal_system="hexagonal",
        spacegroup="P63/mmc",
        a=3.16, b=3.16, c=12.30, alpha=90.0, beta=90.0, gamma=120.0,
        family="2D material",
        band_gap_ev=1.23,
        density_g_cm3=5.06,
        application="HER catalysis, solid lubrication",
    ),
    MaterialRecord(
        name="Methylammonium lead iodide",
        formula="CH6NPbI3",
        crystal_system="tetragonal",
        spacegroup="I4/mcm",
        a=8.85, b=8.85, c=12.66,
        family="perovskite",
        band_gap_ev=1.55,
        density_g_cm3=4.16,
        application="Perovskite solar cell absorber",
    ),
    MaterialRecord(
        name="Barium titanate",
        formula="BaTiO3",
        crystal_system="tetragonal",
        spacegroup="P4mm",
        a=3.99, b=3.99, c=4.03,
        family="dielectric",
        band_gap_ev=3.20,
        density_g_cm3=6.02,
        application="Multilayer ceramic capacitors, piezoelectrics",
    ),
    MaterialRecord(
        name="Platinum",
        formula="Pt",
        crystal_system="cubic",
        spacegroup="Fm-3m",
        a=3.92, b=3.92, c=3.92,
        family="catalyst",
        band_gap_ev=0.0,
        density_g_cm3=21.45,
        application="HER / ORR electrocatalyst",
    ),
    MaterialRecord(
        name="Copper",
        formula="Cu",
        crystal_system="cubic",
        spacegroup="Fm-3m",
        a=3.61, b=3.61, c=3.61,
        family="catalyst",
        band_gap_ev=0.0,
        density_g_cm3=8.96,
        application="CO2 reduction electrocatalyst, interconnects",
    ),
    MaterialRecord(
        name="Hematite",
        formula="Fe2O3",
        crystal_system="rhombohedral",
        spacegroup="R-3c",
        a=5.04, b=5.04, c=13.75, alpha=90.0, beta=90.0, gamma=120.0,
        family="photocatalyst",
        band_gap_ev=2.10,
        density_g_cm3=5.26,
        application="Photoanode for water splitting",
    ),
    MaterialRecord(
        name="Lithium lanthanum zirconate",
        formula="Li7La3Zr2O12",
        crystal_system="cubic",
        spacegroup="Ia-3d",
        a=12.97, b=12.97, c=12.97,
        family="solid electrolyte",
        band_gap_ev=4.0,
        density_g_cm3=5.10,
        application="Garnet solid state electrolyte",
    ),
    MaterialRecord(
        name="Perovskite strontium titanate",
        formula="SrTiO3",
        crystal_system="cubic",
        spacegroup="Pm-3m",
        a=3.90, b=3.90, c=3.90,
        family="dielectric",
        band_gap_ev=3.25,
        density_g_cm3=5.11,
        application="Substrate, photocatalysis",
    ),
    MaterialRecord(
        name="Zeolite ZSM-5 (all silica)",
        formula="Si96O192",
        crystal_system="orthorhombic",
        spacegroup="Pnma",
        a=20.09, b=19.74, c=13.14,
        family="zeolite",
        band_gap_ev=6.5,
        density_g_cm3=1.80,
        application="Shape selective catalysis, adsorption",
    ),
]


def _to_dict(record: MaterialRecord) -> Dict[str, Any]:
    payload = asdict(record)
    payload["composition"] = {
        element: count for element, count in sorted(parse_formula(record.formula).items())
    }
    return payload


def search_by_formula(formula: str) -> List[Dict[str, Any]]:
    """Return every record whose element counts match ``formula``."""
    target = parse_formula(formula)
    return [_to_dict(record) for record in MATERIALS_LIBRARY if parse_formula(record.formula) == target]


def search_by_name(query: str, limit: int = 10) -> List[Dict[str, Any]]:
    """Substring search on the material name or formula."""
    needle = str(query or "").strip().lower()
    if not needle:
        return []
    matches = [
        _to_dict(record)
        for record in MATERIALS_LIBRARY
        if needle in record.name.lower() or needle in record.formula.lower()
    ]
    return matches[:limit]


def search_by_element(element: str, limit: int = 20) -> List[Dict[str, Any]]:
    """Return every record containing ``element``."""
    target = str(element or "").strip().capitalize()
    if not target:
        return []
    matches = [
        _to_dict(record)
        for record in MATERIALS_LIBRARY
        if target in parse_formula(record.formula)
    ]
    return matches[:limit]


def similar_cell(
    a: float, b: float, c: float, tolerance: float = 0.5, limit: int = 10
) -> List[Dict[str, Any]]:
    """Rank the library by lattice parameter distance."""

    def distance(record: MaterialRecord) -> float:
        return (
            abs(record.a - float(a))
            + abs(record.b - float(b))
            + abs(record.c - float(c))
        ) / 3.0

    ranked = sorted(
        ((distance(record), record) for record in MATERIALS_LIBRARY),
        key=lambda item: item[0],
    )
    return [
        dict(_to_dict(record), cell_distance=round(value, 4))
        for value, record in ranked
        if value <= tolerance
    ][:limit]


def materials_stats() -> Dict[str, Any]:
    """Small summary used by ``/api/databases``."""
    families: Dict[str, int] = {}
    systems: Dict[str, int] = {}
    for record in MATERIALS_LIBRARY:
        families[record.family or "other"] = families.get(record.family or "other", 0) + 1
        systems[record.crystal_system] = systems.get(record.crystal_system, 0) + 1
    return {
        "count": len(MATERIALS_LIBRARY),
        "families": families,
        "crystal_systems": systems,
    }

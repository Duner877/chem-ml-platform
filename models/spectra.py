"""First-principles-flavoured spectral predictors.

The functions below generate **synthetic but physically parameterised** spectra
used by the instrument nodes when no measurement file is supplied.  Each model is
built from published tables / classical formulas so the numbers are meaningful:

=====================  =========================================================
``predict_ms``         monoisotopic mass + exact isotope envelope (natural
                       abundances) + heuristic neutral-loss fragmentation
``predict_nmr``        1H chemical shift table + J-multiplets, synthesised as a
                       time-domain FID and Fourier transformed
``predict_ir``         functional group frequency table (Socrates), Lorentzian
                       band shapes
``predict_raman``      Raman group frequency table
``predict_uvvis``      Woodward-Fieser diene/enone rules + aromatic bands
``predict_fluorescence``  mirror-image emission with a Stokes shift
=====================  =========================================================

They are *not* replacements for measured data -- every node records the
``synthetic`` flag in its output metadata.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from workflow_engine.objects import Peak, Spectrum
from workflow_engine.processing import formula_mass, isotope_pattern, parse_formula
from .smiles import MolecularGraph, parse_smiles
from .substructure import detect_functional_groups, has_substructure

__all__ = [
    "predict_ms",
    "predict_nmr",
    "predict_ir",
    "predict_raman",
    "predict_uvvis",
    "predict_fluorescence",
    "IR_GROUP_FREQUENCIES",
    "RAMAN_GROUP_FREQUENCIES",
    "NMR_SHIFT_TABLE",
    "XPS_BINDING_ENERGIES",
    "XAS_K_EDGES",
]


def _gaussian_profile(
    grid: np.ndarray, centers: Sequence[float], heights: Sequence[float], widths: Sequence[float]
) -> np.ndarray:
    curve = np.zeros_like(grid)
    for center, height, width in zip(centers, heights, widths):
        if width <= 0:
            continue
        curve += height * np.exp(-0.5 * ((grid - center) / width) ** 2)
    return curve


# --------------------------------------------------------------------------- #
# Mass spectrometry
# --------------------------------------------------------------------------- #
#: Common neutral losses (Da) observed in positive mode LC-MS/MS.
NEUTRAL_LOSSES: Tuple[Tuple[str, float, float], ...] = (
    ("H2O", 18.01056, 0.35),
    ("CO", 27.99491, 0.30),
    ("NH3", 17.02655, 0.25),
    ("CO2", 43.98983, 0.22),
    ("CH3", 15.02348, 0.18),
    ("HCN", 27.01090, 0.15),
    ("C2H4", 28.03130, 0.12),
)


def predict_ms(
    smiles: str,
    adduct: str = "[M+H]+",
    polarity: str = "positive",
    resolution: float = 8000.0,
    max_mz: float = 1200.0,
    points: int = 4000,
    noise: float = 0.004,
    rng: np.random.Generator | None = None,
) -> Spectrum:
    """Predict a profile-mode MS spectrum for ``smiles``."""
    graph = parse_smiles(smiles)
    formula = graph.formula()
    neutral = formula_mass(graph.formula_string())
    envelope = isotope_pattern(graph.formula_string(), adduct=adduct)
    if not envelope:
        envelope = [(neutral, 1.0)]

    grid = np.linspace(0.0, float(max_mz), int(points))
    profile = np.zeros_like(grid)
    rng = rng or np.random.default_rng(1017)

    for mz, abundance in envelope:
        width = max(1e-4, float(mz) / float(resolution))
        profile += abundance * np.exp(-0.5 * ((grid - mz) / width) ** 2)

    peaks: List[Peak] = []
    for mz, abundance in envelope:
        peaks.append(
            Peak(
                x=round(float(mz), 4),
                y=round(float(abundance) * 100.0, 3),
                intensity=round(float(abundance) * 100.0, 3),
                assignment=f"{graph.formula_string()} {adduct}",
            )
        )

    # heuristic fragmentation
    for label, loss, weight in NEUTRAL_LOSSES:
        fragment = float(envelope[0][0]) - loss
        if fragment <= 0:
            continue
        width = max(1e-4, fragment / float(resolution))
        profile += 0.45 * weight * np.exp(-0.5 * ((grid - fragment) / width) ** 2)
        peaks.append(
            Peak(
                x=round(fragment, 4),
                y=round(45.0 * weight, 3),
                intensity=round(45.0 * weight, 3),
                assignment=f"loss of {label}",
            )
        )

    if noise > 0:
        profile += np.abs(rng.normal(0.0, noise, profile.shape))
    profile = np.maximum(profile, 0.0)
    scale = float(np.max(profile)) or 1.0
    profile = profile / scale * 100.0
    for peak in peaks:
        peak.y = round(peak.y, 3)
    peaks.sort(key=lambda item: item.x)

    return Spectrum(
        mode="MS",
        technique="LC-MS" if adduct.startswith("[M+") else "MS",
        name=f"predicted {adduct} spectrum",
        x=[float(value) for value in grid],
        y=[float(value) for value in profile],
        x_unit="m/z",
        y_unit="relative intensity",
        peaks=peaks,
        precursor_mz=round(float(envelope[0][0]), 4),
        polarity=polarity,
        metadata={
            "formula": graph.formula_string(),
            "neutral_monoisotopic_mass": round(float(neutral), 5),
            "adduct": adduct,
            "resolution": resolution,
            "synthetic": True,
            "model": "monoisotopic mass + natural abundance isotope envelope + heuristic neutral losses",
        },
    )


# --------------------------------------------------------------------------- #
# NMR
# --------------------------------------------------------------------------- #
#: Approximate 1H chemical shift table (ppm) keyed by environment.
NMR_SHIFT_TABLE: Dict[str, float] = {
    "alkyl_CH3": 0.90,
    "alkyl_CH2": 1.30,
    "alkyl_CH": 1.70,
    "allylic_CH3": 1.70,
    "alpha_carbonyl_CH3": 2.10,
    "benzylic_CH3": 2.30,
    "alkyne_CH": 2.50,
    "N_CH3": 2.50,
    "O_CH3": 3.30,
    "O_CH2": 3.60,
    "halogen_CH": 3.80,
    "alkene_CH": 5.50,
    "aromatic_CH": 7.20,
    "aldehyde_CH": 9.70,
    "carboxylic_acid_H": 11.00,
    "phenol_OH": 6.50,
    "alcohol_OH": 2.50,
    "amine_NH": 3.00,
    "amide_NH": 7.80,
}


def _classify_proton(graph: MolecularGraph, index: int) -> str:
    """Assign a proton environment label to the atom at ``index``."""
    atom = graph.atoms[index]
    element = atom.get("element", "C")
    adjacency = graph.adjacency()
    neighbours = [
        graph.atoms[neighbour]["element"] for neighbour, _ in adjacency[index]
    ]

    if element == "O":
        return "alcohol_OH"
    if element == "N":
        return "amide_NH" if "C=O" in _neighbour_patterns(graph, index) else "amine_NH"
    if element == "C" and atom.get("aromatic"):
        return "aromatic_CH"
    if "O" in neighbours:
        return "O_CH3" if len(neighbours) == 1 else "O_CH2"
    if "N" in neighbours:
        return "N_CH3"
    if any(item in {"F", "Cl", "Br", "I"} for item in neighbours):
        return "halogen_CH"
    if any(item in {"C"} for item in neighbours):
        carbonyl = _has_carbonyl_neighbour(graph, index)
        if carbonyl:
            return "alpha_carbonyl_CH3"
        double = _has_double_bond_neighbour(graph, index)
        if double:
            return "alkene_CH"
    return "alkyl_CH3"


def _neighbour_patterns(graph: MolecularGraph, index: int) -> List[str]:
    return [
        graph.atoms[neighbour]["element"]
        for neighbour, _ in graph.adjacency()[index]
    ]


def _has_carbonyl_neighbour(graph: MolecularGraph, index: int) -> bool:
    for neighbour, order in graph.adjacency()[index]:
        if abs(float(order) - 2.0) < 1e-6:
            for outer, _ in graph.adjacency()[neighbour]:
                if graph.atoms[outer]["element"] == "O" and outer != index:
                    return True
    return False


def _has_double_bond_neighbour(graph: MolecularGraph, index: int) -> bool:
    return any(
        abs(float(order) - 2.0) < 1e-6 for _, order in graph.adjacency()[index]
    )


def predict_nmr(
    smiles: str,
    nucleus: str = "1H",
    frequency_mhz: float = 400.13,
    points: int = 16384,
    line_broadening: float = 1.0,
    noise: float = 0.01,
    seed: int = 19,
) -> Spectrum:
    """Predict a 1H NMR spectrum.

    Hydrogen bearing atoms are grouped into environments, assigned a shift
    from :data:`NMR_SHIFT_TABLE`, split into a binomial multiplet and then
    rendered as an exponentially decaying FID which is Fourier transformed.
    """
    graph = parse_smiles(smiles)
    rng = np.random.default_rng(seed)
    adjacency = graph.adjacency()

    signals: List[Dict[str, float]] = []
    for atom in graph.atoms:
        hydrogens = int(atom.get("hydrogens", 0) or 0)
        if hydrogens <= 0:
            continue
        environment = _classify_proton(graph, atom["index"])
        shift = NMR_SHIFT_TABLE.get(environment, 2.0)
        # small dispersion so equivalent-looking groups do not overlap exactly
        shift += rng.uniform(-0.06, 0.06)
        vicinal = sum(
            int(graph.atoms[neighbour].get("hydrogens", 0) or 0)
            for neighbour, _ in adjacency[atom["index"]]
        )
        signals.append(
            {
                "ppm": round(float(shift), 3),
                "intensity": float(hydrogens),
                "multiplicity": max(1, min(6, 1 + vicinal)),
                "j": 7.0,
                "assignment": environment,
            }
        )

    if not signals:
        signals = [{"ppm": 0.0, "intensity": 1.0, "multiplicity": 1, "j": 7.0}]

    # Synthesise the FID and transform it (reuses the Bruker DSP code path).
    from workflow_engine.parsers.bruker import fid_to_spectrum, synthesize_fid

    fid = synthesize_fid(
        signals,
        points=int(points),
        spectral_width_hz=float(frequency_mhz) * 15.0,
        spectrometer_mhz=float(frequency_mhz),
        relaxation=0.55,
        noise=float(noise),
    )
    spectrum = fid_to_spectrum(
        fid,
        sf=float(frequency_mhz),
        sw_ppm=15.0,
        offset_hz=6.0 * float(frequency_mhz),
        line_broadening=float(line_broadening),
        name="predicted 1H NMR",
    )
    spectrum.mode = "NMR"
    spectrum.technique = f"{nucleus} NMR"
    spectrum.x_unit = "ppm"
    spectrum.peaks = sorted(
        [
            Peak(
                x=round(float(signal["ppm"]), 3),
                y=round(float(signal["intensity"]), 3),
                intensity=round(float(signal["intensity"]), 3),
                assignment=str(signal["assignment"]),
            )
            for signal in signals
        ],
        key=lambda item: -item.x,
    )
    spectrum.metadata.update(
        {"nucleus": nucleus, "frequency_mhz": frequency_mhz, "synthetic": True}
    )
    return spectrum


# --------------------------------------------------------------------------- #
# Vibrational / electronic spectroscopy
# --------------------------------------------------------------------------- #
#: Characteristic IR bands per functional group:
#: ``group -> [(cm-1, relative intensity, assignment)]``
IR_BANDS: Dict[str, List[Tuple[float, float, str]]] = {
    "alcohol": [
        (3350.0, 0.75, "O-H stretch (alcohol)"),
        (1050.0, 0.55, "C-O stretch"),
    ],
    "phenol": [
        (3300.0, 0.60, "O-H stretch (phenol)"),
        (1220.0, 0.60, "C-O stretch"),
    ],
    "carboxylic_acid": [
        (3000.0, 0.55, "O-H stretch (carboxylic acid)"),
        (1710.0, 0.95, "C=O stretch"),
        (1280.0, 0.60, "C-O stretch"),
    ],
    "ester": [
        (1735.0, 0.95, "C=O stretch (ester)"),
        (1200.0, 0.70, "C-O stretch"),
    ],
    "amide": [
        (1650.0, 0.90, "C=O stretch (amide I)"),
        (1550.0, 0.60, "N-H bend (amide II)"),
        (3300.0, 0.50, "N-H stretch"),
    ],
    "ketone": [(1715.0, 0.95, "C=O stretch (ketone)")],
    "aldehyde": [
        (1725.0, 0.90, "C=O stretch (aldehyde)"),
        (2820.0, 0.45, "C-H aldehyde Fermi doublet"),
        (2720.0, 0.45, "C-H aldehyde Fermi doublet"),
    ],
    "ether": [(1100.0, 0.55, "C-O-C stretch")],
    "primary_amine": [
        (3400.0, 0.45, "N-H asymmetric stretch (primary amine)"),
        (3320.0, 0.40, "N-H symmetric stretch (primary amine)"),
    ],
    "secondary_amine": [(3350.0, 0.40, "N-H stretch (secondary amine)")],
    "tertiary_amine": [(1200.0, 0.35, "C-N stretch (tertiary amine)")],
    "nitrile": [(2250.0, 0.85, "C=N stretch (nitrile)")],
    "alkyne": [
        (2150.0, 0.60, "C≡C stretch"),
        (3300.0, 0.70, "≡C-H stretch"),
    ],
    "alkene": [
        (3010.0, 0.45, "=C-H stretch"),
        (1650.0, 0.55, "C=C stretch"),
    ],
    "aromatic_ring": [
        (3030.0, 0.40, "aromatic C-H stretch"),
        (1600.0, 0.60, "aromatic C=C stretch"),
        (1500.0, 0.45, "aromatic C=C stretch"),
    ],
    "aryl_chloride": [
        (1090.0, 0.45, "aromatic C-Cl stretch"),
        (700.0, 0.50, "C-Cl bend"),
    ],
    "aryl_bromide": [
        (1070.0, 0.35, "aromatic C-Br stretch"),
        (650.0, 0.45, "C-Br bend"),
    ],
    "nitro": [
        (1520.0, 0.85, "N=O asymmetric stretch"),
        (1350.0, 0.80, "N=O symmetric stretch"),
    ],
    "sulfone": [
        (1300.0, 0.75, "S=O asymmetric stretch"),
        (1150.0, 0.75, "S=O symmetric stretch"),
    ],
    "thiol": [(2550.0, 0.35, "S-H stretch")],
    "alkane": [
        (2960.0, 0.70, "C-H stretch"),
        (1465.0, 0.45, "C-H bend"),
        (1375.0, 0.35, "C-H bend"),
    ],
    "carbonyl": [(1700.0, 0.80, "C=O stretch")],
}

#: Raman active bands per functional group.
RAMAN_BANDS: Dict[str, List[Tuple[float, float, str]]] = {
    "aromatic_ring": [
        (1000.0, 1.00, "aromatic ring breathing"),
        (1600.0, 0.70, "aromatic C=C stretch"),
        (620.0, 0.35, "ring deformation"),
    ],
    "alkene": [(1650.0, 0.60, "C=C stretch")],
    "alkyne": [(2150.0, 0.80, "C≡C stretch")],
    "nitrile": [(2250.0, 0.85, "C≡N stretch")],
    "carbonyl": [(1700.0, 0.55, "C=O stretch")],
    "alkane": [
        (2900.0, 0.55, "C-H stretch"),
        (1450.0, 0.40, "C-H bend"),
    ],
    "sulfone": [(1140.0, 0.45, "S=O symmetric stretch")],
}


def predict_ir(smiles: str, points: int = 1800, noise: float = 0.004) -> Spectrum:
    """Predict an IR absorption spectrum from detected functional groups."""
    graph = parse_smiles(smiles)
    grid = np.linspace(400.0, 4000.0, int(points))
    absorbance = np.zeros_like(grid)
    peaks: List[Peak] = []

    groups = detect_functional_groups(graph)
    if not groups:
        groups = {"alkane": 1}

    for group, count in sorted(groups.items()):
        bands = IR_BANDS.get(group)
        if not bands:
            continue
        for center, intensity, label in bands:
            width = 35.0 if center > 1500 else 25.0
            weight = float(intensity) * min(3.0, float(count))
            absorbance += weight * np.exp(-0.5 * ((grid - center) / width) ** 2)
            peaks.append(
                Peak(
                    x=float(center),
                    y=round(weight * 100.0, 2),
                    intensity=round(weight * 100.0, 2),
                    assignment=label,
                )
            )

    rng = np.random.default_rng(20240521)
    if noise > 0:
        absorbance += np.abs(rng.normal(0.0, noise, absorbance.shape))
    scale = float(np.max(absorbance)) or 1.0
    absorbance = absorbance / scale * 1.5
    for peak in peaks:
        peak.y = round(peak.y / 1.5, 2)
        peak.intensity = peak.y
    peaks.sort(key=lambda item: -item.y)

    return Spectrum(
        mode="IR",
        technique="FTIR",
        name="predicted IR spectrum",
        x=[float(value) for value in grid],
        y=[float(value) for value in absorbance],
        x_unit="cm-1",
        y_unit="absorbance",
        peaks=peaks[:30],
        metadata={
            "synthetic": True,
            "groups": groups,
            "model": "group frequency table + Gaussian bands",
        },
    )


def predict_raman(smiles: str, points: int = 1800, noise: float = 0.004) -> Spectrum:
    """Predict a Raman spectrum (aromatic ring modes dominate)."""
    graph = parse_smiles(smiles)
    grid = np.linspace(200.0, 3500.0, int(points))
    curve = np.zeros_like(grid)

    groups = detect_functional_groups(graph)
    if not groups:
        groups = {"alkane": 1}

    peaks: List[Peak] = []
    for group, count in sorted(groups.items()):
        bands = RAMAN_BANDS.get(group)
        if not bands:
            continue
        for center, intensity, label in bands:
            width = 28.0 if center < 2000 else 60.0
            weight = float(intensity) * min(3.0, float(count))
            curve += weight * np.exp(-0.5 * ((grid - center) / width) ** 2)
            peaks.append(
                Peak(
                    x=float(center),
                    y=round(weight * 100.0, 2),
                    intensity=round(weight * 100.0, 2),
                    assignment=label,
                )
            )

    rng = np.random.default_rng(20240611)
    if noise > 0:
        curve += np.abs(rng.normal(0.0, noise, curve.shape))
    scale = float(np.max(curve)) or 1.0
    curve = curve / scale * 100.0
    for peak in peaks:
        peak.y = round(peak.y, 2)
        peak.intensity = peak.y
    peaks.sort(key=lambda item: -item.y)

    return Spectrum(
        mode="Raman",
        technique="Raman",
        name="predicted Raman spectrum",
        x=[float(value) for value in grid],
        y=[float(value) for value in curve],
        x_unit="cm-1",
        y_unit="intensity",
        peaks=peaks[:30],
        metadata={"synthetic": True, "groups": groups},
    )


def predict_uvvis(
    smiles: str, points: int = 400, noise: float = 0.002, seed: int = 23
) -> Spectrum:
    """Predict a UV-Vis spectrum with Woodward-Fieser style rules."""
    graph = parse_smiles(smiles)
    grid = np.linspace(200.0, 800.0, int(points))

    conjugated = has_substructure(graph, "C=CC=C")
    aromatic = has_substructure(graph, "c1ccccc1")
    carbonyl = has_substructure(graph, "C=O")

    bands: List[Tuple[float, float, str]] = []
    if conjugated:
        bands.append((217.0, 0.85, "diene pi->pi*"))
    if aromatic:
        bands.append((254.0, 0.70, "aromatic pi->pi* (E2)"))
        bands.append((204.0, 0.65, "aromatic pi->pi* (E1)"))
    if carbonyl:
        bands.append((280.0, 0.35, "carbonyl n->pi*"))
    if not bands:
        bands.append((210.0, 0.40, "sigma->sigma* / n->sigma*"))

    absorbance = np.zeros_like(grid)
    peaks: List[Peak] = []
    for center, intensity, label in bands:
        width = 30.0
        absorbance += intensity * np.exp(-0.5 * ((grid - center) / width) ** 2)
        peaks.append(
            Peak(
                x=float(center),
                y=round(float(intensity), 3),
                intensity=round(float(intensity), 3),
                assignment=label,
            )
        )

    rng = np.random.default_rng(seed)
    if noise > 0:
        absorbance += np.abs(rng.normal(0.0, noise, absorbance.shape))
    return Spectrum(
        mode="UV-Vis",
        technique="UV-Vis",
        name="predicted UV-Vis spectrum",
        x=[float(value) for value in grid],
        y=[float(value) for value in absorbance],
        x_unit="nm",
        y_unit="absorbance",
        peaks=peaks,
        metadata={"synthetic": True, "model": "Woodward-Fieser approximation"},
    )


def predict_fluorescence(
    smiles: str,
    excitation_nm: float = 260.0,
    stokes_shift_nm: float = 70.0,
    points: int = 400,
    noise: float = 0.002,
    seed: int = 29,
) -> Spectrum:
    """Predict an emission spectrum (mirror image + Stokes shift)."""
    rng = np.random.default_rng(seed)
    grid = np.linspace(excitation_nm + 20.0, 800.0, int(points))
    emission = np.exp(-0.5 * ((grid - (excitation_nm + stokes_shift_nm)) / 55.0) ** 2)
    emission += 0.28 * np.exp(
        -0.5 * ((grid - (excitation_nm + stokes_shift_nm + 95.0)) / 70.0) ** 2
    )
    if noise > 0:
        emission += np.abs(rng.normal(0.0, noise, emission.shape))
    emission = emission / (float(np.max(emission)) or 1.0) * 100.0
    return Spectrum(
        mode="Fluorescence",
        technique="Fluorescence emission",
        name="predicted emission spectrum",
        x=[float(value) for value in grid],
        y=[float(value) for value in emission],
        x_unit="nm",
        y_unit="intensity",
        peaks=[
            Peak(
                x=round(float(excitation_nm + stokes_shift_nm), 1),
                y=100.0,
                intensity=100.0,
                assignment="emission maximum",
            )
        ],
        metadata={
            "synthetic": True,
            "excitation_nm": excitation_nm,
            "stokes_shift_nm": stokes_shift_nm,
        },
    )


# --------------------------------------------------------------------------- #
# X-ray spectroscopies
# --------------------------------------------------------------------------- #
#: Core level binding energies (eV) used by the XPS / XAS nodes.
XPS_BINDING_ENERGIES: Dict[str, Dict[str, float]] = {
    "C": {"1s": 284.8},
    "N": {"1s": 399.6},
    "O": {"1s": 531.6},
    "F": {"1s": 685.0},
    "Na": {"1s": 1071.0},
    "Mg": {"1s": 1303.0},
    "Al": {"2p": 74.0},
    "Si": {"2p": 99.4},
    "P": {"2p": 133.0},
    "S": {"2p": 164.0},
    "Cl": {"2p": 199.0},
    "K": {"2p": 294.0},
    "Ca": {"2p": 347.0},
    "Ti": {"2p3/2": 458.8},
    "Mn": {"2p3/2": 641.0},
    "Fe": {"2p3/2": 710.0},
    "Co": {"2p3/2": 780.0},
    "Ni": {"2p3/2": 854.0},
    "Cu": {"2p3/2": 932.6},
    "Zn": {"2p3/2": 1021.8},
    "Se": {"3d": 55.0},
    "Br": {"3d": 70.0},
    "I": {"3d5/2": 619.0},
    "Li": {"1s": 55.0},
}

#: K-edge / L3-edge energies (eV) used by the XAS node.
XAS_K_EDGES: Dict[str, float] = {
    "C": 284.0, "N": 410.0, "O": 543.0, "F": 697.0, "Na": 1071.0,
    "Mg": 1303.0, "Al": 1559.0, "Si": 1839.0, "P": 2145.0, "S": 2472.0,
    "Cl": 2822.0, "K": 3608.0, "Ca": 4038.0, "Ti": 4966.0, "Mn": 6539.0,
    "Fe": 7112.0, "Co": 7709.0, "Ni": 8333.0, "Cu": 8979.0, "Zn": 9659.0,
    "Li": 55.0,
}


def _lorentzian(grid: np.ndarray, center: float, height: float, width: float) -> np.ndarray:
    return height / (1.0 + ((grid - center) / max(1e-9, width)) ** 2)


def predict_xps(
    composition: Sequence[Dict[str, Any]],
    noise: float = 0.01,
    seed: int = 31,
) -> Spectrum:
    """Predict an XPS survey scan from a list of ``{element, fraction}``."""
    rng = np.random.default_rng(seed)
    grid = np.linspace(1200.0, 0.0, 1200)  # conventional reversed axis
    counts = np.zeros_like(grid)
    peaks: List[Peak] = []
    for entry in composition or []:
        element = str(entry.get("element", "")).strip().capitalize()
        fraction = float(entry.get("fraction", 0.0) or 0.0)
        levels = XPS_BINDING_ENERGIES.get(element)
        if not levels or fraction <= 0:
            continue
        for level, energy in levels.items():
            counts += fraction * 100.0 * _lorentzian(grid, energy, 1.0, 1.6)
            peaks.append(
                Peak(
                    x=float(energy),
                    y=round(fraction * 100.0, 2),
                    intensity=round(fraction * 100.0, 2),
                    assignment=f"{element} {level}",
                )
            )
    if noise > 0:
        counts += np.abs(rng.normal(0.0, noise, counts.shape))
    return Spectrum(
        mode="XPS",
        technique="XPS survey",
        name="predicted XPS survey",
        x=[float(value) for value in grid],
        y=[float(value) for value in counts],
        x_unit="eV",
        y_unit="counts (a.u.)",
        peaks=peaks,
        metadata={"synthetic": True, "model": "core level binding energy table"},
    )


def predict_xas(
    element: str,
    edge: str = "K",
    oxidation_state: float = 0.0,
    noise: float = 0.003,
    seed: int = 37,
) -> Spectrum:
    """Predict a XANES scan: ``arctan`` edge step + damped EXAFS oscillation."""
    rng = np.random.default_rng(seed)
    energy_edge = XAS_K_EDGES.get(str(element).capitalize(), 500.0)
    # Higher oxidation states shift the edge to higher energy (Kunzl's law).
    energy_edge += 1.6 * float(oxidation_state)
    if str(edge).upper().startswith("L"):
        energy_edge *= 0.12
    grid = np.linspace(energy_edge - 60.0, energy_edge + 260.0, 900)
    step = 0.5 + (1.0 / math.pi) * np.arctan(0.6 * (grid - energy_edge))
    # EXAFS: k = sqrt(0.2625 * (E - E0))  for E > E0
    excess = np.maximum(grid - energy_edge, 0.0)
    k = np.sqrt(0.2625 * excess)
    oscillation = np.exp(-0.03 * k**2) * np.sin(2.0 * k * 2.0 + 0.4) / np.maximum(k, 0.6)
    white_line = 0.55 * np.exp(-0.5 * ((grid - (energy_edge + 6.0)) / 9.0) ** 2)
    signal = step + white_line + 0.35 * oscillation * (excess > 0.0)
    if noise > 0:
        signal += rng.normal(0.0, noise, signal.shape)
    return Spectrum(
        mode="XAS",
        technique=f"{edge}-edge XANES/EXAFS",
        name=f"predicted {element} {edge}-edge",
        x=[float(value) for value in grid],
        y=[float(value) for value in signal],
        x_unit="eV",
        y_unit="normalized absorption",
        peaks=[
            Peak(
                x=round(float(energy_edge + 6.0), 1),
                y=1.0,
                intensity=1.0,
                assignment=f"{element} {edge}-edge white line",
            )
        ],
        metadata={"synthetic": True, "element": element, "edge": edge},
    )

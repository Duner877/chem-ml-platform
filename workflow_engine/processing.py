"""Signal processing, spectral similarity and chemistry helpers.

Everything in this module is implemented with NumPy (SciPy is used for the
baseline solver when installed, with a dense fallback otherwise) so the
functions are usable both from the nodes and from notebooks / the SDK.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np

from .objects import Peak
from .utils import to_array

__all__ = [
    "moving_average",
    "savitzky_golay",
    "als_baseline",
    "find_peaks",
    "normalize",
    "resample",
    "bin_spectrum",
    "cosine_similarity",
    "match_peaks",
    "parse_formula",
    "formula_mass",
    "isotope_pattern",
    "neutral_mass",
    "adduct_mz",
    "mass_error",
    "ElementDataError",
]

_ELECTRON_MASS = 0.00054857990946


# --------------------------------------------------------------------------- #
# Smoothing / baseline
# --------------------------------------------------------------------------- #
def moving_average(y: Any, window: int = 5) -> np.ndarray:
    """Centred moving average of ``y``."""
    values = to_array(y)
    window = max(1, int(window))
    if values.size == 0 or window == 1:
        return values.copy()
    kernel = np.ones(window, dtype=float) / float(window)
    padded = np.pad(values, (window // 2, window - 1 - window // 2), mode="edge")
    return np.convolve(padded, kernel, mode="valid")


def savitzky_golay(y: Any, window_length: int = 11, polyorder: int = 3) -> np.ndarray:
    """Savitzky-Golay smoothing filter (pure NumPy implementation)."""
    values = to_array(y)
    window_length = int(window_length)
    if window_length % 2 == 0:
        window_length += 1
    window_length = min(window_length, max(3, values.size if values.size % 2 else values.size - 1))
    if values.size < 3 or window_length <= polyorder:
        return values.copy()
    half = window_length // 2
    positions = np.arange(-half, half + 1, dtype=float)
    vander = np.vander(positions, polyorder + 1, increasing=True)
    # pinv keeps the filter stable for any window / order combination
    coeffs = np.linalg.pinv(vander)[0]
    padded = np.pad(values, (half, half), mode="edge")
    return np.convolve(padded, coeffs[::-1], mode="valid")


def als_baseline(
    y: Any, lam: float = 1e5, p: float = 0.01, niter: int = 10
) -> np.ndarray:
    """Asymmetric least squares baseline (Eilers & Boelens, 2005)."""
    values = to_array(y)
    length = values.size
    if length < 3:
        return np.zeros_like(values)

    try:  # pragma: no cover - depends on the environment
        from scipy import sparse
        from scipy.sparse.linalg import spsolve

        identity = sparse.eye(length, format="csc")
        second_diff = sparse.diags(
            [1.0, -2.0, 1.0], [0, 1, 2], shape=(length - 2, length), format="csc"
        )
        penalty = lam * (second_diff.T @ second_diff)
        weights = np.ones(length, dtype=float)
        baseline = values.copy()
        for _ in range(max(1, int(niter))):
            weight_matrix = sparse.diags(weights, 0, format="csc")
            baseline = spsolve((weight_matrix + penalty).tocsc(), weights * values)
            weights = np.where(values > baseline, p, 1.0 - p)
        return baseline
    except ImportError:
        identity = np.eye(length)
        second_diff = np.zeros((length - 2, length))
        for i in range(length - 2):
            second_diff[i, i] = 1.0
            second_diff[i, i + 1] = -2.0
            second_diff[i, i + 2] = 1.0
        penalty = lam * (second_diff.T @ second_diff)
        weights = np.ones(length, dtype=float)
        baseline = values.copy()
        for _ in range(max(1, int(niter))):
            system = np.diag(weights) + penalty
            baseline = np.linalg.solve(system, weights * values)
            weights = np.where(values > baseline, p, 1.0 - p)
        return baseline


# Backwards/forwards friendly alias used by the nodes.
baseline_als = als_baseline


# --------------------------------------------------------------------------- #
# Peak picking
# --------------------------------------------------------------------------- #
def _apex(x: np.ndarray, y: np.ndarray, index: int) -> float:
    """Parabolic refinement of the apex position."""
    if 0 < index < len(y) - 1:
        denom = y[index - 1] - 2.0 * y[index] + y[index + 1]
        if abs(denom) > 1e-12:
            delta = 0.5 * (y[index - 1] - y[index + 1]) / denom
            if abs(delta) <= 1.0:
                step = x[index + 1] - x[index]
                return float(x[index] + delta * step)
    return float(x[index])


def _side_minimum(y: np.ndarray, index: int, step: int) -> float:
    lowest = y[index]
    position = index
    while 0 <= position + step < len(y):
        position += step
        if y[position] > y[index]:
            break
        lowest = min(lowest, y[position])
    return float(lowest)


def find_peaks(
    x: Any,
    y: Any,
    height: float | None = None,
    prominence: float = 0.03,
    distance: float = 0.0,
    max_peaks: int = 200,
) -> List[Peak]:
    """Detect peaks in ``(x, y)``.

    ``height`` and ``prominence`` are expressed as fractions of the maximum
    intensity (or absolute values when ``> 1``).  ``distance`` is given in
    ``x`` units.
    """
    xs = to_array(x)
    ys = to_array(y)
    if xs.size != ys.size or xs.size < 3:
        return []

    peak_max = float(np.max(ys))
    if peak_max <= 0:
        return []
    if height is None:
        height_abs = 0.0
    elif float(height) <= 1.0:
        height_abs = peak_max * float(height)
    else:
        height_abs = float(height)
    prominence_abs = (
        peak_max * float(prominence) if prominence and prominence <= 1 else float(prominence or 0)
    )

    candidates: List[Tuple[int, float, float]] = []
    for i in range(1, len(ys) - 1):
        if ys[i] >= ys[i - 1] and ys[i] > ys[i + 1]:
            if height_abs and ys[i] < height_abs:
                continue
            prom = ys[i] - max(
                _side_minimum(ys, i, -1), _side_minimum(ys, i, 1)
            )
            if prom < prominence_abs:
                continue
            candidates.append((i, _apex(xs, ys, i), float(ys[i])))
    # include a rising/falling edge maximum
    if len(ys) > 1:
        if ys[0] > ys[1]:
            candidates.insert(0, (0, float(xs[0]), float(ys[0])))
        if ys[-1] > ys[-2]:
            candidates.append((len(ys) - 1, float(xs[-1]), float(ys[-1])))

    candidates.sort(key=lambda item: item[2], reverse=True)

    selected: List[Tuple[int, float, float]] = []
    if distance and distance > 0:
        for candidate in candidates:
            if all(
                abs(candidate[1] - chosen[1]) >= distance for chosen in selected
            ):
                selected.append(candidate)
    else:
        selected = candidates
    selected.sort(key=lambda item: item[1])
    return [
        Peak(x=position, y=intensity, intensity=intensity)
        for _, position, intensity in selected[:max_peaks]
    ]


def normalize(y: Any, method: str = "max", x: Any = None) -> np.ndarray:
    """Normalise intensities.

    Supported methods: ``max`` (default), ``area``, ``minmax``, ``snv``,
    ``none``.
    """
    values = to_array(y).astype(float)
    if values.size == 0:
        return values
    method = (method or "max").lower()
    if method == "none":
        return values
    if method == "max":
        scale = float(np.max(np.abs(values)))
        return values / scale if scale else values
    if method == "area":
        if x is not None:
            xs = to_array(x)
            area = float(np.trapz(values, xs)) if xs.size == values.size else float(np.sum(values))
        else:
            area = float(np.sum(values))
        return values / area if area else values
    if method == "minmax":
        low, high = float(np.min(values)), float(np.max(values))
        return (values - low) / (high - low) if high > low else values - low
    if method == "snv":
        centered = values - float(np.mean(values))
        deviation = float(np.std(centered))
        return centered / deviation if deviation else centered
    return values


def resample(x: Any, y: Any, step: float) -> Tuple[np.ndarray, np.ndarray]:
    """Resample ``(x, y)`` on a uniform grid of width ``step``."""
    xs, ys = to_array(x), to_array(y)
    if xs.size < 2:
        return xs, ys
    order = np.argsort(xs)
    xs, ys = xs[order], ys[order]
    grid = np.arange(float(xs[0]), float(xs[-1]) + step, float(step))
    return grid, np.interp(grid, xs, ys)


def bin_spectrum(
    x: Any, y: Any, bin_width: float = 0.01, statistic: str = "max"
) -> Tuple[np.ndarray, np.ndarray]:
    """Bin irregular ``(x, y)`` data onto a regular grid."""
    xs, ys = to_array(x), to_array(y)
    if xs.size == 0:
        return xs, ys
    start, stop = float(np.min(xs)), float(np.max(xs))
    edges = np.arange(start, stop + bin_width, bin_width)
    indices = np.clip(((xs - start) / bin_width).astype(int), 0, len(edges) - 1)
    accumulator = np.zeros(len(edges), dtype=float)
    if statistic == "sum":
        np.add.at(accumulator, indices, ys)
    else:
        accumulator[:] = -np.inf
        np.maximum.at(accumulator, indices, ys)
        accumulator[~np.isfinite(accumulator)] = 0.0
    centers = edges + bin_width / 2.0
    return centers, accumulator


# --------------------------------------------------------------------------- #
# Spectral similarity
# --------------------------------------------------------------------------- #
def cosine_similarity(
    x_a: Any,
    y_a: Any,
    x_b: Any,
    y_b: Any,
    tolerance: float = 0.02,
    mz_power: float = 0.0,
    intensity_power: float = 0.5,
) -> float:
    """GNPS-style cosine score between two peak lists.

    Peaks are aligned within ``tolerance`` (in ``x`` units, e.g. Da for MS).
    """
    xa, ya = to_array(x_a), to_array(y_a)
    xb, yb = to_array(x_b), to_array(y_b)
    if xa.size == 0 or xb.size == 0:
        return 0.0

    ya = normalize(ya, "max")
    yb = normalize(yb, "max")
    wa = (np.maximum(xa, 1.0) ** mz_power) * (ya**intensity_power)
    wb = (np.maximum(xb, 1.0) ** mz_power) * (yb**intensity_power)

    order = np.argsort(xb)
    xb_sorted, wb_sorted = xb[order], wb[order]
    total = 0.0
    for x_value, weight in zip(xa, wa):
        low = np.searchsorted(xb_sorted, x_value - tolerance, side="left")
        high = np.searchsorted(xb_sorted, x_value + tolerance, side="right")
        if high > low:
            total += weight * float(np.max(wb_sorted[low:high]))
    denominator = math.sqrt(float(np.sum(wa**2)) * float(np.sum(wb**2)))
    return float(total / denominator) if denominator else 0.0


def match_peaks(
    query_peaks: Sequence[Peak],
    reference_peaks: Sequence[Peak],
    tolerance: float = 0.02,
) -> Dict[str, Any]:
    """Align two peak lists and report the matched features."""
    reference = list(reference_peaks or [])
    ref_x = np.array([p.x for p in reference], dtype=float)
    ref_y = np.array([p.y or p.intensity for p in reference], dtype=float)
    order = np.argsort(ref_x)
    ref_x, ref_y = ref_x[order], ref_y[order]

    matched: List[Dict[str, Any]] = []
    for peak in query_peaks or []:
        if ref_x.size == 0:
            break
        low = np.searchsorted(ref_x, peak.x - tolerance, side="left")
        high = np.searchsorted(ref_x, peak.x + tolerance, side="right")
        if high > low:
            best = int(np.argmax(ref_y[low:high])) + low
            matched.append(
                {
                    "query_mz": float(peak.x),
                    "query_intensity": float(peak.y or peak.intensity),
                    "reference_mz": float(ref_x[best]),
                    "reference_intensity": float(ref_y[best]),
                    "assignment": peak.assignment or reference[best].assignment,
                    "error": float(peak.x - ref_x[best]),
                }
            )
    total = max(1, len(query_peaks or []))
    return {
        "matched": matched,
        "matched_count": len(matched),
        "query_count": len(query_peaks or []),
        "reference_count": len(reference),
        "recall": len(matched) / total,
    }


# --------------------------------------------------------------------------- #
# Formulae, masses and isotope patterns
# --------------------------------------------------------------------------- #
class ElementDataError(ValueError):
    """Raised when a formula contains an unknown element."""


#: (exact mass, natural abundance) per isotope of the most common elements.
ISOTOPES: Dict[str, List[Tuple[float, float]]] = {
    "H": [(1.0078250319, 0.999885), (2.0141017778, 0.000115)],
    "He": [(4.0026032497, 0.99999866)],
    "Li": [(7.01600344, 0.9241), (6.01512230, 0.0759)],
    "Be": [(9.01218220, 1.0)],
    "B": [(11.00930550, 0.8010), (10.01293700, 0.1990)],
    "C": [(12.0, 0.9893), (13.0033548378, 0.0107)],
    "N": [(14.0030740052, 0.99632), (15.0001088984, 0.00368)],
    "O": [(15.9949146221, 0.99757), (16.99913150, 0.00038), (17.9991596, 0.00205)],
    "F": [(18.99840322, 1.0)],
    "Ne": [(19.99244018, 0.9048), (21.99138511, 0.0925), (20.99384668, 0.0027)],
    "Na": [(22.98976928, 1.0)],
    "Mg": [(23.98504190, 0.7899), (24.98583702, 0.1000), (25.98259304, 0.1101)],
    "Al": [(26.98153853, 1.0)],
    "Si": [(27.97692653, 0.92223), (28.97649470, 0.04685), (29.97377017, 0.03092)],
    "P": [(30.97376151, 1.0)],
    "S": [(31.97207069, 0.9499), (32.97145850, 0.0075), (33.96786683, 0.0425)],
    "Cl": [(34.96885271, 0.7576), (36.96590260, 0.2424)],
    "Ar": [(39.96238312, 0.996)],
    "K": [(38.96370649, 0.932581), (40.96182597, 0.067302)],
    "Ca": [(39.96259120, 0.96941), (41.95861826, 0.00647), (43.95548156, 0.02086)],
    "Sc": [(44.95590828, 1.0)],
    "Ti": [(47.94794698, 0.7372), (49.94479122, 0.0541)],
    "V": [(50.94395704, 0.9975)],
    "Cr": [(51.94050980, 0.8345)],
    "Mn": [(54.93804710, 1.0)],
    "Fe": [(55.93493930, 0.91754), (56.93539580, 0.02119), (57.93327730, 0.00282)],
    "Co": [(58.93319760, 1.0)],
    "Ni": [(57.93534620, 0.68077), (59.93078840, 0.26223), (61.92834610, 0.011399)],
    "Cu": [(62.92959890, 0.6915), (64.92779290, 0.3085)],
    "Zn": [(63.92914480, 0.4863), (65.92603470, 0.2790), (67.92484590, 0.1875)],
    "Ga": [(68.92557360, 0.6011), (70.92470130, 0.3989)],
    "Ge": [(73.92117780, 0.3654), (71.92207580, 0.2745), (69.92424740, 0.2057)],
    "As": [(74.92159420, 1.0)],
    "Se": [(79.91652180, 0.4961), (77.91730910, 0.0763)],
    "Br": [(78.91833760, 0.5069), (80.91629060, 0.4931)],
    "Kr": [(83.91149773, 0.5699), (85.91061073, 0.1728)],
    "Rb": [(84.91178974, 0.7217), (86.90918053, 0.2783)],
    "Sr": [(87.90561250, 0.8258), (85.90926060, 0.0956)],
    "Y": [(88.90584030, 1.0)],
    "Zr": [(89.90469770, 0.5152), (91.90503180, 0.1715)],
    "Nb": [(92.90637300, 1.0)],
    "Mo": [(97.90540480, 0.2413), (95.90467612, 0.1584), (94.90583877, 0.1572)],
    "Ag": [(106.90509160, 0.5184), (108.90475530, 0.4816)],
    "Cd": [(113.90336120, 0.2873), (110.90418290, 0.1249)],
    "Sn": [(119.90220160, 0.3258), (117.90160660, 0.2422)],
    "Sb": [(120.90382540, 0.5721), (122.90422270, 0.4279)],
    "Te": [(129.90622270, 0.3174), (127.90446140, 0.1874)],
    "I": [(126.90447190, 1.0)],
    "Ba": [(137.90524130, 0.7165), (135.90457070, 0.0659)],
    "La": [(138.90634790, 0.99909)],
    "Ce": [(139.90543330, 0.8845)],
    "Pr": [(140.90764790, 1.0)],
    "Nd": [(141.90771900, 0.272)],
    "Sm": [(151.91972800, 0.2675)],
    "Eu": [(152.92122500, 0.5219)],
    "Gd": [(157.92410000, 0.2485)],
    "Tb": [(158.92534200, 1.0)],
    "Dy": [(163.92917100, 0.2826)],
    "Ho": [(164.93031900, 1.0)],
    "Er": [(165.93029000, 0.3383)],
    "Tm": [(168.93421200, 1.0)],
    "Yb": [(173.93885900, 0.3183)],
    "Lu": [(174.94076700, 0.97401)],
    "Hf": [(179.94655700, 0.351)],
    "Ta": [(180.94799200, 0.99988)],
    "W": [(183.95093090, 0.3064)],
    "Re": [(186.95574400, 0.3739)],
    "Os": [(191.96147900, 0.4094)],
    "Ir": [(192.96291700, 0.3722)],
    "Pt": [(194.96476600, 0.3383)],
    "Au": [(196.96655100, 1.0)],
    "Hg": [(201.97063250, 0.2986)],
    "Pb": [(207.97663650, 0.524)],
    "Bi": [(208.98038300, 1.0)],
    "Th": [(232.03805040, 1.0)],
    "U": [(238.05078260, 0.9927)],
}

#: Standard atomic weights (IUPAC 2021 four significant figures).
ATOMIC_WEIGHTS: Dict[str, float] = {
    "H": 1.008, "He": 4.0026, "Li": 6.94, "Be": 9.0122, "B": 10.81,
    "C": 12.011, "N": 14.007, "O": 15.999, "F": 18.998, "Ne": 20.180,
    "Na": 22.990, "Mg": 24.305, "Al": 26.982, "Si": 28.085, "P": 30.974,
    "S": 32.06, "Cl": 35.45, "Ar": 39.95, "K": 39.098, "Ca": 40.078,
    "Sc": 44.956, "Ti": 47.867, "V": 50.942, "Cr": 51.996, "Mn": 54.938,
    "Fe": 55.845, "Co": 58.933, "Ni": 58.693, "Cu": 63.546, "Zn": 65.38,
    "Ga": 69.723, "Ge": 72.630, "As": 74.922, "Se": 78.971, "Br": 79.904,
    "Kr": 83.798, "Rb": 85.468, "Sr": 87.62, "Y": 88.906, "Zr": 91.224,
    "Nb": 92.906, "Mo": 95.95, "Tc": 97.0, "Ru": 101.07, "Rh": 102.91,
    "Pd": 106.42, "Ag": 107.87, "Cd": 112.41, "In": 114.82, "Sn": 118.71,
    "Sb": 121.76, "Te": 127.60, "I": 126.90, "Xe": 131.29, "Cs": 132.91,
    "Ba": 137.33, "La": 138.91, "Ce": 140.12, "Pr": 140.91, "Nd": 144.24,
    "Pm": 145.0, "Sm": 150.36, "Eu": 151.96, "Gd": 157.25, "Tb": 158.93,
    "Dy": 162.50, "Ho": 164.93, "Er": 167.26, "Tm": 168.93, "Yb": 173.05,
    "Lu": 174.97, "Hf": 178.49, "Ta": 180.95, "W": 183.84, "Re": 186.21,
    "Os": 190.23, "Ir": 192.22, "Pt": 195.08, "Au": 196.97, "Hg": 200.59,
    "Tl": 204.38, "Pb": 207.20, "Bi": 208.98, "Th": 232.04, "Pa": 231.04,
    "U": 238.03,
}

#: Element token: an element symbol optionally followed by a (fractional)
#: stoichiometry such as ``C``, ``C8`` or ``Ni0.8``.
_FORMULA_TOKEN = re.compile(r"([A-Z][a-z]?)(\d+(?:\.\d+)?)?")

#: Adduct definitions: ``name -> (mass of the attached ion, absolute charge)``.
ADDUCTS: Dict[str, Tuple[float, int]] = {
    "[M]+": (0.0, 1),
    "[M+H]+": (1.00727646, 1),
    "[M+Na]+": (22.989221, 1),
    "[M+K]+": (38.963158, 1),
    "[M+NH4]+": (18.033823, 1),
    "[M+H-H2O]+": (-17.002740, 1),
    "[M+2H]2+": (1.00727646, 2),
    "[M]-": (0.0, 1),
    "[M-H]-": (-1.00727646, 1),
    "[M+Cl]-": (34.969402, 1),
    "[M+FA-H]-": (44.998201, 1),
    "[M+Ac-H]-": (59.013851, 1),
    "[M-2H]2-": (-1.00727646, 2),
}


def parse_formula(formula: str) -> "Counter[str]":
    """Parse a Hill-ish formula such as ``C8H10N4O2`` into element counts.

    Fractional stoichiometries (``LiNi0.8Mn0.1Co0.1O2``) are supported, the
    counts are returned as ``float``.  A trailing charge decoration
    (``C8H10N4O2+``) is removed before parsing.
    """
    text = str(formula or "").strip()
    if not text:
        return Counter()
    # Strip charge decorations such as "2+" / "-" at the end of the formula.
    text = re.sub(r"[\+\-]\d*$", "", text).strip()
    counts: Counter[str] = Counter()
    position = 0
    while position < len(text):
        match = _FORMULA_TOKEN.match(text, position)
        if match is None:
            raise ElementDataError(f"Cannot parse formula {formula!r}")
        element, number = match.group(1), match.group(2)
        if element not in ISOTOPES:
            raise ElementDataError(f"Unknown element {element!r} in {formula!r}")
        counts[element] += float(number) if number else 1.0
        position = match.end()
    return counts


def formula_mass(formula: str, isotope: str = "monoisotopic") -> float:
    """Exact (monoisotopic) or average mass of a molecular formula."""
    counts = parse_formula(formula)
    if isotope == "average":
        return float(sum(ATOMIC_WEIGHTS[el] * n for el, n in counts.items()))
    return float(
        sum(ISOTOPES[el][0][0] * n for el, n in counts.items())
    )


def isotope_pattern(
    formula: str, charge: int = 1, adduct: str = "[M+H]+", threshold: float = 1e-4
) -> List[Tuple[float, float]]:
    """Compute the isotope envelope of ``formula``.

    Returns a list of ``(m/z, relative abundance)`` sorted by m/z; the most
    intense peak is scaled to 1.0.
    """
    counts = parse_formula(formula)
    distribution: Dict[int, float] = {0: 1.0}

    for element, number in counts.items():
        isotopes = ISOTOPES[element]
        for _ in range(int(number)):
            updated: Dict[int, float] = {}
            for nominal, probability in distribution.items():
                for index, (isotope_mass, abundance) in enumerate(isotopes):
                    if abundance <= 0:
                        continue
                    key = nominal + index
                    updated[key] = updated.get(key, 0.0) + probability * abundance
            distribution = {
                key: value
                for key, value in updated.items()
                if value >= threshold
            }

    # Convert nominal neutron excess into exact masses.
    base_mass = formula_mass(formula)
    pattern: List[Tuple[float, float]] = []
    for nominal, abundance in sorted(distribution.items()):
        # Exact mass of the isotopologue: base + nominal neutron excess.
        # 1 neutron excess ~ 1.00335 Da; the error stays below 5 mDa for the
        # first three peaks of typical small molecules.
        exact = base_mass + nominal * 1.0033548378
        ion_mass, abs_charge = ADDUCTS.get(adduct, ADDUCTS["[M+H]+"])
        mz = (exact + abs_charge * ion_mass) / max(1, abs(charge))
        pattern.append((float(mz), float(abundance)))

    peak_abundance = max((value for _, value in pattern), default=1.0)
    if peak_abundance > 0:
        pattern = [(mz, value / peak_abundance) for mz, value in pattern]
    pattern = [item for item in pattern if item[1] >= threshold]
    return pattern


def neutral_mass(mz: float, adduct: str = "[M+H]+") -> float:
    """Neutral monoisotopic mass of an ion observed at ``mz``."""
    ion_mass, abs_charge = ADDUCTS.get(adduct, ADDUCTS["[M+H]+"])
    return float(mz - ion_mass) * abs_charge


def adduct_mz(neutral: float, adduct: str = "[M+H]+") -> float:
    """m/z of ``neutral`` for the requested adduct."""
    ion_mass, abs_charge = ADDUCTS.get(adduct, ADDUCTS["[M+H]+"])
    return float(neutral + abs_charge * ion_mass) / abs_charge


def mass_error(observed: float, theoretical: float, unit: str = "ppm") -> float:
    """Mass error between an observed and a theoretical value."""
    if theoretical == 0:
        return float("nan")
    difference = observed - theoretical
    if unit.lower() == "ppm":
        return difference / theoretical * 1e6
    return difference

"""Fragmentation pathway deduction for MS/MS spectra (v0.7.2).

What this module answers
------------------------
Given a **measured** mass spectrum (and, when available, the candidate
structure the identification step proposed), *which fragmentation pathway is
consistent with the observed peaks?*

This is deliberately **not** a black box.  The deduction is a transparent,
deterministic, rule-based search:

1. **Candidate generation.**  Starting from the precursor ion, every cleavage
   the structure permits is enumerated (see :data:`CLEAVAGE_RULES`): bond
   cleavages that are energetically favoured in positive-mode CID (benzylic,
   allylic, alpha-to-heteroatom, acyl) plus the classic neutral losses
   (``H2O``, ``CO``, ``CO2``, ``NH3`` ...).  For a structure-less measurement
   the search degrades honestly to :func:`deduce_without_structure`, which only
   reports *neutral-loss differences between observed peaks* -- no invented
   chemistry.

2. **Matching.**  Each theoretical fragment m/z is matched against the observed
   peaks within a mass tolerance (ppm), and scored by relative intensity,
   elemental plausibility and the rule's prior probability.

3. **Ranking.**  Pathways are ranked by the product of step scores, and the
   best one is returned with the full step list so the GUI (and any report) can
   show *why* each fragment was proposed.

Honesty rules (the platform's iron law)
---------------------------------------
* Every answer records ``engine``.  A rules-only deduction is
  ``internal:fragmentation-rules``; a narrative written by a real model is
  ``external:<provider>``.  The two are never conflated.
* The AI narrative is **optional** and **additive**: when no LLM is reachable
  the pathway itself is still returned, with an honest note saying the
  interpretation came from the built-in engine.
* Nothing here fabricates a structure.  Without a molecule the output says so.

Scoring is deterministic (no RNG), so a re-run reproduces the pathway exactly.
"""

from __future__ import annotations

import math
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from workflow_engine.processing import adduct_mz, formula_mass, isotope_pattern, neutral_mass

__all__ = [
    "CLEAVAGE_RULES",
    "NEUTRAL_LOSSES",
    "FragmentStep",
    "PathwayResult",
    "deduce_pathway",
    "deduce_without_structure",
    "DEFAULT_TOLERANCE_PPM",
]

#: Mass matching tolerance used when the caller does not supply one.
DEFAULT_TOLERANCE_PPM = 20.0

#: Classic positive-mode neutral losses: (label, exact mass, prior weight).
NEUTRAL_LOSSES: Tuple[Tuple[str, float, float], ...] = (
    ("H2O", 18.010565, 0.92),
    ("CO", 27.994915, 0.70),
    ("NH3", 17.026549, 0.62),
    ("CO2", 43.989830, 0.58),
    ("CH3", 15.023475, 0.45),
    ("HCN", 27.010899, 0.40),
    ("C2H4", 28.031300, 0.34),
    ("CH2O", 30.010565, 0.30),
    ("NO2", 45.993430, 0.22),
    ("CH3OH", 32.026215, 0.24),
    ("C3H6", 42.046950, 0.20),
    # Fused-ring systems (purines, xanthines, steroids) cannot be split by a
    # *single* bond cut at all -- every bond in a fused ring system still leaves
    # the ring system connected through the other ring.  Their characteristic
    # products therefore arrive as combinations of neutral losses, so those
    # combos have to be in the library or the structural enumeration (correctly,
    # but uselessly) returns nothing for them.
    ("CH3NCO", 57.021464, 0.34),
    ("C2H3NO", 57.021464, 0.26),  # isobaric alternative of CH3NCO
    ("C2H3NO2", 73.029005, 0.22),
    ("C3H6O", 58.041865, 0.22),
    ("C4H6O", 70.041865, 0.18),
)

#: Each further step of a neutral-loss ladder is less likely than the first, so
#: the prior decays instead of multiplying (which would let deep ladders -- the
#: most combinatorially numerous -- dominate the ranking).
NEUTRAL_LOSS_DEPTH_DECAY = 0.55

#: Bond cleavages a CID experiment actually makes, with a prior probability.
#: ``(label, prior, rationale)`` -- the rationale is shown in the GUI so the
#: user can judge the proposal instead of trusting a number.
#:
#: .. note::
#:    This table documents the *chemistry the search knows about*.  The priors
#:    actually applied live in :func:`_cleavage_prior`, which decides per bond
#:    from the graph (aromatic? alpha to a heteroatom? on a ring?) and returns
#:    the exact fragment formula.  Keep the two in sync when adding a channel.
CLEAVAGE_RULES: Tuple[Tuple[str, float, str], ...] = (
    ("benzylic C–C", 0.78, "苄位 C–C 键：苄基自由基共振稳定，CID 首选裂解位点"),
    ("α-羰基 C–C", 0.74, "羰基 α 位：生成的烯醇正离子由共振稳定"),
    ("acyl cleavage", 0.70, "酰基 C–N / C–O：生成稳定的酰离子 R–C≡O⁺"),
    ("α-heteroatom C–C", 0.60, "杂原子 α 位：N/O/S 邻位碳正离子由孤对电子稳定"),
    ("ring C–C", 0.55, "环内 C–C：环开裂，常伴随中性丢失"),
    ("aromatic C–C", 0.34, "芳香环内 C–C：需要较高能量"),
    ("C–C", 0.34, "普通 C–C：缺少共振稳定，优先级低"),
    ("terminal C–C", 0.42, "末端 C–C：生成 CH₃•⁺ / CH₃⁺ 碎片"),
)


# --------------------------------------------------------------------------- #
# Result containers
# --------------------------------------------------------------------------- #
class FragmentStep(dict):
    """One step of a fragmentation pathway.

    A plain ``dict`` subclass so the result serialises straight to JSON for the
    REST layer and the run artefact without a converter.
    """

    @property
    def step(self) -> int:
        return int(self.get("step", 0))

    @property
    def confidence(self) -> float:
        return float(self.get("confidence", 0.0))


class PathwayResult(dict):
    """A ranked pathway plus the evidence behind it."""

    @property
    def confidence(self) -> float:
        return float(self.get("confidence", 0.0))

    @property
    def steps(self) -> List[FragmentStep]:
        return list(self.get("steps", []))


# --------------------------------------------------------------------------- #
# Peak helpers
# --------------------------------------------------------------------------- #
def _observed_peaks(
    spectrum: Any, limit: int = 400
) -> List[Tuple[float, float]]:
    """``[(mz, relative_intensity 0..1), ...]`` sorted by decreasing intensity."""
    peaks = getattr(spectrum, "peaks", None)
    rows: List[Tuple[float, float]] = []

    if peaks:
        for peak in peaks:
            try:
                mz = float(getattr(peak, "x", peak))
                intensity = float(getattr(peak, "y", 0.0) or 0.0)
            except (TypeError, ValueError):
                continue
            if mz > 0 and math.isfinite(mz):
                rows.append((mz, intensity))
    else:
        # A spectrum without a peak list (e.g. freshly parsed profile data):
        # fall back to local maxima of the trace so the engine still works.
        xs = list(getattr(spectrum, "x", []) or [])
        ys = list(getattr(spectrum, "y", []) or [])
        for index in range(1, len(ys) - 1):
            window = ys[max(0, index - 6) : index + 7]
            if ys[index] >= max(window, default=0.0) and ys[index] > 0:
                rows.append((float(xs[index]), float(ys[index])))

    if not rows:
        return []

    base = max(value for _, value in rows) or 1.0
    normalised = [(mz, value / base) for mz, value in rows]
    normalised.sort(key=lambda item: -item[1])
    return normalised[:limit]


def _match(
    peaks: Sequence[Tuple[float, float]], theoretical: float, tolerance_ppm: float
) -> Optional[Tuple[float, float, float]]:
    """Best observed peak for ``theoretical``.

    Returns ``(observed_mz, relative_intensity, ppm_error)`` or ``None``.
    """
    best: Optional[Tuple[float, float, float]] = None
    best_error = float("inf")
    for mz, relative in peaks:
        if theoretical <= 0:
            continue
        error = abs(mz - theoretical) / theoretical * 1e6
        if error > tolerance_ppm:
            continue
        # Prefer the closest match; break ties on the stronger peak.
        if error < best_error or (error == best_error and best and relative > best[1]):
            best = (mz, relative, error)
            best_error = error
    return best


def _step_score(prior: float, relative: float, ppm_error: float, tolerance_ppm: float) -> float:
    """Combine prior, intensity and mass accuracy into ``0..1`` confidence."""
    accuracy = max(0.0, 1.0 - (ppm_error / max(tolerance_ppm, 1e-6)))
    # Relative intensity contributes on a square-root scale: a 4 % peak is weak
    # evidence, a 40 % peak is strong, but the difference must not dominate.
    intensity_term = math.sqrt(max(0.0, min(1.0, relative)))
    return max(0.0, min(1.0, prior * (0.35 + 0.45 * accuracy + 0.20 * intensity_term)))


# --------------------------------------------------------------------------- #
# Candidate generation
# --------------------------------------------------------------------------- #
def _neutral_loss_candidates(
    precursor_mz: float, *, max_depth: int = 1, floor_mz: float = 0.0
) -> List[Tuple[float, str, float, str]]:
    """``[(fragment_mz, label, prior, rationale), ...]`` for neutral losses.

    With ``max_depth > 1`` this walks **neutral-loss ladders** rather than a
    single fan of parallel losses, which is what a real CID pathway is: a
    precursor loses H2O, the product ion loses CO, and so on.  Each further
    step multiplies the prior by :data:`NEUTRAL_LOSS_DEPTH_DECAY` because every
    extra cleavage is another step that can be wrong (and is worth less than
    the first), while the label spells out the whole ladder so the report is
    readable (``-H2O > -CO``).
    """
    candidates: List[Tuple[float, str, float, str]] = []
    depth_limit = max(1, int(max_depth))

    def walk(current: float, label: str, prior: float, chain: List[str], depth: int) -> None:
        for entry_label, loss, loss_prior in NEUTRAL_LOSSES:
            fragment = current - loss
            if fragment <= floor_mz:
                continue
            step_prior = prior * loss_prior * (NEUTRAL_LOSS_DEPTH_DECAY ** depth)
            step_label = f"{label}-{entry_label}" if label else f"-{entry_label}"
            step_chain = chain + [f"{entry_label}（{loss:.4f} Da）"]
            candidates.append(
                (
                    fragment,
                    step_label,
                    step_prior,
                    "中性丢失阶梯 " + " → ".join(step_chain),
                )
            )
            if depth + 1 < depth_limit:
                walk(fragment, step_label, loss_prior, step_chain, depth + 1)

    walk(precursor_mz, "", 1.0, [], 0)
    return candidates


def _structural_candidates(
    graph: Any, precursor_mz: float, adduct: str
) -> List[Tuple[float, str, float, str, str]]:
    """Cleavage candidates derived by actually cutting the molecular graph.

    Every single bond of the structure is broken in turn, the two resulting
    sub-structures are re-formed into molecular formulas, and their *exact*
    monoisotopic masses are turned into theoretical fragment m/z values.  A
    bond is only proposed when the chemistry supports it (see
    :func:`_cleavage_prior`), and each candidate carries the fragment formula
    it came from -- so nothing in the output is a guessed constant.

    Returns ``[(fragment_mz, label, prior, rationale, formula), ...]``.
    """
    candidates: List[Tuple[float, str, float, str, str]] = []
    try:
        atoms = list(graph.atoms)
        bonds = list(graph.bonds)
    except Exception:  # noqa: BLE001 - a defensive fallback, never a crash path
        return candidates
    if not atoms or not bonds:
        return candidates

    ring_atoms = set()
    aromatic_atoms = set()
    try:
        ring_atoms = set(graph.ring_atoms())
        aromatic_atoms = {
            atom["index"] for atom in atoms if atom.get("aromatic")
        }
    except Exception:  # noqa: BLE001
        pass

    adjacency = graph.adjacency()
    # Elements that can stabilise an adjacent carbocation by lone-pair donation.
    heteroatoms = {"N", "O", "S"}

    for bond in bonds:
        first, second = int(bond["a"]), int(bond["b"])
        prior, rationale, label = _cleavage_prior(
            graph, first, second, ring_atoms, aromatic_atoms, adjacency, heteroatoms
        )
        if prior <= 0.0:
            continue

        # Cut the bond and decide which side is *the* fragment ion.  Both sides
        # of a single bond cleavage are complementary fragments, but only one of
        # them is the surviving ion: the other leaves as a neutral radical.  The
        # surviving ion is the one that keeps the molecular scaffold, so the
        # scaffold side is always reported and the sliver is not.  Reporting
        # both is how naive calculators end up claiming that benzylic cleavage of
        # DHB produces "CH2O2" at m/z 46.
        sizes: List[Tuple[List[Dict[str, Any]], str, float]] = []
        for keep, drop in ((first, second), (second, first)):
            fragment_atoms = _component_without(atoms, bonds, keep, drop)
            if not fragment_atoms or len(fragment_atoms) >= len(atoms):
                continue
            formula = _formula_of(fragment_atoms)
            if not formula or not _is_reportable_fragment(formula):
                continue
            try:
                neutral = formula_mass(formula)
            except Exception:  # noqa: BLE001 - unknown element -> skip silently
                continue
            sizes.append((fragment_atoms, formula, neutral))

        if not sizes:
            continue
        # The scaffold side is the larger one; a symmetric cut (both sides equal)
        # is reported once, which the caller's m/z de-duplication would do anyway.
        _, formula, neutral = max(sizes, key=lambda item: len(item[0]))
        kept_atoms = max(len(item[0]) for item in sizes)

        # No extra proton is added here: :func:`_formula_of` already gives the
        # *ion* formula (the cut atom gains the hydrogen that carries the
        # charge).  Adding :data:`_PROTON_MASS` on top would double count it and
        # push every structural fragment 1 Da too high.
        fragment_mz = neutral
        if fragment_mz <= 0 or fragment_mz >= precursor_mz - 1.0:
            continue
        candidates.append(
            (
                fragment_mz,
                label,
                _size_adjusted_prior(prior, kept_atoms, len(atoms)),
                rationale,
                formula,
            )
        )
    return candidates


#: Mass of a proton (the charge carrier for every ``[M+H]+`` precursor).
_PROTON_MASS = 1.00727645

#: A cut that leaves fewer heavy atoms than this is not a *fragment ion* a
#: spectroscopist would report -- breaking an O-H bond yields "HO", which is a
#: neutral radical, not a peak.  Reporting it would be padding the pathway with
#: noise, so such cuts are dropped before they ever reach the matcher.
MIN_FRAGMENT_HEAVY_ATOMS = 3

#: How much of the molecule a fragment must retain before it is considered a
#: plausible fragment ion rather than a sliver.  Because only the scaffold side
#: of a cleavage is reported (see :func:`_structural_candidates`), a reported
#: fragment always keeps at least half of the heavy atoms, so this threshold
#: exists purely as a guard: if a future change ever reports the smaller half,
#: this is what catches it before it reaches the matcher.
MIN_FRAGMENT_MASS_FRACTION = 0.5


def _size_adjusted_prior(prior: float, fragment_atoms: int, total_atoms: int) -> float:
    """Scale a cleavage ``prior`` by how much of the molecule the fragment keeps.

    The chemistry prior answers "is this a sensible bond to break?".  It says
    nothing about "does the surviving piece deserve its own peak?", and without
    this correction a cut that strands a tiny fragment is scored exactly like
    one that yields the main product.  Slivers are discounted linearly towards
    a quarter of the prior as their share of the molecule vanishes.
    """
    if total_atoms <= 0:
        return prior
    fraction = fragment_atoms / total_atoms
    if fraction >= MIN_FRAGMENT_MASS_FRACTION:
        return prior
    scaled = max(0.0, min(1.0, fraction / MIN_FRAGMENT_MASS_FRACTION))
    return prior * (0.25 + 0.75 * scaled)


def _cleavage_prior(
    graph: Any,
    first: int,
    second: int,
    ring_atoms: set,
    aromatic_atoms: set,
    adjacency: Dict[int, List[Tuple[int, float]]],
    heteroatoms: set,
) -> Tuple[float, str, str]:
    """Is this bond a plausible CID cleavage site?  ``(prior, rationale, label)``.

    ``prior <= 0`` means "not proposed at all".  The ordering of the tests is
    the ordering of the chemistry: a benzylic position stabilises the incipient
    cation better than an allylic one, which beats alpha-to-heteroatom.
    """
    element_first = str(graph.atoms[first].get("element", ""))
    element_second = str(graph.atoms[second].get("element", ""))
    carbons = [i for i in (first, second) if graph.atoms[i].get("element") == "C"]
    if not carbons:
        # Heteroatom-heteroatom bonds are not typical CID sites.
        return 0.0, "", ""
    carbon = carbons[0]
    other = first if carbon == second else second

    neighbours = adjacency.get(carbon, [])
    # A carbon with no heavy neighbours left after the cut is a terminal methyl;
    # losing it (radical cation CH3) is a real but weak channel.
    if len(neighbours) <= 1:
        return 0.42, "末端 C–C 断裂：生成稳定的 CH3•+ 或 CH3+ 碎片", "terminal C–C"

    if carbon in aromatic_atoms:
        # Breaking the bond *out of* an aromatic ring opens the ring system.
        if other in aromatic_atoms:
            return (
                0.34,
                "芳香环内 C–C 断裂：需要较高能量，生成稳定芳香碎片",
                "aromatic C–C",
            )
        return (
            0.78,
            "苄位 C–C 断裂：苄基正离子由芳环共振稳定，是 CID 的首选裂解位点",
            "benzylic C–C",
        )

    if carbon in ring_atoms and other in ring_atoms:
        return 0.55, "环内 C–C 断裂：环开裂，常伴随中性丢失", "ring C–C"

    if any(graph.atoms[i].get("element") in heteroatoms for i, _ in neighbours):
        return (
            0.60,
            "杂原子 α 位 C–C 断裂：生成的碳正离子由 N/O/S 孤对电子共振稳定",
            "α-heteroatom C–C",
        )

    if any(abs(float(order) - 2.0) < 1e-6 for _, order in neighbours):
        return (
            0.74,
            "α-羰基 C–C 断裂：烯醇正离子由羰基共振稳定",
            "α-carbonyl C–C",
        )

    if any(abs(float(order) - 2.0) < 1e-6 for _, order in adjacency.get(other, [])):
        return (
            0.70,
            "酰基 C–N / C–O 断裂：生成稳定的酰离子 R–C≡O+",
            "acyl cleavage",
        )

    del element_first, element_second
    return 0.34, "普通 C–C 断裂：缺少共振稳定，优先级低", "C–C"


def _is_reportable_fragment(formula: str) -> bool:
    """Does ``formula`` describe something a mass spectrum would actually show?

    Two conditions, both about honesty rather than chemistry: it must contain
    carbon (an organic fragment ion), and it must have enough heavy atoms to be
    a real fragment rather than a stray radical.
    """
    from workflow_engine.processing import parse_formula

    try:
        counts = parse_formula(formula)
    except Exception:  # noqa: BLE001 - an unparsable formula is simply not reportable
        return False
    if int(counts.get("C", 0)) < 1:
        return False
    heavy = sum(int(value) for element, value in counts.items() if element != "H")
    return heavy >= MIN_FRAGMENT_HEAVY_ATOMS


def _component_without(
    atoms: List[Dict[str, Any]], bonds: List[Dict[str, Any]], keep: int, drop: int
) -> List[Dict[str, Any]]:
    """Atoms reachable from ``keep`` once the ``keep``–``drop`` bond is cut."""
    adjacency: Dict[int, List[int]] = {atom["index"]: [] for atom in atoms}
    for bond in bonds:
        a, b = int(bond["a"]), int(bond["b"])
        if (a == keep and b == drop) or (a == drop and b == keep):
            continue
        adjacency[a].append(b)
        adjacency[b].append(a)

    seen = {keep}
    queue = [keep]
    while queue:
        current = queue.pop()
        for neighbour in adjacency.get(current, []):
            if neighbour not in seen:
                seen.add(neighbour)
                queue.append(neighbour)
    return [atom for atom in atoms if atom["index"] in seen]


def _formula_of(atoms: List[Dict[str, Any]]) -> str:
    """Hill-notation formula of a sub-structure, **adding back** the hydrogen
    lost at the cleavage site.

    The SMILES parser stores *implicit* hydrogens per heavy atom for the intact
    molecule.  When a bond is broken, the atom on each side gains one hydrogen,
    so a sub-structure's formula is its heavy atoms plus the stored hydrogens
    plus one H for the new valence.  Getting this wrong is exactly how naive
    fragment calculators end up off by 1 Da, so it is done explicitly.
    """
    from collections import Counter

    counts: Counter = Counter()
    for atom in atoms:
        element = str(atom.get("element", ""))
        if not element:
            return ""
        counts[element] += 1
        hydrogens = int(atom.get("hydrogens", 0) or 0)
        if hydrogens:
            counts["H"] += hydrogens
    counts["H"] += 1  # the hydrogen gained at the cleavage site
    if counts.get("H", 0) <= 0:
        counts.pop("H", None)

    ordered: List[Tuple[str, int]] = []
    if "C" in counts:
        ordered.append(("C", counts.pop("C")))
        if "H" in counts:
            ordered.append(("H", counts.pop("H")))
    ordered.extend(sorted(counts.items()))
    return "".join(
        f"{element}{number if number > 1 else ''}" for element, number in ordered
    )


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #
def deduce_pathway(
    spectrum: Any,
    smiles: str = "",
    *,
    adduct: str = "[M+H]+",
    tolerance_ppm: float = DEFAULT_TOLERANCE_PPM,
    max_steps: int = 8,
    min_relative: float = 0.01,
    max_depth: int = 2,
) -> PathwayResult:
    """Deduce the fragmentation pathway of ``spectrum``.

    ``smiles`` is optional.  With a structure the search proposes structure-
    sensible cleavages; without one it falls back to
    :func:`deduce_without_structure`, which only reports neutral-loss
    differences between the observed peaks.

    ``max_depth`` bounds how far a neutral-loss ladder may be followed: ``1``
    proposes only parallel single losses from the precursor, ``2`` (default)
    also follows two-step ladders such as ``-H2O > -CO``, which is what a real
    CID pathway looks like.  Deeper ladders are combinatorial and rarely
    supported by evidence, so the default stops at two.
    """
    tolerance = max(0.5, float(tolerance_ppm or DEFAULT_TOLERANCE_PPM))
    limit = max(1, int(max_steps or 8))
    floor = max(0.0, float(min_relative or 0.0))
    depth = max(1, int(max_depth or 1))

    peaks = _observed_peaks(spectrum)
    if not peaks:
        return PathwayResult(
            {
                "ok": False,
                "reason": "no usable peaks in the spectrum",
                "engine": "internal:fragmentation-rules",
                "steps": [],
                "confidence": 0.0,
                "precursor_mz": None,
                "structure_known": bool(smiles),
                "smiles": smiles or "",
                "observed_peaks": 0,
            }
        )

    precursor_mz = float(getattr(spectrum, "precursor_mz", 0.0) or 0.0)
    metadata = getattr(spectrum, "metadata", {}) or {}
    if not precursor_mz:
        precursor_mz = float(metadata.get("precursor_mz", 0.0) or 0.0)

    graph = None
    formula = ""
    if smiles:
        try:
            from models.smiles import parse_smiles

            graph = parse_smiles(smiles)
            formula = graph.formula_string()
        except Exception:  # noqa: BLE001 - an unparsable SMILES must not crash
            graph = None

    precursor_neutral = neutral_mass(precursor_mz, adduct) if precursor_mz else 0.0
    if graph is not None and precursor_neutral <= 0:
        try:
            precursor_neutral = formula_mass(formula)
        except Exception:  # noqa: BLE001
            precursor_neutral = 0.0

    # Where does the precursor come from?  In order of trustworthiness:
    #  1. the measurement declared one (MS/MS precursor isolation);
    #  2. the structure is known -> its theoretical [M]+ / [M+H]+ ...;
    #  3. nothing else: fall back to the base peak and *say so*, because a
    #     MALDI 1-MS scan of a mixture very often has its strongest ion in the
    #     matrix, not in the analyte.
    precursor_source = "declared"
    if not precursor_mz and precursor_neutral > 0:
        precursor_mz = adduct_mz(precursor_neutral, adduct)
        precursor_source = "structure"
    if not precursor_mz and peaks:
        precursor_mz = peaks[0][0]
        precursor_source = "base-peak (no declared or computed precursor)"

    candidates: List[Tuple[float, str, float, str, str]] = []
    candidates.extend(
        (mz, label, prior, rationale, "") for mz, label, prior, rationale
        in _neutral_loss_candidates(precursor_mz, max_depth=depth)
    )
    if graph is not None:
        candidates.extend(_structural_candidates(graph, precursor_mz, adduct))

    # The de-adducted neutral molecule ion is a real peak in its own right, but
    # it is **not a fragmentation step**: no bond was broken to get there, so it
    # must not compete with genuine fragments for a step slot (or for the
    # confidence).  It is recorded separately as an observation.
    de_adducted: Dict[str, Any] | None = None
    if precursor_neutral > 0 and precursor_neutral < precursor_mz:
        hit = _match(peaks, precursor_neutral, tolerance)
        if hit is not None:
            observed, relative, error = hit
            de_adducted = {
                "rule": "M (de-adducted)",
                "theoretical_mz": round(precursor_neutral, 4),
                "observed_mz": round(observed, 4),
                "mass_error_ppm": round(error, 2),
                "relative_intensity": round(relative, 4),
                "rationale": (
                    "加合离子丢失中性伙伴后得到的去加合中性分子离子；"
                    "它未断开任何化学键，因此不计入裂解步骤。"
                ),
            }

    steps: List[FragmentStep] = []
    step_number = 0
    seen_mz: set = set()
    for theoretical, label, prior, rationale, fragment_formula in candidates:
        if len(steps) >= limit:
            break
        if round(theoretical, 3) in seen_mz:
            continue
        hit = _match(peaks, theoretical, tolerance)
        if hit is None:
            continue
        observed, relative, error = hit
        if relative < floor:
            continue
        step_number += 1
        seen_mz.add(round(theoretical, 3))
        steps.append(
            FragmentStep(
                {
                    "step": step_number,
                    "rule": label,
                    "rationale": rationale,
                    "fragment_formula": fragment_formula,
                    "theoretical_mz": round(theoretical, 4),
                    "observed_mz": round(observed, 4),
                    "loss_da": round(precursor_mz - observed, 4),
                    "relative_intensity": round(relative, 4),
                    "mass_error_ppm": round(error, 2),
                    "confidence": round(_step_score(prior, relative, error, tolerance), 4),
                }
            )
        )

    steps.sort(key=lambda item: (-float(item["confidence"]), float(item["theoretical_mz"])))
    for index, entry in enumerate(steps, start=1):
        entry["step"] = index

    confidence = 0.0
    if steps:
        # A pathway is only as trustworthy as its weakest meaningful link, so
        # the mean is damped by the minimum (no averaging away a bad step).
        scores = [float(entry["confidence"]) for entry in steps]
        confidence = round(
            (sum(scores) / len(scores)) * 0.6 + min(scores) * 0.4, 4
        )

    return PathwayResult(
        {
            "ok": bool(steps),
            "reason": "" if steps else "no theoretical fragment matched an observed peak",
            "engine": "internal:fragmentation-rules",
            "steps": steps,
            "confidence": confidence,
            "precursor_mz": round(precursor_mz, 4),
            "precursor_source": precursor_source,
            "precursor_neutral": round(precursor_neutral, 4) if precursor_neutral else None,
            "adduct": adduct,
            "formula": formula,
            "structure_known": graph is not None,
            "smiles": smiles or "",
            "tolerance_ppm": tolerance,
            "observed_peaks": len(peaks),
            "matched_peaks": len(steps),
            "de_adducted": de_adducted,
        }
    )


def deduce_without_structure(
    spectrum: Any,
    *,
    tolerance_da: float = 0.02,
    max_steps: int = 8,
    min_relative: float = 0.01,
) -> PathwayResult:
    """Structure-free deduction: neutral losses **between observed peaks**.

    This is what can honestly be said about a single MALDI/1-MS scan of an
    unknown: peak *differences* that match a known neutral loss.  It asserts no
    structure and no bond order.
    """
    peaks = _observed_peaks(spectrum)
    precursor = float(getattr(spectrum, "precursor_mz", 0.0) or 0.0) or (
        peaks[0][0] if peaks else 0.0
    )
    if not peaks:
        return PathwayResult(
            {
                "ok": False,
                "reason": "no usable peaks in the spectrum",
                "engine": "internal:fragmentation-rules",
                "steps": [],
                "confidence": 0.0,
                "precursor_mz": precursor or None,
                "structure_known": False,
                "observed_peaks": 0,
            }
        )

    steps: List[FragmentStep] = []
    limit = max(1, int(max_steps or 8))
    floor = max(0.0, float(min_relative or 0.0))

    for mz, relative in peaks:
        if len(steps) >= limit:
            break
        if relative < floor:
            continue
        difference = precursor - mz
        if difference <= 0:
            continue
        best: Optional[Tuple[str, float, float]] = None
        for label, loss, prior in NEUTRAL_LOSSES:
            error = abs(difference - loss)
            if error <= tolerance_da and (best is None or error < best[2]):
                best = (label, loss, error)
        if best is None:
            continue
        label, loss, error = best
        steps.append(
            FragmentStep(
                {
                    "rule": f"-{label}",
                    "rationale": f"与最高强度离子相差 {difference:.4f} Da，匹配中性丢失 {label}",
                    "theoretical_mz": round(precursor - loss, 4),
                    "observed_mz": round(mz, 4),
                    "loss_da": round(difference, 4),
                    "relative_intensity": round(relative, 4),
                    "mass_error_ppm": round(error / max(loss, 1e-9) * 1e6, 2),
                    "confidence": round(
                        _step_score(0.55, relative, 0.0, max(tolerance_da, loss) / loss * 1e6),
                        4,
                    ),
                }
            )
        )

    for index, entry in enumerate(steps, start=1):
        entry["step"] = index

    confidence = 0.0
    if steps:
        scores = [float(entry["confidence"]) for entry in steps]
        confidence = round((sum(scores) / len(scores)) * 0.6 + min(scores) * 0.4, 4)

    return PathwayResult(
        {
            "ok": bool(steps),
            "reason": "" if steps else "no peak difference matched a known neutral loss",
            "engine": "internal:fragmentation-rules",
            "steps": steps,
            "confidence": confidence,
            "precursor_mz": round(precursor, 4),
            # Said out loud, because here the "precursor" is really just the
            # reference peak the differences were measured against.
            "precursor_source": (
                "declared" if getattr(spectrum, "precursor_mz", 0.0) else "base-peak"
            ),
            "structure_known": False,
            "smiles": "",
            "tolerance_da": tolerance_da,
            "observed_peaks": len(peaks),
            "matched_peaks": len(steps),
        }
        | {"note": "无结构信息：仅报告观测峰之间的中性丢失关系，不推断化学键"},
    )


# --------------------------------------------------------------------------- #
# Prompt construction (used by the node and the REST route)
# --------------------------------------------------------------------------- #
def build_prompt(pathway: Dict[str, Any], *, language: str = "zh") -> str:
    """Prompt asking a model to *interpret* an already-computed pathway.

    The rules engine has done the chemistry; the model is asked to explain the
    evidence and flag anything inconsistent.  Keeping the division this way
    means an unavailable model degrades the *narrative*, never the deduction.
    """
    steps = list(pathway.get("steps", []))
    lines: List[str] = []
    if language == "en":
        lines.append(
            "You are a mass-spectrometry specialist. A deterministic rule engine "
            "has already proposed a fragmentation pathway from the measured "
            "spectrum. Explain what the evidence supports."
        )
        lines.append("")
        lines.append(f"Precursor m/z: {pathway.get('precursor_mz')}")
        if pathway.get("formula"):
            lines.append(f"Formula: {pathway['formula']}")
        if pathway.get("smiles"):
            lines.append(f"Structure: {pathway['smiles']}")
        lines.append(
            f"Matched fragments: {len(steps)} of {pathway.get('observed_peaks')} peaks "
            f"(engine confidence {pathway.get('confidence')})."
        )
        lines.append("")
        for entry in steps:
            lines.append(
                f"- m/z {entry.get('observed_mz')} "
                f"({entry.get('relative_intensity', 0) * 100:.1f}% rel., "
                f"{entry.get('mass_error_ppm')} ppm): {entry.get('rule')} — "
                f"{entry.get('rationale')}"
            )
        lines.append("")
        lines.append(
            "Answer with: (1) the most probable fragmentation route in one "
            "paragraph, (2) which peaks are diagnostic and why, (3) any peak the "
            "rules could not explain, (4) what additional measurement would "
            "discriminate the remaining candidates. Do not invent a structure "
            "that was not provided."
        )
        return "\n".join(lines)

    lines.append(
        "你是质谱分析专家。一个确定性规则引擎已经根据实测谱图给出了裂解链路候选，"
        "请解释这些证据支持什么结论。"
    )
    lines.append("")
    lines.append(f"前体离子 m/z：{pathway.get('precursor_mz')}")
    if pathway.get("formula"):
        lines.append(f"分子式：{pathway['formula']}")
    if pathway.get("smiles"):
        lines.append(f"结构：{pathway['smiles']}")
    lines.append(
        f"匹配碎片：{len(steps)} / {pathway.get('observed_peaks')} 个峰"
        f"（引擎置信度 {pathway.get('confidence')}）"
    )
    lines.append("")
    for entry in steps:
        lines.append(
            f"- m/z {entry.get('observed_mz')}"
            f"（相对强度 {entry.get('relative_intensity', 0) * 100:.1f}%，"
            f"误差 {entry.get('mass_error_ppm')} ppm）：{entry.get('rule')} —— "
            f"{entry.get('rationale')}"
        )
    lines.append("")
    lines.append(
        "请按以下结构回答：(1) 用一段话给出最可能的裂解路径；"
        "(2) 指出哪些峰是诊断性的、为什么；"
        "(3) 说明规则引擎无法解释的峰；"
        "(4) 给出能进一步区分剩余候选的实验建议。"
        "在未提供结构的情况下不要臆造结构。"
    )
    return "\n".join(lines)


def summarise_pathway(pathway: Dict[str, Any], *, language: str = "zh") -> str:
    """Rule-engine-only narrative (the honest offline answer)."""
    steps = list(pathway.get("steps", []))
    if not steps:
        reason = pathway.get("reason") or "no match"
        # The precursor still has to be reported when nothing matched: "we
        # found no pathway" is only meaningful next to "and this is the peak we
        # looked from" -- especially when that peak was guessed.
        precursor = pathway.get("precursor_mz")
        source = pathway.get("precursor_source")
        where = (
            f" The reference peak was m/z {precursor}"
            + (f" (source: {source})." if source else ".")
        )
        return (
            f"未能在容差内匹配到任何理论碎片（{reason}）。"
            + (
                f"参考峰为 m/z {precursor}"
                + (f"（来源：{source}）。" if source else "。")
            )
            if language != "en"
            else f"No theoretical fragment matched an observed peak ({reason})." + where
        )

    if language == "en":
        lines = [
            f"Fragmentation pathway built by the built-in rule engine "
            f"(internal:fragmentation-rules), confidence {pathway.get('confidence')}.",
            f"Precursor m/z {pathway.get('precursor_mz')} "
            f"(source: {pathway.get('precursor_source', 'unknown')}); "
            f"{len(steps)} fragment(s) matched out of {pathway.get('observed_peaks')} peaks.",
            "",
        ]
        for entry in steps:
            lines.append(
                f"{entry.get('step')}. m/z {entry.get('observed_mz')} "
                f"(rel. {entry.get('relative_intensity', 0) * 100:.1f}%, "
                f"{entry.get('mass_error_ppm')} ppm) — {entry.get('rule')}: "
                f"{entry.get('rationale')}"
            )
        lines.append("")
        de_adducted = pathway.get("de_adducted")
        if de_adducted:
            lines.append(
                f"Also observed: the de-adducted neutral molecule ion at m/z "
                f"{de_adducted.get('observed_mz')} (rel. "
                f"{de_adducted.get('relative_intensity', 0) * 100:.1f}%, "
                f"{de_adducted.get('mass_error_ppm')} ppm). It breaks no bond, so it "
                f"is not counted as a fragmentation step."
            )
            lines.append("")
        lines.append(
            "This text is generated by the deterministic rule engine, not by a "
            "language model: no AI provider was reachable, so no model "
            "interpretation was added."
        )
        if not pathway.get("structure_known"):
            lines.append(
                "Note: this deduction ran without a structure. It reports only "
                "neutral-loss relationships between the observed peaks; no bond "
                "is inferred."
            )
        return "\n".join(lines)

    lines = [
        f"以下裂解链路由内置规则引擎推导（internal:fragmentation-rules），"
        f"综合置信度 {pathway.get('confidence')}。",
        f"前体离子 m/z {pathway.get('precursor_mz')}"
        f"（来源：{pathway.get('precursor_source', '未知')}）；"
        f"在 {pathway.get('observed_peaks')} 个观测峰中匹配到 {len(steps)} 个碎片。",
        "",
    ]
    for entry in steps:
        lines.append(
            f"{entry.get('step')}. m/z {entry.get('observed_mz')}"
            f"（相对强度 {entry.get('relative_intensity', 0) * 100:.1f}%，"
            f"误差 {entry.get('mass_error_ppm')} ppm）—— {entry.get('rule')}："
            f"{entry.get('rationale')}"
        )
    lines.append("")
    de_adducted = pathway.get("de_adducted")
    if de_adducted:
        lines.append(
            f"另观测到去加合中性分子离子 m/z {de_adducted.get('observed_mz')}"
            f"（相对强度 {de_adducted.get('relative_intensity', 0) * 100:.1f}%，"
            f"误差 {de_adducted.get('mass_error_ppm')} ppm）；"
            f"它未断开任何化学键，故不计入裂解步骤。"
        )
    lines.append("")
    lines.append(
        "本段文字由确定性规则引擎生成，并非大模型输出：当前没有可用的 AI 供应商，"
        "因此未附加模型解读。"
    )
    if not pathway.get("structure_known"):
        lines.append(
            "注意：本次推导没有结构输入，只报告观测峰之间的中性丢失关系，未推断化学键。"
        )
    return "\n".join(lines)


def iter_step_labels(pathway: Dict[str, Any]) -> Iterable[str]:
    """Yield ``"rule @ m/z"`` labels (used by compact renderers)."""
    for entry in pathway.get("steps", []):
        yield f"{entry.get('rule')} @ {entry.get('observed_mz')}"


def theoretical_fragments(smiles: str, adduct: str = "[M+H]+") -> List[Dict[str, Any]]:
    """Theoretical fragment list for a structure, without any measured peaks.

    Exposed for the node's "predict" mode and for tests that need a known answer
    (e.g. DHB must lose H2O / CO / CO2).
    """
    from models.smiles import parse_smiles

    graph = parse_smiles(smiles)
    envelope = isotope_pattern(graph.formula_string(), adduct=adduct)
    if not envelope:
        return []
    precursor = float(envelope[0][0])
    rows: List[Dict[str, Any]] = [
        {
            "rule": "precursor",
            "mz": round(precursor, 4),
            "assignment": f"{graph.formula_string()} {adduct}",
            "confidence": 1.0,
        }
    ]
    for fragment, label, prior, rationale in _neutral_loss_candidates(precursor):
        rows.append(
            {
                "rule": label,
                "mz": round(fragment, 4),
                "assignment": rationale,
                "confidence": round(prior, 4),
            }
        )
    return rows
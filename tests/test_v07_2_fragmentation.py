"""Fragmentation-pathway deduction (v0.7.2, task 93).

Every assertion here is pinned to *chemistry that can be checked against a
textbook*, not to whatever the current implementation happens to print.  The
three bug classes these tests exist to lock shut:

1. **charge double-counting** -- the fragment ion formula already carries the
   hydrogen that holds the charge, so the fragment m/z is the ion formula's
   mass with **no** proton added.  Getting this wrong shifts every structural
   fragment by 1 Da and still "works" on any spectrum with no peak there.
2. **reporting the wrong half of a cleavage** -- cutting a bond yields two
   complementary pieces, but only the scaffold piece is the ion; the sliver
   leaves as a neutral radical.  Reporting both produced "CH2O2 at m/z 46"
   for benzylic cleavage of DHB, which is nonsense.
3. **the de-adducted molecule ion is not a fragmentation step** -- no bond is
   broken to reach it, so it must not consume a step slot or lift confidence.
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from models.fragmentation import (
    MIN_FRAGMENT_HEAVY_ATOMS,
    NEUTRAL_LOSS_DEPTH_DECAY,
    NEUTRAL_LOSSES,
    PathwayResult,
    _formula_of,
    _is_reportable_fragment,
    _neutral_loss_candidates,
    _size_adjusted_prior,
    _structural_candidates,
    deduce_pathway,
    deduce_without_structure,
    summarise_pathway,
)
from models.smiles import parse_smiles
from workflow_engine.objects import Molecule, Peak, Spectrum

DHB = "Oc1cc(O)ccc1C(=O)O"  # 2,5-dihydroxybenzoic acid, C7H6O4
CAFFEINE = "CN1C(=O)C2=C(ncn2C)n(C)c1=O"  # C8H10N4O2
PROTON = 1.00727645


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def spectrum(peaks, *, precursor_mz=None, ms_level=2) -> Spectrum:
    return Spectrum(
        peaks=[Peak(x=float(mz), y=float(intensity)) for mz, intensity in peaks],
        precursor_mz=precursor_mz,
        metadata={"ms_level": ms_level},
    )


def rules_of(pathway: PathwayResult) -> list[str]:
    return [str(step["rule"]) for step in pathway.steps]


def observed_of(pathway: PathwayResult) -> list[float]:
    return [float(step["observed_mz"]) for step in pathway.steps]


# --------------------------------------------------------------------------- #
# 1. formula / charge bookkeeping
# --------------------------------------------------------------------------- #
def test_formula_of_adds_exactly_one_hydrogen_at_the_cleavage_site():
    """The +1 H at the cut is the charge carrier.

    Ethanol's SMILES carries implicit hydrogens (C3H2, C, O1).  Cut the C-O
    bond and keep the carbon side: the stored hydrogens give C2H5, and the cut
    adds exactly one more H for the new valence -- the ion formula C2H6+.
    """
    from models.fragmentation import _component_without

    atoms = list(parse_smiles("CCO").atoms)
    bonds = list(parse_smiles("CCO").bonds)
    carbon_side = _component_without(atoms, bonds, keep=1, drop=2)
    assert _formula_of(carbon_side) == "C2H6"

    # The O side keeps its single stored H and gains the same one: H2O.
    oxygen_side = _component_without(atoms, bonds, keep=2, drop=1)
    assert _formula_of(oxygen_side) == "H2O"


def test_formula_of_is_the_ion_formula_not_the_neutral_plus_a_proton():
    """The fragment m/z is the ion formula's mass -- no proton is added on top.

    ``_formula_of`` already added the charge-carrying hydrogen at the cut, so
    ``formula_mass`` of that formula *is* the fragment m/z.  This is asserted
    against the textbook DHB benzylic cation C7H7O3+ at 139.0395 -- the exact
    value the shipped workflow matches.  The 1 Da-high variant (139.0395 +
    1.0073) is what the old double-count produced.
    """
    from workflow_engine.processing import formula_mass

    assert formula_mass("C7H7O3") == pytest.approx(139.0395, abs=1e-3)
    # Not 138.0317 (missing the charge hydrogen) and not 140.0468 (double
    # counted).  Both of those used to pass unnoticed.
    assert formula_mass("C7H7O3") != pytest.approx(139.0395 - PROTON, abs=1e-3)
    assert formula_mass("C7H7O3") != pytest.approx(139.0395 + PROTON, abs=1e-3)

    # And the caffeine fragment C8H11N4O+ = 179.0933, likewise exact.
    assert formula_mass("C8H11N4O") == pytest.approx(179.0933, abs=1e-3)


def test_reportable_fragment_rejects_radicals_and_small_pieces():
    assert _is_reportable_fragment("C6H5O3") is True
    # "HO" is what cutting an O-H bond produces: a neutral radical, not a peak.
    assert _is_reportable_fragment("HO") is False
    assert _is_reportable_fragment("H2O") is False
    # Too few heavy atoms to be a fragment ion.
    assert _is_reportable_fragment("CH2O") is False
    assert _is_reportable_fragment("C2H4") is False
    assert MIN_FRAGMENT_HEAVY_ATOMS == 3


# --------------------------------------------------------------------------- #
# 2. cleavage enumeration reports the scaffold half only
# --------------------------------------------------------------------------- #
def test_cleavage_reports_the_scaffold_fragment_not_the_sliver():
    """Benzylic cleavage of DHB yields the substituted phenyl cation.

    The complementary piece is CH2O2 (m/z 46.0055): that is the neutral
    radical leaving, never a reported fragment.  The scaffold fragment is
    C7H7O3+ at m/z 139.0395.
    """
    graph = parse_smiles(DHB)
    candidates = _structural_candidates(graph, 155.0339, "[M+H]+")
    mzs = [mz for mz, *_ in candidates]

    assert any(abs(mz - 139.0395) < 1e-3 for mz in mzs)
    # The sliver must not be proposed at all.
    assert not any(abs(mz - 46.0055) < 1e-3 for mz in mzs), (
        "the small complementary piece was proposed as a fragment ion; it "
        "leaves as a neutral radical"
    )


def test_size_adjusted_prior_penalises_slivers():
    # A fragment keeping the whole molecule is unscored down.
    assert _size_adjusted_prior(0.78, 11, 11) == pytest.approx(0.78)
    # Half is exactly the boundary for the scaffold side of a cleavage.
    assert _size_adjusted_prior(0.78, 6, 11) == pytest.approx(0.78)
    # Anything smaller is discounted -- this is the guard that catches a future
    # regression which starts reporting the sliver half again.
    assert _size_adjusted_prior(0.78, 3, 11) < 0.78
    assert _size_adjusted_prior(0.78, 1, 11) < _size_adjusted_prior(0.78, 3, 11)
    # Monotonic: a bigger surviving fragment never scores worse.
    priors = [_size_adjusted_prior(0.78, n, 11) for n in range(1, 12)]
    assert priors == sorted(priors)


# --------------------------------------------------------------------------- #
# 3. the de-adducted molecule ion is not a step
# --------------------------------------------------------------------------- #
def test_de_adducted_molecule_ion_is_not_a_fragmentation_step():
    """DHB [M+H]+ = 155.0339; the neutral molecule is at 154.0261.

    The neutral peak is real and gets recorded, but it breaks no bond, so it
    must not appear as a numbered step (it used to rank above the real -H2O).
    """
    sp = spectrum(
        [
            (155.0339, 1000.0),
            (154.0261, 500.0),  # de-adducted molecule
            (137.0233, 800.0),  # -H2O
        ],
        precursor_mz=155.0339,
    )
    pathway = deduce_pathway(sp, DHB, adduct="[M+H]+")

    rules = rules_of(pathway)
    assert not any("去加合" in rule or "de-adducted" in rule for rule in rules)
    assert "-H2O" in rules

    de_adducted = pathway["de_adducted"]
    assert de_adducted is not None
    assert abs(float(de_adducted["observed_mz"]) - 154.0261) < 1e-3

    # And it must be mentioned, not silently dropped.
    zh = summarise_pathway(pathway, language="zh")
    assert "去加合" in zh


# --------------------------------------------------------------------------- #
# 4. known-answer spectra
# --------------------------------------------------------------------------- #
def test_dhb_minus_water_is_found_with_a_teachable_mass_error():
    sp = spectrum(
        [(155.0339, 1000.0), (137.0231, 800.0), (123.0450, 200.0)],
        precursor_mz=155.0339,
    )
    pathway = deduce_pathway(sp, DHB, adduct="[M+H]+")

    assert pathway["ok"] is True
    assert pathway["precursor_source"] == "declared"

    step = pathway.steps[0]
    assert step["rule"] == "-H2O"
    assert step["observed_mz"] == pytest.approx(137.0231, abs=1e-3)
    assert step["loss_da"] == pytest.approx(18.0108, abs=1e-2)
    # 137.0233 theoretical vs 137.0231 observed -> ~1.5 ppm
    assert abs(step["mass_error_ppm"]) < 5.0


def test_neutral_loss_ladder_is_followed_not_just_a_parallel_fan():
    """A two-step ladder must be reachable and must outrank junk.

    Caffeine [M+H]+ 195.0877 -> -CO -CH3NCO = 110.0713, a textbook product.
    """
    precursor = 195.0877  # caffeine [M+H]+
    sp = spectrum(
        [
            (precursor, 1000.0),
            (110.0713, 400.0),
        ],
        precursor_mz=precursor,
    )
    one_step = deduce_pathway(sp, CAFFEINE, adduct="[M+H]+", max_depth=1)
    two_step = deduce_pathway(sp, CAFFEINE, adduct="[M+H]+", max_depth=2)

    # With depth 1 there is no ladder, so this peak cannot be explained.
    assert not any(
        abs(float(step["observed_mz"]) - 110.0713) < 1e-3
        for step in one_step.steps
    )
    # With depth 2 it is explained, at ~0.2 ppm.
    ladder = [
        step for step in two_step.steps if abs(float(step["observed_mz"]) - 110.0713) < 1e-3
    ]
    assert ladder, f"ladder did not explain m/z 110.0713; got {rules_of(two_step)}"
    rule = str(ladder[0]["rule"])
    assert rule.startswith("-CO-CH3NCO")
    assert abs(float(ladder[0]["mass_error_ppm"])) < 1.0


def test_ladder_prior_decays_with_depth():
    candidates = _neutral_loss_candidates(155.0339, max_depth=2)
    single = {label: prior for mz, label, prior, _ in candidates if label.count("-") == 1}
    double = {label: prior for mz, label, prior, _ in candidates if label.count("-") == 2}
    assert single and double
    # Every two-step ladder must be weaker than the same first step alone.
    for label, prior in double.items():
        first = "-" + label[1:].split("-")[0]
        assert prior < single[first]
    assert NEUTRAL_LOSS_DEPTH_DECAY < 1.0


def test_deeper_ladders_are_superset_of_shallower():
    one = {(label, round(mz, 4)) for mz, label, _, _ in _neutral_loss_candidates(200.0, max_depth=1)}
    two = {(label, round(mz, 4)) for mz, label, _, _ in _neutral_loss_candidates(200.0, max_depth=2)}
    assert one < two


# --------------------------------------------------------------------------- #
# 5. precursor provenance
# --------------------------------------------------------------------------- #
def test_precursor_is_computed_from_the_structure_when_none_is_declared():
    """A 1-MS scan has no precursor; the base peak may be the matrix."""
    sp = spectrum(
        [
            (310.994, 51097.0),  # matrix / dimer -- NOT the analyte
            (155.0339, 12000.0),
            (137.0231, 9000.0),
        ],
        ms_level=1,
    )
    pathway = deduce_pathway(sp, DHB, adduct="[M+H]+")

    assert pathway["precursor_source"] == "structure"
    assert pathway["precursor_mz"] == pytest.approx(155.0339, abs=1e-3)
    # With 155.0339 as the precursor the -H2O peak is explained; anchoring on
    # the 310.994 matrix peak would explain nothing.
    assert "-H2O" in rules_of(pathway)


def test_base_peak_fallback_is_declared_loudly():
    """With no precursor and no structure the engine must say it guessed."""
    sp = spectrum([(310.994, 51097.0), (100.0, 500.0)], ms_level=1)
    pathway = deduce_pathway(sp, "", adduct="[M+H]+")
    assert "base-peak" in str(pathway["precursor_source"])
    assert "base-peak" in summarise_pathway(pathway, language="en")


def test_declared_precursor_wins_over_everything():
    sp = spectrum([(155.0339, 100.0), (137.0231, 800.0)], precursor_mz=155.0339)
    pathway = deduce_pathway(sp, DHB, adduct="[M+H]+")
    assert pathway["precursor_source"] == "declared"


# --------------------------------------------------------------------------- #
# 6. honest degradation without a structure
# --------------------------------------------------------------------------- #
def test_without_structure_no_bond_is_claimed():
    sp = spectrum(
        [(155.0339, 1000.0), (137.0233, 800.0), (110.0713, 400.0)],
        precursor_mz=155.0339,
    )
    pathway = deduce_without_structure(sp)

    assert pathway["structure_known"] is False
    # Only differences between observed peaks -- no chemical bond labels.
    for rule in rules_of(pathway):
        assert "苄位" not in rule
        assert "benzylic" not in rule.lower()
    # Both languages must state the limitation.
    assert "未推断化学键" in summarise_pathway(pathway, language="zh")
    assert "no bond is inferred" in summarise_pathway(pathway, language="en").lower()


def test_empty_spectrum_is_reported_not_crashed():
    sp = spectrum([])
    pathway = deduce_pathway(sp, DHB)
    assert pathway["ok"] is False
    assert pathway["steps"] == []
    assert pathway["observed_peaks"] == 0


def test_unparsable_smiles_degrades_instead_of_raising():
    sp = spectrum([(155.0339, 1000.0), (137.0233, 800.0)], precursor_mz=155.0339)
    pathway = deduce_pathway(sp, "this-is-not-smiles(((", adduct="[M+H]+")
    assert pathway["structure_known"] is False
    # Still finds the neutral-loss explanation.
    assert "-H2O" in rules_of(pathway)


# --------------------------------------------------------------------------- #
# 7. determinism
# --------------------------------------------------------------------------- #
def test_deduction_is_deterministic():
    sp = spectrum(
        [(155.0339, 1000.0), (137.0231, 800.0), (110.0713, 400.0)],
        precursor_mz=155.0339,
    )
    first = deduce_pathway(sp, CAFFEINE, adduct="[M+H]+")
    second = deduce_pathway(sp, CAFFEINE, adduct="[M+H]+")
    assert observed_of(first) == observed_of(second)
    assert first["confidence"] == second["confidence"]


def test_confidence_is_damped_by_the_weakest_step():
    """A single bad step must not be averaged away by good ones.

    DHB [M+H]+ 155.0339 -> -H2O 137.0231 (excellent) -> -H2O 119.0128 (weak).
    """
    sp = spectrum(
        [
            (155.0339, 1000.0),
            (137.0231, 900.0),  # excellent: 1.7 ppm, strong
            (119.0128, 60.0),  # poor: weak peak, so low intensity term
        ],
        precursor_mz=155.0339,
    )
    pathway = deduce_pathway(sp, DHB, adduct="[M+H]+", tolerance_ppm=20.0)
    assert len(pathway.steps) >= 2
    scores = [float(step["confidence"]) for step in pathway.steps]
    mean = sum(scores) / len(scores)
    weakest = min(scores)
    assert pathway["confidence"] == pytest.approx(mean * 0.6 + weakest * 0.4, abs=1e-3)
    assert pathway["confidence"] < mean  # the minimum always pulls it down


# --------------------------------------------------------------------------- #
# 8. the real dataset
# --------------------------------------------------------------------------- #
@pytest.mark.skipif(
    not Path("datasets/mass_spectrometry/scan_018081.mzml").exists(),
    reason="bundled mzML dataset is not present",
)
def test_real_mzml_dataset_explains_dhb():
    """End-to-end on the file that ships with the platform."""
    from workflow_engine.parsers.mzml import read_mzml

    spectra = read_mzml("datasets/mass_spectrometry/scan_018081.mzml")
    assert spectra
    pathway = deduce_pathway(spectra[0], DHB, adduct="[M+H]+")

    assert pathway["ok"] is True
    assert pathway["precursor_source"] == "structure"
    assert pathway["structure_known"] is True
    assert "-H2O" in rules_of(pathway)


# --------------------------------------------------------------------------- #
# 9. the node (multi-port handling)
# --------------------------------------------------------------------------- #
def test_node_accepts_single_object_on_a_multi_port():
    """One edge into a ``multi`` port arrives as one object, not a list.

    A Pydantic model is iterable, so iterating it yields ``(field, value)``
    pairs -- the classic silent-corruption bug thisnormalises.
    """
    from nodes.instruments.fragmentation import FragmentationPathwayNode
    from nodes.loader import get_registry

    get_registry()
    node = get_registry().create("FragmentationPathwayNode")
    node.params.update({"max_steps": 4, "language": "en"})

    sp = spectrum([(155.0339, 1000.0), (137.0231, 800.0)], precursor_mz=155.0339)
    outputs = node.process({"spectrum": sp, "molecule": Molecule(smiles=DHB)}, ctx=None)

    assert outputs["pathway"].rows
    assert "-H2O" in str(outputs["pathway"].rows)
    assert "Fragmentation pathway" in outputs["text"].text


def test_node_handles_a_list_on_a_multi_port():
    from nodes.instruments.fragmentation import FragmentationPathwayNode
    from nodes.loader import get_registry

    get_registry()
    node = get_registry().create("FragmentationPathwayNode")
    node.params.update({"max_steps": 4, "language": "en"})

    sp = spectrum([(155.0339, 1000.0), (137.0231, 800.0)], precursor_mz=155.0339)
    outputs = node.process(
        {"spectrum": [sp], "molecule": [Molecule(smiles=DHB)]}, ctx=None
    )
    assert outputs["pathway"].rows


def test_node_without_a_molecule_still_runs():
    from nodes.instruments.fragmentation import FragmentationPathwayNode
    from nodes.loader import get_registry

    get_registry()
    node = get_registry().create("FragmentationPathwayNode")
    node.params.update({"max_steps": 4, "language": "en"})

    sp = spectrum([(155.0339, 1000.0), (137.0231, 800.0)], precursor_mz=155.0339)
    outputs = node.process({"spectrum": sp}, ctx=None)
    assert outputs["pathway"] is not None


def test_node_rejects_a_missing_spectrum():
    from nodes.instruments.fragmentation import FragmentationPathwayNode
    from nodes.loader import get_registry

    get_registry()
    node = get_registry().create("FragmentationPathwayNode")
    with pytest.raises(Exception):
        node.process({"spectrum": None}, ctx=None)
"""Regression tests for the solid-state engine and the agent planning path.

These lock down failures that were real, reproducible, and silent: the Born wall
that was negative under compression, the energy curve that moved with the k-grid,
the relaxation that discarded its own result, and the planner whose catalogue was
always empty.

Style note: every assertion here is behavioural.  No test reads the source with
``inspect.getsource`` to confirm a comment still says what it used to say -- that
approach passes on a file that documents a bug it no longer has.
"""

from __future__ import annotations

import re
import tempfile
from pathlib import Path

import pytest

from nodes.loader import get_registry
from simulations import tight_binding as tb


# --------------------------------------------------------------------------- #
# 1. The Born repulsion must be a wall, not a well
# --------------------------------------------------------------------------- #
class TestRepulsionIsAlwaysPositive:
    def test_repulsion_never_negative_across_a_wide_compression_range(self):
        """``rep(3.5)`` used to return -5.87 eV: the "wall" was a well.

        An asymmetric form that normalises each half only in the direction it
        acts -- ``(r_ref/d)^2 + (d/r_ref)^6 - 2`` -- goes negative for moderate
        compression and the equilibrium lands below every measured value.
        """
        for lattice in ("sc", "bcc", "fcc", "hcp"):
            for element in ("Al", "Cu", "Fe"):
                for a in [0.4 * v for v in (3.0, 3.5, 4.0, 4.5, 5.0, 6.0)]:
                    value = tb.repulsion_energy(lattice, element, a)
                    assert value >= 0.0, (
                        f"repulsion went negative: {element} {lattice} a={a} -> {value}"
                    )

    def test_repulsion_vanishes_exactly_at_the_reference_bond(self):
        for lattice, element in (("fcc", "Al"), ("fcc", "Cu"), ("bcc", "Fe")):
            reference = tb._reference_bond(element, lattice)
            assert reference > 0.0
            # The cell whose nearest-neighbour distance equals the reference.
            a = reference * (2.0 if lattice == "fcc" else 4.0 / 3.0) ** 0.5
            assert tb.repulsion_energy(lattice, element, a) == pytest.approx(0.0, abs=1e-9)

    def test_repulsion_rises_on_both_sides_of_the_minimum(self):
        reference_a = tb._reference_bond("Al", "fcc") * 2.0 ** 0.5
        # Compression: the factor f shrinks, the repulsion must climb.
        below = [tb.repulsion_energy("fcc", "Al", reference_a * f) for f in (0.85, 0.90, 0.95)]
        above = [tb.repulsion_energy("fcc", "Al", reference_a * f) for f in (1.05, 1.10, 1.15)]
        assert below == sorted(below, reverse=True), f"not monotonic under compression: {below}"
        assert above == sorted(above), f"not monotonic under expansion: {above}"
        assert below[-1] > 0.0 and above[0] > 0.0
        # And the wall must be steeper on the compressed side, where it has to
        # stop an attraction that grows without bound.
        assert below[0] > above[-1], "compression must be resisted harder than expansion"


# --------------------------------------------------------------------------- #
# 2. The energy curve must not depend on the integration grid
# --------------------------------------------------------------------------- #
class TestTotalEnergyIsGridIndependent:
    @pytest.mark.parametrize("n_kpoints", [2, 3, 4, 6])
    def test_minimum_location_stable_across_k_grids(self, n_kpoints):
        """A numerical knob had become the parameter being measured.

        Summing band energies over the k list makes the total proportional to
        the number of points: the same Al relaxation landed at 4.06 A on 2x2x2
        and 6.08 A on 11x11x11.  Filling against a self-consistent Fermi level
        and averaging over k removes the proportionality; the residual spread
        must stay well under the 0.1 A that a real material variation shows.
        """
        samples = [3.60 + 0.05 * index for index in range(17)]
        energies = [
            tb.total_energy("fcc", "Al", a, n_kpoints=n_kpoints) for a in samples
        ]
        best = samples[energies.index(min(energies))]
        assert best == pytest.approx(4.0, abs=0.12), (
            f"n_kpoints={n_kpoints} put the minimum at {best:.3f} A"
        )

    def test_energy_curve_has_a_single_well_not_a_field_of_local_minima(self):
        """Fermi smearing must remove the cliffs a hard cut leaves behind.

        With a sharp ``E < E_F`` fill, every band crossing the Fermi level makes
        the occupied sum jump, so E(a) has a spurious local minimum roughly every
        0.1 A and a gradient optimiser stalls on a flat spot -- which is how a
        relaxation "converged" at an 11% error without moving.
        """
        samples = [3.50 + 0.02 * index for index in range(61)]
        energies = [tb.total_energy("fcc", "Al", a, n_kpoints=4) for a in samples]
        minima = 0
        for index in range(1, len(energies) - 1):
            if energies[index] <= energies[index - 1] and energies[index] < energies[index + 1]:
                minima += 1
        assert minima <= 2, f"E(a) has {minima} interior minima -- not a potential surface"

    def test_fermi_level_occupation_conserves_electron_count(self):
        """Smearing must not quietly change how many electrons there are."""
        samples = [3.8 + 0.05 * index for index in range(9)]
        for a in samples:
            structure = tb.compute_bands(
                lattice_key="fcc", element="Al", a=a, shells=2,
                k_points=tb._uniform_kpoints(3),
            )
            n_orbitals = len(structure.energies[0])
            target = int(round(structure._filling() * n_orbitals)) * len(structure.energies)
            level = tb._fermi_level(structure.flat_energies(), target, tb._SMEARING_EV)
            occupied = sum(
                tb._fermi_occupation(value, level, tb._SMEARING_EV)
                for value in structure.flat_energies()
            )
            assert occupied == pytest.approx(target, rel=0.02)

    def test_repeated_evaluation_is_bit_identical(self):
        first = tb.total_energy("fcc", "Al", 4.0, n_kpoints=4)
        second = tb.total_energy("fcc", "Al", 4.0, n_kpoints=4)
        assert first == second


# --------------------------------------------------------------------------- #
# 3. Relaxation must be reproducible and land near experiment
# --------------------------------------------------------------------------- #
class TestRelaxation:
    @pytest.mark.parametrize("start", [3.60, 4.05, 4.60])
    def test_al_relaxes_to_the_same_answer_from_any_start(self, start):
        """Best-so-far plus uphill back-off: the result is a basin, not a step count."""
        results = {
            round(tb.relax_lattice("fcc", "Al", start, steps=40, n_kpoints=4)["a_relaxed"], 3)
            for start in (3.60, 4.05, 4.60)
        }
        assert len(results) == 1, f"relaxation depended on where it started: {results}"

    @pytest.mark.parametrize(
        "element,lattice,expected",
        [
            ("Al", "fcc", 4.05),
            ("Cu", "fcc", 3.615),
            ("Ni", "fcc", 3.524),
            ("Ag", "fcc", 4.086),
            ("Fe", "bcc", 2.866),
        ],
    )
    def test_relaxed_constants_land_within_a_few_percent(self, element, lattice, expected):
        result = tb.relax_lattice(lattice, element, expected * 0.92, steps=40, n_kpoints=4)
        error = abs(result["a_relaxed"] - expected) / expected
        assert error < 0.05, (
            f"{element} {lattice} relaxed to {result['a_relaxed']:.3f} A, "
            f"measured {expected:.3f} A ({error * 100:.1f}% off)"
        )
        # A relaxation with no stated accuracy reads as a prediction.
        assert result["accuracy_note"], "relaxation must report its distance to experiment"

    def test_bandwidth_responds_to_the_lattice_constant(self):
        """``a`` must actually enter the Hamiltonian.

        The reference length used to be ``d_nn(a)`` itself, so
        ``exp(-(d - r0) * decay)`` was identically 1 and every material produced
        the same band structure at every lattice constant.  Measured span for Al
        fcc: 21.95 eV at a = 3.60 Å against 16.80 eV at a = 4.50 Å, so a 25%
        change is the order of magnitude a real table gives.
        """
        narrow = tb.compute_bands("fcc", "Al", 3.60)
        wide = tb.compute_bands("fcc", "Al", 4.50)
        span_narrow = max(narrow.flat_energies()) - min(narrow.flat_energies())
        span_wide = max(wide.flat_energies()) - min(wide.flat_energies())
        assert span_narrow > span_wide * 1.2, (
            f"band width barely moved with a: {span_narrow:.3f} -> {span_wide:.3f} eV"
        )

    def test_different_elements_give_different_band_structures(self):
        """The old single-orbital model reported the same bands for everything."""
        aluminium = tb.compute_bands("fcc", "Al", 4.05)
        copper = tb.compute_bands("fcc", "Cu", 3.61)
        span_a = max(aluminium.flat_energies()) - min(aluminium.flat_energies())
        span_c = max(copper.flat_energies()) - min(copper.flat_energies())
        assert abs(span_a - span_c) > 0.5, (
            f"Al and Cu produced the same span: {span_a:.3f} vs {span_c:.3f} eV"
        )

    def test_aluminium_is_a_metal_and_the_dos_says_why(self):
        """s-p hybridisation at E_F is the reason; a gap-only check misses it."""
        from simulation_runtime.materials import _dos_at

        structure = tb.compute_bands("fcc", "Al", 4.05)
        x, y = tb.density_of_states(structure.flat_energies(), points=200)
        fermi = tb.fermi_energy(structure)
        at_fermi = _dos_at(x, y, fermi)
        assert at_fermi > 1e-3, f"Al reported DOS(E_F)={at_fermi}, expected a metal"

        pdos = tb.projected_density_of_states(structure, points=200)
        assert len(pdos["orbitals"]) == 4, "expected s, px, py, pz channels"
        assert max(max(curve) for curve in pdos["orbitals"]) > 0.0


# --------------------------------------------------------------------------- #
# 4. The planner must actually know what nodes exist
# --------------------------------------------------------------------------- #
class TestPlannerCatalogue:
    def _tool_specs(self):
        from nodes.agent.tools import tool_registry

        registry = tool_registry()
        return [registry.get(name).to_dict() for name in registry.types() if registry.get(name)]

    def test_catalogue_is_not_empty(self):
        """The bug: the registry emits ``node_type``, the planner read ``type``.

        An empty catalogue made the prompt say "(no node catalogue available)",
        and the planner then fell back to the recipe and reported success -- so
        the LLM path was dead without any error anywhere.
        """
        from nodes.agent.planner import Planner

        planner = Planner(self._tool_specs())
        assert len(planner.catalog) > 50, (
            f"planner catalogue has {len(planner.catalog)} entries"
        )
        assert "ABACUSNode" in planner.catalog

    def test_catalogue_entry_exposes_parameter_names_and_enum_values(self):
        from nodes.agent.planner import Planner, _catalog_entry

        planner = Planner(self._tool_specs())
        entry = _catalog_entry("ABACUSNode", planner.catalog["ABACUSNode"])
        assert "calculation(enum:" in entry, "enum options missing from the prompt"
        assert "cell_relax" in entry and "pdos" in entry
        assert "in: material" in entry and "out:" in entry

    def test_llm_plan_drops_parameters_the_node_does_not_declare(self):
        """A hallucinated parameter must be reported, not silently ignored.

        Nodes store unknown params and never read them, so an invented name
        looks accepted, survives validation, and quietly does nothing.
        """
        from nodes.agent.planner import Planner

        planner = Planner(self._tool_specs())
        completion = (
            '{"intent":"solid_state_dft","steps":['
            '{"node_type":"ABACUSNode","id":"x","params":'
            '{"calculation":"pdos","bandwidth":3.0}}]}'
        )
        plan = planner.plan_from_llm("dos", completion)
        assert plan is not None
        assert "bandwidth" not in plan.steps[0].params
        assert any("bandwidth" in note for note in plan.notes), plan.notes

    def test_llm_plan_rewrites_an_option_label_to_its_value(self):
        """A model that echoes back an option's *label* has not made a mistake.

        Options come in two shapes -- bare strings (ABACUSNode.calculation) and
        ``(value, label)`` pairs (AgentPlanNode.language).  Discarding a whole
        plan because the model wrote 中文 instead of "zh" throws away good work.
        """
        from nodes.agent.planner import Planner

        planner = Planner(self._tool_specs())
        completion = (
            '{"intent":"report","steps":['
            '{"node_type":"AgentPlanNode","id":"p","params":{"language":"\\u4e2d\\u6587"}}]}'
        )
        plan = planner.plan_from_llm("report", completion)
        assert plan is not None
        assert plan.steps[0].params.get("language") == "zh"

    def test_llm_plan_drops_an_enum_value_that_is_not_declared(self):
        from nodes.agent.planner import Planner

        planner = Planner(self._tool_specs())
        completion = (
            '{"intent":"solid_state_dft","steps":['
            '{"node_type":"ABACUSNode","id":"x","params":{"calculation":"magic"}}]}'
        )
        plan = planner.plan_from_llm("dft", completion)
        assert plan is not None
        assert "calculation" not in plan.steps[0].params
        assert any("calculation" in note for note in plan.notes), plan.notes


# --------------------------------------------------------------------------- #
# 5. Recipes must only use parameters and ports that exist
# --------------------------------------------------------------------------- #
class TestRecipesMatchTheRegistry:
    def _specs(self):
        return {spec["type"]: spec for spec in get_registry().specs()}

    def test_every_recipe_step_is_runnable_as_written(self):
        """Recipes carried 16 parameters no node declares.

        ``PeakPickingNode`` was called with ``height``/``limit`` when its real
        parameters are ``prominence``/``max_peaks``; ``SpectrumFileNode`` with
        ``technique`` instead of ``mode``.  Unknown names are stored and never
        read, so every one of those settings was a no-op that still validated.
        """
        from nodes.agent.planner import RECIPES

        specs = self._specs()
        problems = []
        for intent, recipe in RECIPES.items():
            for step in recipe["steps"]:
                spec = specs.get(step["type"])
                if spec is None:
                    problems.append(f"{intent}: unknown node {step['type']}")
                    continue
                names = {p["name"] for p in spec.get("parameters", [])}
                options = {
                    p["name"]: [
                        item[0] if isinstance(item, (list, tuple)) else item
                        for item in (p.get("options") or [])
                    ]
                    for p in spec.get("parameters", [])
                }
                for key, value in (step.get("params") or {}).items():
                    if key not in names:
                        problems.append(f"{intent}/{step['type']}: no parameter {key!r}")
                    elif options[key] and value not in options[key]:
                        problems.append(
                            f"{intent}/{step['type']}: {key}={value!r} not in {options[key]}"
                        )
                ports = {p["name"] for p in spec.get("inputs", [])}
                for port in (step.get("inputs") or {}):
                    if port not in ports:
                        problems.append(f"{intent}/{step['type']}: no input port {port!r}")
        assert not problems, "\n".join(problems)

    def test_solid_state_recipe_relaxes_before_computing_bands(self):
        """Bands must run on the relaxed cell, not the one that came in.

        The relaxation used to return its input material unchanged, so the band
        node re-resolved the original lattice constant: the run reported
        "a 4.050 -> 3.987 A" and then plotted a band structure for a = 4.050 A.
        Every number in the report was self-consistent about the wrong cell.
        """
        from nodes.agent.planner import RECIPES

        steps = {step["id"]: step for step in RECIPES["solid_state_dft"]["steps"]}
        assert "relax" in steps
        for downstream in ("bands", "pdos"):
            assert steps[downstream]["inputs"]["material"] == "relax.material", (
                f"{downstream} must consume the relaxed cell"
            )


# --------------------------------------------------------------------------- #
# 6. The end-to-end reference case
# --------------------------------------------------------------------------- #
class TestSolidStateWorkflow:
    def _run(self, question):
        from nodes.agent.planner import Planner
        from nodes.agent.tools import tool_registry
        from nodes.agent.workflow_generator import WorkflowGenerator
        from workflow_engine.engine import WorkflowEngine
        from workflow_engine.workflow import Workflow

        registry = tool_registry()
        catalog = {
            name: registry.get(name).to_dict()
            for name in registry.types()
            if registry.get(name)
        }
        plan = Planner(list(catalog.values())).plan(question)
        document = WorkflowGenerator(catalog).generate(plan)
        workflow = Workflow.from_dict(document)
        assert workflow.validate() == [], workflow.validate()
        return WorkflowEngine(max_workers=4, use_cache=False).run(workflow).to_dict()

    def test_agent_plans_and_runs_the_reference_case(self):
        result = self._run("对铝做原胞优化并计算能带态密度")
        assert result["status"] == "completed", result.get("errors")
        assert not result["errors"], result["errors"]

        records = result["records"]
        assert {"relax", "bands", "pdos"} <= set(records)
        assert all(records[key]["status"] == "completed" for key in records)

        relaxed = _text_of(records["relax"])
        assert "-> " in relaxed and "cell-relax" in relaxed

        relaxed_a = _number_from(relaxed, r"->\s*([\d.]+)\s*Å")
        # Bands and DOS must quote the same cell the relaxation produced.
        for node in ("bands", "pdos"):
            value = _number_from(_text_of(records[node]), r"a=([\d.]+)\s*Å")
            assert value == pytest.approx(relaxed_a, abs=0.01), (
                f"{node} ran at a={value} but the relaxation produced {relaxed_a}"
            )

    def test_independent_calculations_do_not_overwrite_each_other(self):
        """Parallel bands and PDOS both write ``Al_primitive.STRU``.

        Sharing one directory made the surviving file depend on thread timing.
        Keying the directory on the node id is what makes parallelism safe.
        """
        result = self._run("对铝做原胞优化并计算能带态密度")
        run_dir = Path(result["records"]["relax"].get("run_dir") or "output/runs")
        candidates = sorted(run_dir.glob("*/bands/Al_primitive.STRU")) or sorted(
            run_dir.rglob("bands/Al_primitive.STRU")
        )
        assert candidates, f"bands node wrote no STRU under {run_dir}"


def _text_of(record) -> str:
    text = (record.get("outputs") or {}).get("text") or {}
    return str(text.get("text", "")) if isinstance(text, dict) else str(text)


def _number_from(text: str, pattern: str) -> float:
    match = re.search(pattern, text)
    assert match, f"pattern {pattern!r} not found in {text[:160]!r}"
    return float(match.group(1))
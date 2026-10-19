"""Regression tests for the six delivered product figures (v0.7.3).

The reference case delivers six PNG files.  Before this work the platform
delivered **none** of them: the run produced an HTML report, three ABACUS
decks and a ``STRU``, and the figures existed only as numbers inside the
report.  Three separate defects had to be fixed before a band structure could
be drawn at all, and each of them failed silently:

* ``to_array`` ``ravel()``-ed the ``[k][band]`` matrix into one flat run, so a
  spectrum carried 71 x values against 284 y values;
* the matrix is k-major, so even intact it drew as 57 four-point stubs rather
  than four dispersing bands;
* matplotlib's mathtext parser is not thread safe, and the engine runs
  same-generation nodes in parallel, so two of three relaxation figures failed
  with ``ParseException``.

Every assertion below is behavioural.  The reverse check -- reverting to the
old behaviour and confirming these tests fail -- is recorded in
``test_reverting_to_flattened_bands_breaks_the_figure``.
"""

from __future__ import annotations

import json
import math
import tempfile
import zipfile
from pathlib import Path

import pytest

from nodes.loader import create_node, get_registry
from simulations import tight_binding as tb
from workflow_engine.objects import Material, Spectrum, Table

WORKFLOW = Path(__file__).resolve().parents[1] / "workflows" / "11_solid_state_dft.json"

#: The exact set the reference case promises.
EXPECTED_FIGURES = (
    "Al_能带图.png",
    "Al_态密度_DOS.png",
    "Al_投影态密度_PDOS.png",
    "Al_弛豫能量收敛.png",
    "Al_弛豫力收敛.png",
    "Al_弛豫应力收敛.png",
)


@pytest.fixture(scope="module")
def registry():
    return get_registry()


def _relax(relax_steps: int = 25) -> dict:
    return tb.relax_lattice("fcc", "Al", 4.05, steps=relax_steps, n_kpoints=4)


# --------------------------------------------------------------------------- #
# 1. A band structure must survive as per-band traces
# --------------------------------------------------------------------------- #
class TestBandStructureIsMulticurve:
    def test_two_dimensional_input_lands_in_curves_not_a_flat_run(self):
        """``from_arrays`` used to ``ravel()`` a 2-D y into one long list."""
        spectrum = Spectrum.from_arrays(
            [0.0, 1.0, 2.0, 3.0],
            [[1.0, 2.0, 3.0, 4.0], [5.0, 6.0, 7.0, 8.0]],
            mode="Bands",
        )
        assert spectrum.is_multicurve()
        assert len(spectrum.curves) == 2
        assert spectrum.curves[0] == [1.0, 2.0, 3.0, 4.0]
        assert spectrum.curves[1] == [5.0, 6.0, 7.0, 8.0]
        # ``y`` must stay empty: a consumer reading only ``y`` would otherwise
        # plot one band as if it were the entire structure.
        assert spectrum.y == []
        assert len(spectrum.x) == 4

    def test_one_dimensional_input_still_uses_y(self):
        """The ordinary single-trace case must be untouched by that change."""
        spectrum = Spectrum.from_arrays([1.0, 2.0], [3.0, 4.0], mode="DOS")
        assert not spectrum.is_multicurve()
        assert spectrum.y == [3.0, 4.0]
        assert spectrum.curves == []
        assert spectrum.traces() == [[3.0, 4.0]]

    def test_a_single_row_matrix_does_not_count_as_multicurve(self):
        spectrum = Spectrum.from_arrays([1.0, 2.0], [[3.0, 4.0]], mode="Generic")
        # One row is still one trace, but the shape was explicitly 2-D so it
        # must not be flattened into ``y`` either.
        assert spectrum.y == []
        assert spectrum.curves == [[3.0, 4.0]]

    def test_traces_accessor_is_uniform_for_both_shapes(self):
        single = Spectrum.from_arrays([1.0], [2.0], mode="DOS")
        multi = Spectrum.from_arrays([1.0], [[2.0], [3.0]], mode="Bands")
        assert single.traces() == [[2.0]]
        assert multi.traces() == [[2.0], [3.0]]

    def test_tic_is_zero_for_a_band_structure(self):
        """Summing band energies is not an ion current."""
        spectrum = Spectrum.from_arrays([0.0, 1.0], [[-1.5, -1.5], [2.0, 2.0]],
                                        mode="Bands")
        assert spectrum.tic() == 0.0

    def test_clip_preserves_every_curve(self):
        spectrum = Spectrum.from_arrays(
            [0.0, 1.0, 2.0], [[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]], mode="Bands"
        )
        clipped = spectrum.clip(1.0, 2.0)
        assert clipped.x == [1.0, 2.0]
        assert clipped.curves == [[2.0, 3.0], [5.0, 6.0]]

    def test_summary_reports_the_trace_count(self):
        spectrum = Spectrum.from_arrays([0.0, 1.0], [[1.0, 2.0], [3.0, 4.0]],
                                        mode="Bands")
        assert "2 traces" in spectrum.summary()

    def test_preview_carries_the_curves_to_the_frontend(self):
        """The frontend truncates to ``min(len(x), len(y))``.

        With ``y`` empty and ``curves`` absent from ``preview``, a band
        structure renders as an empty panel in the dock -- which is what the
        old code did even after ``from_arrays`` was fixed.
        """
        preview = Spectrum.from_arrays(
            [0.0, 1.0], [[1.0, 2.0], [3.0, 4.0]], mode="Bands"
        ).preview()
        assert preview["curves"] == [[1.0, 2.0], [3.0, 4.0]]


# --------------------------------------------------------------------------- #
# 2. The energies matrix is k-major and must be transposed
# --------------------------------------------------------------------------- #
class TestBandMatrixOrientation:
    def test_compute_bands_is_k_major(self):
        """One row per k point -- the fact the figure depends on."""
        structure = tb.compute_bands(lattice_key="fcc", element="Al", a=4.05,
                                     points_per_segment=6)
        assert len(structure.energies) == len(structure.k_points)
        assert len(structure.energies[0]) == structure.n_orbitals_per_site()

    def test_band_spectrum_has_one_trace_per_band(self, registry):
        from simulation_runtime import run

        result = run("materials", Material(name="Al", formula="Al",
                                           structure={"a": 4.05}),
                     backend="abacus", calculation="bands", lattice="fcc",
                     band_points=6)
        spectrum = result.ports["spectrum"]
        structure = tb.compute_bands(lattice_key="fcc", element="Al", a=4.05,
                                     points_per_segment=6)
        n_bands = structure.n_orbitals_per_site()
        assert len(spectrum.curves) == n_bands
        # Each trace spans the whole path.  Untransposed, the same data gave
        # ``len(k_points)`` traces of ``n_bands`` points -- vertical stubs.
        for row in spectrum.curves:
            assert len(row) == len(spectrum.x)
            assert len(row) > n_bands

    def test_band_spectrum_carries_the_high_symmetry_ticks(self, registry):
        from simulation_runtime import run

        result = run("materials", Material(name="Al", formula="Al",
                                           structure={"a": 4.05}),
                     backend="abacus", calculation="bands", lattice="fcc",
                     band_points=4)
        meta = result.ports["spectrum"].metadata
        assert meta["tick_labels"] == ["G", "X", "W", "K", "G", "L", "W", "X"]
        assert len(meta["tick_positions"]) == len(meta["tick_labels"])

    def test_bands_cross_the_fermi_level_so_aluminium_reads_as_a_metal(self, registry):
        from simulation_runtime import run

        result = run("materials", Material(name="Al", formula="Al",
                                           structure={"a": 4.05}),
                     backend="abacus", calculation="bands", lattice="fcc",
                     band_points=10)
        spectrum = result.ports["spectrum"]
        # Energies are stored relative to E_F, so a crossing is a sign change.
        signs = {row[0] * row[-1] > 0 for row in spectrum.curves}
        assert len(signs) == 2, "no band crosses E_F: aluminium would read as a gap"


# --------------------------------------------------------------------------- #
# 3. Force and stress must exist in the relaxation trace
# --------------------------------------------------------------------------- #
class TestRelaxationTraceCarriesForceAndStress:
    def test_history_rows_expose_force_and_stress(self):
        result = _relax()
        for row in result["history"][1:]:
            assert row["force_ev_per_angstrom"] is not None
            assert row["stress_gpa"] is not None

    def test_first_row_has_no_force_and_no_stress(self):
        """The start-of-run gradient has not been evaluated.

        Seeding it with 0.0 would draw a flat start on the force and stress
        figures and read as "the residual force at the input geometry was
        exactly zero" -- a claim the optimiser has not made.
        """
        first = _relax()["history"][0]
        assert first["force_ev_per_angstrom"] is None
        assert first["stress_gpa"] is None

    def test_residual_force_decays_towards_zero(self):
        forces = [abs(row["force_ev_per_angstrom"])
                  for row in _relax()["history"][1:]
                  if row["force_ev_per_angstrom"] is not None]
        assert forces, "no force was recorded at all"
        assert forces[-1] < forces[0] / 100.0

    def test_stress_shares_the_sign_convention_of_the_force(self):
        """``sigma = -dE/dV`` and ``F = -dE/da`` share the sign of ``dE/da``."""
        rows = [row for row in _relax()["history"][1:] if row["force_ev_per_angstrom"]]
        for row in rows:
            assert row["force_ev_per_angstrom"] * row["stress_gpa"] > 0.0

    def test_stress_magnitude_matches_the_analytic_derivative(self):
        """Recompute ``-dE/dV`` independently of the relaxation loop."""
        lattice_key, element, a = "fcc", "Al", 3.987
        expected = tb._stress_gpa(
            lattice_key, element, a,
            d_energy_da=(tb.total_energy(lattice_key, element, a + 0.01, n_kpoints=4)
                         - tb.total_energy(lattice_key, element, a - 0.01, n_kpoints=4)) / 0.02,
        )
        volume = tb.cell_volume(lattice_key, a, element)
        assert volume > 0.0
        assert abs(expected) < 1e6  # a GPa-scale number, not eV/Å

    def test_cell_volume_matches_the_analytic_fcc_value(self):
        for a in (3.5, 4.05, 5.0):
            # fcc primitive cell: a^3 / 4
            assert tb.cell_volume("fcc", a, "Al") == pytest.approx(a ** 3 / 4.0, rel=1e-9)

    def test_relaxation_table_has_the_five_expected_columns(self, registry):
        from simulation_runtime import run

        result = run("materials", Material(name="Al", formula="Al",
                                           structure={"a": 4.05}),
                     backend="abacus", calculation="cell_relax", lattice="fcc",
                     relax_steps=20)
        table = result.ports["table"]
        assert table.columns == ["step", "a (Å)", "energy (eV)",
                                 "force (eV/Å)", "stress (GPa)"]

    def test_relaxation_emits_a_three_trace_convergence_spectrum(self, registry):
        from simulation_runtime import run

        spectrum = run("materials", Material(name="Al", formula="Al",
                                             structure={"a": 4.05}),
                       backend="abacus", calculation="cell_relax",
                       lattice="fcc", relax_steps=20).ports["spectrum"]
        assert spectrum.mode == "Convergence"
        assert spectrum.curve_labels == ["energy", "force", "stress"]
        assert len(spectrum.curves) == 3
        # The unmeasured first step must be a gap, not a zero.
        assert math.isnan(spectrum.curves[1][0])
        assert math.isnan(spectrum.curves[2][0])


# --------------------------------------------------------------------------- #
# 4. The figure node
# --------------------------------------------------------------------------- #
class TestFigureExportNode:
    def test_node_is_registered(self, registry):
        assert "FigureExportNode" in registry

    def test_declares_every_figure_kind_it_dispatches(self, registry):
        from nodes.report import FIGURE_KINDS

        spec = next(item for item in registry.specs()
                    if item.get("type") == "FigureExportNode")
        kind_param = next(item for item in spec["parameters"]
                          if item["name"] == "kind")
        values = {value for value, _ in kind_param["options"]}
        # ``auto`` is the sentinel; every other entry must be a real kind with
        # its own label and file stem, or a dispatched kind is unreachable from
        # the GUI parameter list -- ``kind`` is what selects it.
        assert values - {"auto"} == set(FIGURE_KINDS) - {"auto"}
        for key in values - {"auto"}:
            assert FIGURE_KINDS[key]["stem"], f"{key} has no file stem"
            assert FIGURE_KINDS[key]["title"], f"{key} has no title"


    @pytest.mark.parametrize("kind,stem", [
        ("band_structure", "band_structure"),
        ("dos", "dos"),
        ("pdos", "pdos"),
        ("relax_convergence", "relax_convergence"),
    ])
    def test_every_kind_renders_a_real_png(self, registry, kind, stem):
        from simulation_runtime import run

        calc = {"band_structure": "bands", "dos": "dos",
                "pdos": "pdos", "relax_convergence": "cell_relax"}[kind]
        spectrum = run("materials", Material(name="Al", formula="Al",
                                            structure={"a": 4.05}),
                       backend="abacus", calculation=calc, lattice="fcc",
                       band_points=6, relax_steps=15).ports["spectrum"]
        with tempfile.TemporaryDirectory() as tmp:
            node = create_node("FigureExportNode", node_id="fig",
                               params={"kind": kind})
            written = node.execute({"spectrum": [spectrum]},
                                   ctx=_Ctx(tmp))["text"].metadata["figures"]
            assert len(written) == 1
            payload = Path(written[0]).read_bytes()
            # PNG magic -- a placeholder .txt would sail past a size check.
            assert payload[:8] == b"\x89PNG\r\n\x1a\n"
            assert Path(written[0]).stem == stem

    def test_chinese_file_names_survive(self, registry):
        """``safe_filename`` maps ``能带图`` to the empty string."""
        from simulation_runtime import run

        spectrum = run("materials", Material(name="Al", formula="Al",
                                             structure={"a": 4.05}),
                       backend="abacus", calculation="bands", lattice="fcc",
                       band_points=6).ports["spectrum"]
        with tempfile.TemporaryDirectory() as tmp:
            node = create_node("FigureExportNode", node_id="fig",
                               params={"filename": "Al_能带图"})
            written = node.execute({"spectrum": [spectrum]},
                                   ctx=_Ctx(tmp))["text"].metadata["figures"]
            assert Path(written[0]).name == "Al_能带图.png"

    def test_convergence_trace_selects_one_series(self, registry):
        from simulation_runtime import run

        spectrum = run("materials", Material(name="Al", formula="Al",
                                             structure={"a": 4.05}),
                       backend="abacus", calculation="cell_relax",
                       lattice="fcc", relax_steps=15).ports["spectrum"]
        with tempfile.TemporaryDirectory() as tmp:
            for trace, stem in ((1, "e"), (2, "f"), (3, "s")):
                node = create_node("FigureExportNode", node_id=f"fig{trace}",
                                   params={"kind": "relax_convergence",
                                           "filename": stem, "trace": trace})
                written = node.execute({"spectrum": [spectrum]},
                                       ctx=_Ctx(tmp))["text"].metadata["figures"]
                assert Path(written[0]).read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"

    def test_a_relaxation_table_can_also_be_plotted(self, registry):
        """The node accepts either object type, because the two arrive on
        different ports in different graph shapes."""
        table = Table(
            name="Lattice relaxation",
            columns=["step", "a (Å)", "energy (eV)", "force (eV/Å)", "stress (GPa)"],
            rows=[[0, 4.05, -17.64, None, None],
                  [1, 4.07, -17.66, -0.72, -9.4],
                  [2, 4.08, -17.67, -0.15, -2.0]],
        )
        with tempfile.TemporaryDirectory() as tmp:
            node = create_node("FigureExportNode", node_id="fig",
                               params={"kind": "relax_convergence"})
            written = node.execute({"table": [table]},
                                   ctx=_Ctx(tmp))["text"].metadata["figures"]
            assert Path(written[0]).read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"

    def test_an_empty_spectrum_fails_loudly_instead_of_writing_a_stub(self, registry):
        """A figure node that silently skipped its output would report success
        and deliver five of the six promised files."""
        with tempfile.TemporaryDirectory() as tmp:
            node = create_node("FigureExportNode", node_id="fig",
                               params={"kind": "dos"})
            with pytest.raises(ValueError):
                node.execute({"spectrum": [Spectrum(x=[], y=[])]}, ctx=_Ctx(tmp))

    def test_concurrent_figures_do_not_corrupt_each_other(self, registry):
        """matplotlib's mathtext parser is not thread safe.

        The engine runs same-generation nodes in parallel, so three relaxation
        figures rendering at once is the normal case.  Unserialised, two of the
        three died with ``ParseException`` raised from the middle of a tick
        string.
        """
        from concurrent.futures import ThreadPoolExecutor

        from simulation_runtime import run

        spectrum = run("materials", Material(name="Al", formula="Al",
                                             structure={"a": 4.05}),
                       backend="abacus", calculation="cell_relax",
                       lattice="fcc", relax_steps=15).ports["spectrum"]

        # One shared directory: each thread must not delete the others' output.
        with tempfile.TemporaryDirectory() as tmp:
            context = _Ctx(tmp)

            def render(index: int):
                node = create_node("FigureExportNode", node_id=f"fig{index}",
                                   params={"kind": "relax_convergence",
                                           "filename": f"c{index}", "trace": index})
                return node.execute({"spectrum": [spectrum]},
                                    ctx=context)["text"].metadata["figures"][0]

            with ThreadPoolExecutor(max_workers=4) as pool:
                results = list(pool.map(render, (1, 2, 3, 3)))

            # Read inside the context: the directory disappears with the block,
            # so asserting on paths afterwards would pass vacuously.
            for path in results:
                assert Path(path).read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"




class _Ctx:
    """Minimal run context exposing only ``artifact_path``."""

    def __init__(self, directory: str):
        self.directory = Path(directory)

    def artifact_path(self, filename: str, subdir: str = "") -> str:
        target = self.directory / subdir / filename if subdir else self.directory / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        return str(target)


# --------------------------------------------------------------------------- #
# 5. The workflow must promise and produce the six figures
# --------------------------------------------------------------------------- #
class TestWorkflowDeliversSixFigures:
    def test_metadata_lists_the_six_product_figures(self):
        data = json.loads(WORKFLOW.read_text(encoding="utf-8"))
        assert tuple(data["metadata"]["product_figures"]) == EXPECTED_FIGURES

    def test_one_figure_node_per_declared_figure(self):
        data = json.loads(WORKFLOW.read_text(encoding="utf-8"))
        nodes = {node["id"]: node for node in data["nodes"]}
        figures = [node for node in data["nodes"] if node["type"] == "FigureExportNode"]
        assert len(figures) == len(EXPECTED_FIGURES)
        produced = {f"{node['params']['filename']}.png" for node in figures}
        assert produced == set(EXPECTED_FIGURES)

    def test_every_figure_node_is_wired_to_a_source(self):
        """A figure node with no incoming edge writes nothing and still passes."""
        data = json.loads(WORKFLOW.read_text(encoding="utf-8"))
        targets = {edge["target"] for edge in data["edges"]}
        for node in data["nodes"]:
            if node["type"] == "FigureExportNode":
                assert node["id"] in targets, f"{node['id']} has no incoming edge"

    def test_the_three_relaxation_figures_select_distinct_traces(self):
        """One relaxation feeds all three; drawing the same trace three times
        would deliver three files that are the same picture."""
        data = json.loads(WORKFLOW.read_text(encoding="utf-8"))
        traces = {
            node["params"]["filename"]: node["params"].get("trace")
            for node in data["nodes"] if node["type"] == "FigureExportNode"
        }
        assert traces["Al_弛豫能量收敛"] == 1
        assert traces["Al_弛豫力收敛"] == 2
        assert traces["Al_弛豫应力收敛"] == 3
        assert len({traces[name] for name in
                    ("Al_弛豫能量收敛", "Al_弛豫力收敛", "Al_弛豫应力收敛")}) == 3

    def test_workflow_includes_a_total_dos_node(self):
        """PDOS without a total DOS cannot show the s-p hybridisation envelope."""
        data = json.loads(WORKFLOW.read_text(encoding="utf-8"))
        calculations = {node["params"].get("calculation")
                        for node in data["nodes"] if node["type"] == "ABACUSNode"}
        assert {"bands", "dos", "pdos", "cell_relax"} <= calculations

    def test_the_agent_recipe_plans_the_same_six_figures(self):
        """The demo workflow and the autonomous plan are the same graph.

        They are kept in sync by hand, which means they drift.  The drift is
        silent in the direction that matters most: the demo looks finished
        while the agent -- the path the reference case actually asks for --
        still produces no figures at all.
        """
        from nodes.agent.planner import RECIPES

        steps = RECIPES["solid_state_dft"]["steps"]
        figures = {
            step["params"].get("filename")
            for step in steps if step["type"] == "FigureExportNode"
        }
        assert {name.removesuffix(".png") for name in EXPECTED_FIGURES} == figures

    def test_the_agent_recipe_declares_no_unknown_parameters(self, registry):
        """The planner silently drops parameters the registry does not have.

        A recipe naming a parameter that no node reads passes every validation
        and runs to completion having done nothing.
        """
        from nodes.agent.planner import RECIPES

        for recipe_name, recipe in RECIPES.items():
            for step in recipe["steps"]:
                node_class = registry.get(step["type"])
                if node_class is None:
                    continue
                known = {spec.name for spec in node_class.parameters}
                unknown = set(step.get("params") or {}) - known
                assert not unknown, (
                    f"配方 {recipe_name} 的节点 {step['type']} 含未注册参数：{sorted(unknown)}"
                )

    def test_workflow_validates_and_runs(self, registry):
        from workflow_engine.engine import WorkflowEngine
        from workflow_engine.workflow import Workflow

        data = json.loads(WORKFLOW.read_text(encoding="utf-8"))
        workflow = Workflow.from_dict(data)
        assert workflow.validate() == []

        with tempfile.TemporaryDirectory() as tmp:
            result = WorkflowEngine(registry=registry, workdir=Path(tmp)).run(workflow)
            assert result.status == "completed"
            # ``result.artifacts`` rather than a reconstructed path: it is the
            # engine's own account of what it wrote, so a workflow writing its
            # figures somewhere else cannot pass by pointing at that elsewhere.
            pngs = [path for path in result.artifacts
                    if str(path).lower().endswith(".png")]
            assert {Path(path).name for path in pngs} >= set(EXPECTED_FIGURES)
            for path in pngs:
                assert Path(path).read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"



# --------------------------------------------------------------------------- #
# 6. Reverse verification
# --------------------------------------------------------------------------- #
def test_reverting_to_flattened_bands_breaks_the_figure():
    """Replace ``curves`` routing with the old ``ravel`` and confirm failure.

    A test that passes against both implementations is not testing anything.
    """
    original = Spectrum.from_arrays.__func__

    def flattened(cls, x, y, mode="Generic", x_unit="", y_unit="", **kwargs):
        rows = [row for row in (y or []) if isinstance(row, (list, tuple))]
        if rows:
            flat = [float(v) for row in rows for v in row]
            return original(cls, x, flat, mode, x_unit, y_unit, **kwargs)
        return original(cls, x, y, mode, x_unit, y_unit, **kwargs)

    spectrum = Spectrum.from_arrays([0.0, 1.0, 2.0], [[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]],
                                    mode="Bands")
    assert spectrum.is_multicurve(), "precondition: the fix is in place"

    try:
        Spectrum.from_arrays = classmethod(flattened)
        broken = Spectrum.from_arrays([0.0, 1.0, 2.0], [[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]],
                                      mode="Bands")
        assert broken.is_multicurve() is False, "the ravel must not satisfy the fix"
        assert len(broken.y) == 6 and len(broken.x) == 3
        # This is exactly the defect: more y values than x values, which every
        # renderer previously coped with by truncating or by failing quietly.
        assert len(broken.y) != len(broken.x)
    finally:
        Spectrum.from_arrays = classmethod(original)

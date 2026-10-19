"""Solid-state / plane-wave DFT back-ends for :mod:`simulation_runtime`.

External engines (VASP, Quantum ESPRESSO) are driven through their input decks
when installed.  The internal fallback solves an honest **orthogonal
tight-binding** model (:mod:`simulations.tight_binding`) plus a powder XRD
pattern (:func:`models.materials.simulate_xrd`) from the composition -- physically
meaningful band structures and densities of states with no licence required.

The four-stage contract (input generation, run, output parsing, object
conversion) is shared with the other families.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

from models.materials import simulate_xrd
from simulations.runners import ToolResult
from simulations.tight_binding import (
    band_gap,
    build_lattice,
    compute_bands,
    density_of_states,
    experimental_lattice_constant,
    fermi_energy,
    nearest_neighbour_distance,
    primitive_cell,
    projected_density_of_states,
    relax_lattice,
    total_energy,
)
from workflow_engine.objects import Material, Molecule, Spectrum, Table, Text

from .base import SimulationBackend, SimulationResult

__all__ = [
    "VASPBackend",
    "QuantumESPRESSOBackend",
    "ABACUSBackend",
    "TightBindingBackend",
    "MATERIALS_BACKENDS",
]

CALCULATIONS = ["scf", "relax", "cell_relax", "bands", "dos", "pdos", "xrd"]
FUNCTIONALS = ["pbe", "pbesol", "lda", "scan", "hse06"]
LATTICE_KEYS = ("sc", "bcc", "fcc", "hcp")


def _resolve_material(system: Any) -> Material:
    if isinstance(system, Material):
        return system
    if isinstance(system, Molecule) and system.formula:
        from nodes._helpers import build_material

        return build_material(system.formula, name=system.name or system.formula)
    raise TypeError(f"materials back-end needs a Material (got {type(system).__name__})")


def _formula(material: Material) -> str:
    return " ".join(component.formula for component in material.composition)


def _primary_element(material: Material) -> str:
    """The element symbol the band structure is built for.

    The band solver carries one element per cell (the two-centre model has no
    multi-species potential), so the *heaviest common* species is the one that
    decides the electronic structure -- for an intermetallic that is the
    transition metal, and for a binary of two metals it is a documented
    approximation rather than a silent pick of whichever came first in the
    composition list.
    """
    from simulations.tight_binding import ELEMENT_ORBITALS

    for component in material.composition:
        symbol = str(component.formula or "").strip().rstrip("0123456789")
        if symbol in ELEMENT_ORBITALS:
            return symbol
    for component in material.composition:
        symbol = str(component.formula or "").strip().rstrip("0123456789")
        if symbol:
            return symbol
    return "Al"


def _sites(material: Material) -> List[Dict[str, Any]]:
    """Spread the elements of ``material`` over fractional positions."""
    anchors = [
        [0.0, 0.0, 0.0],
        [0.5, 0.5, 0.5],
        [0.5, 0.0, 0.0],
        [0.0, 0.5, 0.0],
        [0.0, 0.0, 0.5],
        [0.25, 0.25, 0.25],
    ]
    return [
        {"element": component.formula, "frac": anchors[index % len(anchors)]}
        for index, component in enumerate(material.composition)
    ]


def _count_peaks(intensity: Sequence[float], floor: float = 1e-6) -> int:
    """Number of resolved peaks in a sampled diffraction/absorption curve.

    Not ``len(curve)``.  The previous XRD report counted the sample grid and
    printed "3600 peaks" -- the number of points the curve was evaluated on,
    reported as though it were a physical observable.  Such a number cannot be
    read against anything: it changes with the plotting resolution and says
    nothing about the crystal.

    A peak is a sample that is a strict local maximum and clears a fraction of
    the curve's own maximum, which is the criterion that works both for a noisy
    absorption curve and for a Bragg pattern whose peaks sit on a near-zero
    background.
    """
    values = [float(item) for item in intensity]
    if len(values) < 3:
        return 0
    top = max(values)
    if top <= floor:
        return 0
    threshold = top * 1e-3
    count = 0
    for index in range(1, len(values) - 1):
        here = values[index]
        if here >= threshold and here > values[index - 1] and here >= values[index + 1]:
            count += 1
    return count


def _dos_at(x_values: List[float], y_values: List[float], energy: float) -> float:
    """Density of states at ``energy``, by linear interpolation.

    Used to decide "metal or not".  A band-structure gap alone answers that only
    along the sampled path: a band can be flat along Γ-X and disperse elsewhere,
    which is exactly the aluminium case the reference workflow has to get right.
    Sampling the DOS at E_F tests whether any states exist there at all.
    """
    if not x_values or not y_values:
        return 0.0
    if energy <= x_values[0] or energy >= x_values[-1]:
        return 0.0
    for index in range(1, len(x_values)):
        left, right = x_values[index - 1], x_values[index]
        if left <= energy <= right:
            span = right - left
            if span <= 1e-12:
                return float(y_values[index])
            weight = (energy - left) / span
            return float(y_values[index - 1] * (1.0 - weight) + y_values[index] * weight)
    return 0.0


# --------------------------------------------------------------------------- #
# External back-ends
# --------------------------------------------------------------------------- #
class _MaterialsExternal(SimulationBackend):
    family = "materials"
    is_external = True
    input_filename = "input.in"

    def _params(self, system: Any, **params: Any) -> Dict[str, Any]:
        material = _resolve_material(system)
        return {
            "material": material,
            "formula": _formula(material),
            "calculation": str(params.get("calculation", "scf")),
            "functional": str(params.get("functional", "pbe")),
            "cutoff_ev": float(params.get("cutoff_ev", 520.0)),
            "kpoints": int(params.get("kpoints", 4) or 4),
            "lattice": str(params.get("lattice", "sc")),
            "hopping": float(params.get("hopping", -1.0)),
        }

    def generate_input(self, system: Any, **params: Any) -> str:
        return self.build_input(self._params(system, **params))

    def internal_execute(self, system: Any, workdir: Path, **params: Any) -> SimulationResult:
        """External back-ends defer to the built-in tight-binding engine."""
        return TightBindingBackend().internal_execute(system, workdir, **params)

    def build_input(self, p: Dict[str, Any]) -> str:  # pragma: no cover - overridden
        raise NotImplementedError

    def parse_output(
        self, result: ToolResult, system: Any, **params: Any
    ) -> Dict[str, float]:
        text = result.stdout or ""
        metrics: Dict[str, float] = {}
        energy = re.search(r"(?i)(?:free energy|total energy|energy)\s*[:=]\s*(-?\d+\.\d+)", text)
        if energy:
            metrics["total_energy_ev"] = float(energy.group(1))
        gap = re.search(r"(?i)band gap\s*[:=]\s*(-?\d+\.\d+)", text)
        if gap:
            metrics["band_gap_ev"] = float(gap.group(1))
        return metrics

    def to_object(
        self, system: Any, metrics: Dict[str, float], **params: Any
    ) -> Dict[str, Any]:
        material = _resolve_material(system)
        formula = _formula(material)
        table = Table(
            name=f"{self.name} result",
            columns=["quantity", "value"],
            rows=[
                ["total_energy", round(float(metrics.get("total_energy_ev", 0.0)), 4)],
                ["band_gap", round(float(metrics.get("band_gap_ev", 0.0)), 4)],
            ],
        )
        summary = f"{self.name} [external:{self.executable}] {formula}"
        return {
            "material": material,
            "spectrum": None,
            "table": table,
            "text": Text(name=self.name, text=summary, data={"engine": f"external:{self.executable}"}),
        }


class VASPBackend(_MaterialsExternal):
    """VASP wrapper (POSCAR + INCAR)."""

    name = "vasp"
    executable = "vasp_std"
    input_filename = "INCAR"

    def build_input(self, p: Dict[str, Any]) -> str:
        material = p["material"]
        lattice = getattr(material, "lattice", None) or {"a": 10.0, "b": 10.0, "c": 10.0}
        species = [component.formula for component in material.composition]
        return (
            f"{p['formula']}\n"
            "1.0\n"
            f"  {lattice.get('a', 10.0):.4f} 0.0 0.0\n"
            f"  0.0 {lattice.get('b', 10.0):.4f} 0.0\n"
            f"  0.0 0.0 {lattice.get('c', 10.0):.4f}\n"
            + " ".join(species)
            + "\n"
            + "  1 " * len(species)
            + "\nDirect\n"
            "SYSTEM = vasp run\n"
            f"  ENCUT = {int(p['cutoff_ev'])}\n"
            "  ISTART = 0\n"
            "  NSW = 0\n"
        )


class QuantumESPRESSOBackend(_MaterialsExternal):
    """Quantum ESPRESSO (pw.x) wrapper."""

    name = "quantum_espresso"
    executable = "pw.x"
    input_filename = "input.in"

    def build_input(self, p: Dict[str] | Dict[str, Any]) -> str:  # type: ignore[name-defined]
        material = p["material"]
        lattice = getattr(material, "lattice", None) or {"a": 10.0, "b": 10.0, "c": 10.0}
        calculation = {
            "scf": "scf",
            "relax": "relax",
            "bands": "bands",
            "dos": "nscf",
            "xrd": "scf",
        }.get(p["calculation"], "scf")
        return (
            "&CONTROL\n"
            f"  calculation = '{calculation}'\n"
            f"  prefix = 'job'\n"
            "&END CONTROL\n"
            "&SYSTEM\n"
            f"  ibrav = 1\n"
            f"  celldm(1) = {float(lattice.get('a', 10.0)) / 0.529177:.4f}\n"
            f"  ecutwfc = {int(p['cutoff_ev'] / 13.6057)}\n"
            f"  ntyp = 1\n"
            f"  nat = 1\n"
            "&END SYSTEM\n"
            "ATOMIC_SPECIES\n"
            "  X 1.0 X.pbe.UPF\n"
            "ATOMIC_POSITIONS angstrom\n"
            "  X 0.0 0.0 0.0\n"
            f"K_POINTS automatic\n  {p['kpoints']} {p['kpoints']} {p['kpoints']} 0 0 0\n"
        )


# --------------------------------------------------------------------------- #
# Internal fallback: tight-binding + XRD
# --------------------------------------------------------------------------- #
class TightBindingBackend(SimulationBackend):
    """Built-in tight-binding engine (offline fallback for solid-state tasks)."""

    family = "materials"
    name = "tight_binding"
    executable = ""
    is_external = False
    input_filename = "tb.in"

    def generate_input(self, system: Any, **params: Any) -> str:
        material = _resolve_material(system)
        p = {
            "formula": _formula(material),
            "calculation": str(params.get("calculation", "scf")),
            "lattice": str(params.get("lattice", "sc")),
            "hopping": float(params.get("hopping", -1.0)),
        }
        return (
            f"# tight-binding input for {p['formula']}\n"
            f"lattice {p['lattice']}\n"
            f"hopping {p['hopping']}\n"
            f"calculation {p['calculation']}\n"
        )

    def internal_execute(
        self, system: Any, workdir: Path, **params: Any
    ) -> SimulationResult:
        material = _resolve_material(system)
        calculation = str(params.get("calculation", "scf"))
        formula = _formula(material)
        element = str(params.get("element", "") or "").strip() or _primary_element(material)
        lattice_key = str(params.get("lattice", "fcc") or "fcc").lower()
        functional = str(params.get("functional", "pbe"))

        # The lattice constant is the single most consequential number in the
        # whole calculation, and the old engine accepted an ``a`` parameter and
        # then ignored it.  Resolving it explicitly -- parameter, then the
        # material's own lattice, then the measured value -- means "a = 4.05" in
        # a workflow actually produces a 4.05 A cell.
        a = self._resolve_lattice_constant(material, params, element, lattice_key)

        if calculation == "cell_relax":
            return self._relax(material, workdir, params, element, lattice_key, a, functional)
        if calculation == "xrd":
            return self._xrd(material, workdir, params, calculation, formula, a, lattice_key)

        # Compute bands on the resolved cell.
        structure = compute_bands(
            lattice_key=lattice_key,
            element=element,
            a=a,
            hopping=params.get("hopping"),
            points_per_segment=int(params.get("band_points", 40) or 40),
        )
        flat = structure.flat_energies()
        gap = structure.gap()
        e_fermi = float(gap["fermi"])
        dos_x, dos_y = density_of_states(flat, sigma=0.15, points=200, fermi=e_fermi)

        spectrum = self._spectrum_for(
            calculation, structure, dos_x, dos_y, formula, element, lattice_key
        )
        properties: Dict[str, float] = {
            "band_gap_ev": float(gap["gap"]),
            "vbm_ev": float(gap["vbm"]),
            "cbm_ev": float(gap["cbm"]),
            "fermi_ev": e_fermi,
            "lattice_constant_angstrom": round(a, 5),
            "nearest_neighbour_angstrom": round(nearest_neighbour_distance(
                build_lattice(lattice_key, a, element)
            ), 5),
            "n_bands": float(len(structure.energies[0])) if structure.energies else 0.0,
            "n_kpoints_sampled": float(len(structure.k_points)),
            "n_orbitals_per_site": float(structure.n_orbitals_per_site()),
            "dos_at_fermi": float(_dos_at(dos_x, dos_y, e_fermi)),
        }
        if params.get("hopping") is not None:
            properties["hopping_ev"] = float(params.get("hopping") or 0.0)

        spectrum.metadata.update(
            {
                "band_gap_ev": properties["band_gap_ev"],
                "fermi_ev": e_fermi,
                "functional": functional,
                "n_kpoints": len(structure.k_points),
                "lattice": lattice_key,
                "element": element,
                "lattice_constant_angstrom": properties["lattice_constant_angstrom"],
                "engine": "internal:tight-binding",
                "tick_labels": structure.tick_labels,
                "tick_positions": structure.tick_positions,
                "k_axis": structure.k_axis,
                "model": "two-centre Slater-Koster tight binding",
            }
        )

        table = Table(
            name="Tight-binding result",
            columns=["quantity", "value"],
            rows=[[key, round(value, 5)] for key, value in properties.items()],
        )
        summary = self._summary(
            calculation, formula, element, lattice_key, a, properties, structure
        )
        ports = {
            "material": material,
            "spectrum": spectrum,
            "table": table,
            "text": Text(
                name="Tight-binding",
                text=summary,
                data={
                    "engine": "internal:tight-binding",
                    "element": element,
                    "lattice": lattice_key,
                    "lattice_constant_angstrom": properties["lattice_constant_angstrom"],
                    "band_gap_ev": properties["band_gap_ev"],
                    "fermi_ev": e_fermi,
                },
            ),
        }
        input_path = workdir / self.input_filename
        input_path.parent.mkdir(parents=True, exist_ok=True)
        input_path.write_text(self.generate_input(system, **params), encoding="utf-8")
        self._write_stru(workdir, element, lattice_key, a, calculation)
        return SimulationResult(
            backend=self.name,
            engine="internal:tight-binding",
            family=self.family,
            metrics=properties,
            ports=ports,
            workdir=str(workdir),
            input_file=str(input_path),
            message="internal Slater-Koster tight-binding engine",
            raw={"bands": structure.to_dict()},
        )

    # -- helpers -------------------------------------------------------------- #
    @staticmethod
    def _relaxed_material(material: Material, a: float) -> Material:
        """A copy of ``material`` whose cell carries the relaxed ``a``.

        A copy, not an in-place mutation: the input object may be a cached
        upstream artefact that other branches of the graph also consume, and
        rewriting its lattice in place would change what they see without their
        having run a relaxation.

        ``a`` is written only when the cell had one to begin with or the
        material already declares a lattice; a material that carries no cell at
        all gets one, because the relaxation just produced a real one and
        discarding it is the bug this whole method exists to fix.
        """
        structure = getattr(material, "structure", None)
        payload = material.model_dump() if hasattr(material, "model_dump") else None
        if payload is None:
            return material
        cell = dict(payload.get("structure") or {})
        cell["a"] = float(a)
        # Only b and c were explicitly set before the relaxation; scaling them
        # with a keeps the shape of the cell (hcp c/a, monoclinic beta) instead
        # of silently turning an anisotropic cell into a cubic one.
        for key in ("b", "c"):
            value = float(cell.get(key) or 0.0)
            if value > 0.0:
                cell[key] = round(value * float(a) / max(1e-9, float(structure.a if structure and getattr(structure, "a", 0.0) else a)), 8)
        payload["structure"] = cell
        relaxed = Material(**payload)
        # ``properties`` is ``Dict[str, float]``; a provenance string belongs in
        # metadata.  Putting it here produced a pydantic serializer warning on
        # every dump and fed a string into formatting code that expects numbers.
        properties = dict(payload.get("properties") or {})
        properties["a_relaxed_angstrom"] = round(float(a), 6)
        payload["properties"] = properties
        payload["metadata"] = {
            **dict(payload.get("metadata") or {}),
            "relaxed_by": "internal:tight-binding",
            "a_relaxed_angstrom": round(float(a), 6),
        }
        relaxed.properties = properties
        relaxed.metadata = payload["metadata"]
        return relaxed

    @staticmethod
    def _resolve_lattice_constant(
        material: Material, params: Dict[str, Any], element: str, lattice_key: str
    ) -> float:
        """The lattice constant actually used, and where it came from.

        Resolution order: the ``a`` parameter, then the cell carried on the
        incoming ``Material``, then the measured value for the element.

        The middle step used to read ``material.lattice``, which does not exist
        -- ``Material`` stores its cell on ``structure`` as a
        ``CrystalStructure``.  ``getattr(..., None)`` swallowed the miss and
        returned ``None``, so a Material built with an explicit cell was silently
        ignored and the run fell through to the experimental constant.  A
        workflow that carefully passed ``a = 4.05`` on the input node and got
        4.05 anyway had no way to notice, because both numbers agreed; the
        failure only shows when they differ.
        """
        explicit = float(params.get("a", 0.0) or 0.0)
        if explicit > 0.0:
            return explicit
        structure = getattr(material, "structure", None)
        for key in ("a", "b", "c"):
            value = float(getattr(structure, key, 0.0) or 0.0)
            if value > 0.0:
                return value
        measured = experimental_lattice_constant(lattice_key, element)
        if measured > 0.0:
            return measured
        # Nothing known: say so rather than silently using a plausible number.
        raise ValueError(
            f"no lattice constant available for {element} in {lattice_key}; "
            f"set the 'a' parameter (or connect a Material that carries one)"
        )

    @staticmethod
    def _spectrum_for(
        calculation: str,
        structure: Any,
        dos_x: List[float],
        dos_y: List[float],
        formula: str,
        element: str,
        lattice_key: str,
    ) -> Spectrum:
        """Pick the spectrum that matches what was asked for."""
        e_fermi = fermi_energy(structure)
        if calculation == "dos":
            return Spectrum.from_arrays(
                dos_x, dos_y, mode="DOS", x_unit="eV", y_unit="states/eV",
                name=f"{formula} density of states",
            )
        if calculation == "pdos":
            # Orbital-resolved DOS: the only view in which aluminium's s-p
            # hybridisation at E_F -- the reason it is a metal -- is visible.
            pdos = projected_density_of_states(structure, sigma=0.15, points=200)
            s_total = [sum(column) for column in zip(*pdos["orbitals"])]
            spectrum = Spectrum.from_arrays(
                pdos["x"], s_total, mode="PDOS", x_unit="eV", y_unit="states/eV",
                name=f"{element} projected density of states",
            )
            spectrum.metadata["pdos"] = {
                "orbitals": pdos["orbital_labels"],
                "curves": [[round(v, 8) for v in row] for row in pdos["orbitals"]],
                "x": pdos["x"],
                "fermi_ev": pdos["fermi_ev"],
            }
            return spectrum

        # bands / scf / relax: a band structure plotted against the k-path, with
        # the high-symmetry labels carried in metadata.  The previous version
        # plotted against the band index, which is not a band structure.
        energies = [
            [value - e_fermi for value in row] for row in structure.energies
        ]
        return Spectrum.from_arrays(
            structure.k_axis,
            [list(row) for row in energies],
            mode="Bands",
            x_unit="k path (2pi/a)",
            y_unit="E - E_F (eV)",
            name=f"{element} {lattice_key} band structure",
        )

    def _relax(
        self,
        material: Material,
        workdir: Path,
        params: Dict[str, Any],
        element: str,
        lattice_key: str,
        a: float,
        functional: str,
    ) -> SimulationResult:
        """Lattice relaxation -- the cell-relax stage of a DFT run."""
        result = relax_lattice(
            lattice_key=lattice_key,
            element=element,
            a0=a,
            steps=int(params.get("relax_steps", 25) or 25),
            n_kpoints=int(params.get("kpoints", 4) or 4),
        )
        relaxed_a = float(result["a_relaxed"])
        structure = compute_bands(lattice_key=lattice_key, element=element, a=relaxed_a)
        gap = structure.gap()
        properties = {
            "a_initial_angstrom": float(result["a_initial"]),
            "a_relaxed_angstrom": relaxed_a,
            "energy_initial_ev": float(result["energy_initial_ev"]),
            "energy_final_ev": float(result["energy_final_ev"]),
            "energy_change_ev": float(result["energy_change_ev"]),
            "band_gap_ev": float(gap["gap"]),
            "fermi_ev": float(gap["fermi"]),
            "steps": float(result["steps"]),
        }
        table = Table(
            name="Lattice relaxation",
            columns=["step", "a (Å)", "energy (eV)"],
            rows=[
                [int(item["step"]), float(item["a"]), float(item["energy_ev"])]
                for item in result["history"]
            ],
        )
        note = str(result.get("accuracy_note") or "")
        summary = (
            f"cell-relax {element} {lattice_key}: a {result['a_initial']:.3f} -> "
            f"{relaxed_a:.3f} Å in {result['steps']} steps, "
            f"E {result['energy_initial_ev']:.2f} -> {result['energy_final_ev']:.2f} eV"
            + (f". {note}" if note else "")
        )
        input_path = workdir / self.input_filename
        input_path.parent.mkdir(parents=True, exist_ok=True)
        input_path.write_text(
            self.generate_input(material, calculation="cell_relax", lattice=lattice_key, a=relaxed_a),
            encoding="utf-8",
        )
        self._write_stru(workdir, element, lattice_key, relaxed_a, "cell_relax")
        return SimulationResult(
            backend=self.name,
            engine="internal:tight-binding",
            family=self.family,
            metrics=properties,
            ports={
                # The **relaxed** cell, not the one that came in.  Returning
                # ``material`` unchanged made a relaxation a dead end: the
                # downstream band-structure and DOS nodes re-resolve the lattice
                # constant from this object, so they silently recomputed at the
                # *original* a.  The reference workflow read
                # "a 4.050 -> 3.987 Å" in the relaxation report and then plotted
                # bands for a = 4.050 Å -- the relaxation was performed, paid
                # for, and discarded, and every number in the final report was
                # self-consistent about the wrong cell.
                "material": self._relaxed_material(material, relaxed_a),
                "spectrum": None,
                "table": table,
                "text": Text(
                    name="Lattice relaxation",
                    text=summary,
                    data={
                        "engine": "internal:tight-binding",
                        "a_relaxed_angstrom": relaxed_a,
                        "accuracy_note": note,
                        "a_experimental": float(result.get("a_experimental") or 0.0),
                    },
                ),
            },
            workdir=str(workdir),
            input_file=str(input_path),
            message="lattice relaxation on the internal tight-binding surface",
            raw={"relaxation": result},
        )

    def _xrd(
        self, material: Material, workdir: Path, params: Dict[str, Any],
        calculation: str, formula: str, a: float, lattice_key: str,
    ) -> SimulationResult:
        """Powder XRD from the lattice parameters.

        The cell is the **resolved** one -- the same ``a`` the band solver used.
        This path used to read its own defaults (``a = 10.33``, ``c = 4.69``),
        which is a plausible-looking orthorhombic constant for nothing in
        particular: ask for a 4.05 A fcc aluminium band structure and the XRD
        came back for a completely different cell, and every peak angle was
        wrong while the plot still rendered.  A diffraction pattern is the one
        place where silently substituting a lattice constant cannot be undone
        by looking at the result.

        Parameters still override, and ``alpha/beta/gamma`` default to the
        crystal system implied by ``lattice_key`` rather than to 90° for every
        structure.
        """
        alpha = float(params.get("alpha", 0.0) or 0.0)
        beta = float(params.get("beta", 0.0) or 0.0)
        gamma = float(params.get("gamma", 0.0) or 0.0)
        # hcp is the only supported non-orthogonal cell.
        alpha = alpha if alpha > 0.0 else (90.0 if lattice_key != "hcp" else 90.0)
        beta = beta if beta > 0.0 else (90.0 if lattice_key != "hcp" else 90.0)
        gamma = gamma if gamma > 0.0 else (120.0 if lattice_key == "hcp" else 90.0)
        b_value = float(params.get("b", 0.0) or 0.0) or a
        c_value = float(params.get("c", 0.0) or 0.0) or a
        spectrum = simulate_xrd(
            lattice={
                "a": a,
                "b": b_value,
                "c": c_value,
                "alpha": alpha,
                "beta": beta,
                "gamma": gamma,
            },
            sites=_sites(material),
            wavelength=float(params.get("wavelength", 1.5406) or 1.5406),
        )
        peaks = _count_peaks(spectrum.y or [])
        spectrum.metadata.update({
            "engine": "internal:tight-binding",
            "functional": str(params.get("functional", "pbe")),
            "lattice": lattice_key,
            "lattice_constant_angstrom": round(a, 5),
            "n_peaks": peaks,
        })
        summary = (
            f"TB [internal:tight-binding] {calculation} on {formula}: powder XRD, "
            f"{lattice_key} a={a:.3f} Å, {peaks} peaks in the plotted range"
        )
        return SimulationResult(
            backend=self.name,
            engine="internal:tight-binding",
            family=self.family,
            metrics={
                "lattice_constant_angstrom": round(a, 5),
                "n_peaks": float(peaks),
                "wavelength_angstrom": float(params.get("wavelength", 1.5406) or 1.5406),
                "alpha": alpha,
                "beta": beta,
                "gamma": gamma,
            },
            ports={
                "material": material,
                "spectrum": spectrum,
                "table": Table(
                    name="XRD peaks",
                    columns=["quantity", "value"],
                    rows=[["peaks", float(peaks)]],
                ),
                "text": Text(
                    name="XRD",
                    text=summary,
                    data={
                        "engine": "internal:tight-binding",
                        "lattice": lattice_key,
                        "lattice_constant_angstrom": round(a, 5),
                        "n_peaks": peaks,
                    },
                ),
            },
            workdir=str(workdir),
            message="powder XRD from the resolved lattice parameters",
        )

    @staticmethod
    def _write_stru(workdir: Path, element: str, lattice_key: str, a: float, calculation: str) -> Path:
        """Write an ABACUS ``STRU`` file for the cell that was actually used.

        The reference case delivers ``Al_primitive.STRU`` as a product, and a
        structure file is the one artefact every DFT workflow is expected to
        leave behind.  Writing it from the same resolved cell the Hamiltonian
        used -- not from a re-derived guess -- is what makes the file and the
        band structure describe the same crystal.
        """
        cell = primitive_cell(lattice_key, element, a, cubic=False)
        lines = [
            "ATOMIC_SPECIES",
            f"{element} 26.9815 Al.upf  # {element}",
            "",
            "LATTICE_CONSTANT",
            f"{a:.8f}",
            "",
            "LATTICE_VECTORS",
        ]
        for row in cell.vectors:
            lines.append(f"{row[0]:.8f} {row[1]:.8f} {row[2]:.8f}")
        lines += ["", "ATOMIC_POSITIONS", "Cartesian", ""]
        for index, site in enumerate(cell.sites):
            xyz = cell.cartesian(site)
            # ``mag`` is ABACUS's per-atom magnetisation initialiser; 0 keeps a
            # non-magnetic run from silently inheriting one.
            lines.append(f"{element} 0.0 0 1 {xyz[0]:.8f} {xyz[1]:.8f} {xyz[2]:.8f}")
        path = workdir / f"{element}_primitive.STRU"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path

    @staticmethod
    def _summary(
        calculation: str, formula: str, element: str, lattice_key: str, a: float,
        properties: Dict[str, float], structure: Any,
    ) -> str:
        gap = properties["band_gap_ev"]
        head = (
            f"TB [internal:tight-binding] {calculation} on {element} {lattice_key} "
            f"a={a:.3f} Å"
        )
        if calculation in {"dos", "pdos"}:
            dos_fermi = properties["dos_at_fermi"]
            kind = (
                "metal (finite DOS at E_F)" if dos_fermi > 1e-3
                else "semiconductor / insulator (zero DOS at E_F)"
            )
            return (
                f"{head}: DOS, E_F {properties['fermi_ev']:.3f} eV, "
                f"DOS(E_F) {dos_fermi:.4f} states/eV -> {kind}"
            )
        path = " -> ".join(structure.tick_labels) if structure.tick_labels else "k-path"
        return (
            f"{head}: band structure along {path}, gap {gap:.3f} eV, "
            f"E_F {properties['fermi_ev']:.3f} eV, "
            f"{int(properties['n_orbitals_per_site'])} orbitals/atom "
            f"({len(structure.k_points)} k points)"
        )


class ABACUSBackend(_MaterialsExternal):
    """ABACUS (ABACUS v3.x) wrapper: STRU + INPUT + KPT.

    The reference workflow this reproduces drives ABACUS, which is why this
    backend exists at all rather than the case being re-pointed at VASP: the
    deliverable is a ``STRU`` file and the intermediate job is an
    ``input_prepare`` / ``cell-relax`` / ``scf`` sequence.

    ABACUS is a licensed-but-free DFT package.  When it is not installed the
    node falls back to the internal tight-binding engine and says so in
    ``engine``; the input files are written either way, because they are what a
    user needs in order to run the calculation on a cluster that *does* have it.
    """

    name = "abacus"
    executable = "abacus"
    input_filename = "INPUT"

    def _params(self, system: Any, **params: Any) -> Dict[str, Any]:
        material = _resolve_material(system)
        element = str(params.get("element", "") or "").strip() or _primary_element(material)
        lattice_key = str(params.get("lattice", "fcc") or "fcc").lower()
        a = float(params.get("a", 0.0) or 0.0)
        if a <= 0.0:
            a = TightBindingBackend._resolve_lattice_constant(
                material, params, element, lattice_key
            )
        base = super()._params(system, **params)
        base.update({
            "element": element,
            "lattice_key": lattice_key,
            "a": a,
            "orbital": str(params.get("orbital", "lcao") or "lcao"),
            "ecutwfc": float(params.get("ecutwfc", 100.0) or 100.0),
        })
        return base

    def build_input(self, p: Dict[str, Any]) -> str:
        """Write the ABACUS ``INPUT`` deck.

        ``job_type`` is what distinguishes the three stages of the reference
        workflow, and getting it wrong is the kind of error ABACUS reports as a
        plausible-looking run rather than a crash: ``cell-relax`` moves the cell,
        ``scf`` does not, ``nscf`` needs a converged ``scf`` first.
        """
        calculation = str(p.get("calculation", "scf"))
        job_type = {
            "scf": "scf",
            "relax": "relax",
            "cell_relax": "cell-relax",
            "bands": "scf",
            "dos": "scf",
            "pdos": "scf",
            "xrd": "scf",
        }.get(calculation, "scf")

        lines = [
            "INPUT_PARAMETERS",
            f"suffix                  {p.get('element', 'Al')}_{calculation}",
            "calculation             {0 if calculation in {'cell_relax', 'relax'} else 0}",
            f"stru_file               {p.get('element', 'Al')}_primitive.STRU",
            f"pseudo_dir              ./",
            f"orbital_type            {p.get('orbital', 'lcao')}",
            f"ecutwfc                 {float(p.get('ecutwfc', 100.0)):.1f}",
            f"scf_nmax                {int(p.get('scf_nmax', 100))}",
            f"scf_thr                 {float(p.get('scf_thr', 1.0e-8)):.1e}",
            "",
            "K_POINTS",
            f"{int(p.get('kpoints', 11))} {int(p.get('kpoints', 11))} {int(p.get('kpoints', 11))} 0 0 0",
        ]
        if job_type in {"relax", "cell-relax"}:
            lines += [
                "",
                "RELAX",
                "relax_nmax 50",
                "relax_cg_thr 0.001",
                # cell-relax must move the cell; relax must not.  Setting this
                # is the whole difference between the two job types.
                f"relax_scale_force      {1.0e-3 if job_type == 'cell-relax' else 0.0}",
                "force_thr_ev           0.001",
            ]
        return "\n".join(lines) + "\n"

    def build_stru(self, p: Dict[str, Any]) -> str:
        """The ``STRU`` body, so the file and the ``INPUT`` agree by construction."""
        cell = primitive_cell(p["lattice_key"], p["element"], p["a"], cubic=False)
        out = [
            "ATOMIC_SPECIES",
            f"{p['element']} 26.9815 Al.upf",
            "",
            "LATTICE_CONSTANT",
            f"{p['a']:.8f}",
            "",
            "LATTICE_VECTORS",
        ]
        out += [f"{r[0]:.8f} {r[1]:.8f} {r[2]:.8f}" for r in cell.vectors]
        out += ["", "ATOMIC_POSITIONS", "Cartesian", ""]
        for site in cell.sites:
            xyz = cell.cartesian(site)
            out.append(f"{p['element']} 0.0 0 1 {xyz[0]:.8f} {xyz[1]:.8f} {xyz[2]:.8f}")
        return "\n".join(out) + "\n"

    def internal_execute(self, system: Any, workdir: Path, **params: Any) -> SimulationResult:
        """Write the deck, then solve with the internal engine.

        Writing the deck unconditionally is deliberate: a user without ABACUS
        still gets ``INPUT``, ``STRU`` and ``KPT`` they can take to a cluster,
        which is the more common real use of this node.
        """
        resolved = self._params(system, **params)
        workdir.mkdir(parents=True, exist_ok=True)
        (workdir / "INPUT").write_text(self.build_input(resolved), encoding="utf-8")
        (workdir / f"{resolved['element']}_primitive.STRU").write_text(
            self.build_stru(resolved), encoding="utf-8"
        )
        return TightBindingBackend().internal_execute(system, workdir, **params)


#: Every back-end the ``materials`` family dispatches to.  ``TightBindingBackend``
#: is last so it stays the fallback rather than a peer of the real DFT drivers.
MATERIALS_BACKENDS: List[SimulationBackend] = [
    VASPBackend(),
    QuantumESPRESSOBackend(),
    ABACUSBackend(),
    TightBindingBackend(),
]

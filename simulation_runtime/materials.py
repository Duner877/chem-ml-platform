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
from simulations.tight_binding import band_gap, compute_bands, density_of_states
from workflow_engine.objects import Material, Molecule, Spectrum, Table, Text

from .base import SimulationBackend, SimulationResult

__all__ = [
    "VASPBackend",
    "QuantumESPRESSOBackend",
    "TightBindingBackend",
    "MATERIALS_BACKENDS",
]

CALCULATIONS = ["scf", "relax", "bands", "dos", "xrd"]
FUNCTIONALS = ["pbe", "pbesol", "lda", "scan", "hse06"]
LATTICE_KEYS = ("sc", "bcc", "fcc")


def _resolve_material(system: Any) -> Material:
    if isinstance(system, Material):
        return system
    if isinstance(system, Molecule) and system.formula:
        from nodes._helpers import build_material

        return build_material(system.formula, name=system.name or system.formula)
    raise TypeError(f"materials back-end needs a Material (got {type(system).__name__})")


def _formula(material: Material) -> str:
    return " ".join(component.formula for component in material.composition)


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

        bands = compute_bands(
            lattice_key=str(params.get("lattice", "sc")),
            hopping=float(params.get("hopping", -1.0)),
        )
        flat = bands.flat_energies()
        dos_x, dos_y = density_of_states(flat, sigma=0.15, points=200)
        gap = band_gap(flat)

        if calculation == "dos":
            spectrum = Spectrum.from_arrays(
                dos_x, dos_y, mode="DOS", x_unit="eV", y_unit="a.u.",
                name=f"{formula} density of states",
            )
        elif calculation == "xrd":
            spectrum = simulate_xrd(
                lattice={
                    "a": float(params.get("a", 10.33) or 10.33),
                    "b": float(params.get("b", 6.01) or 6.01),
                    "c": float(params.get("c", 4.69) or 4.69),
                    "alpha": float(params.get("alpha", 90.0) or 90.0),
                    "beta": float(params.get("beta", 90.0) or 90.0),
                    "gamma": float(params.get("gamma", 90.0) or 90.0),
                },
                sites=_sites(material),
                wavelength=float(params.get("wavelength", 1.5406) or 1.5406),
            )
        else:
            spectrum = Spectrum.from_arrays(
                list(range(len(flat))), flat, mode="Bands", x_unit="band index",
                y_unit="eV", name=f"{formula} band energies",
            )
        spectrum.metadata.update(
            {
                "band_gap_ev": gap.get("gap", 0.0),
                "fermi_ev": gap.get("fermi", 0.0),
                "functional": str(params.get("functional", "pbe")),
                "n_kpoints": len(bands.k_points) if bands.k_points else 0,
            }
        )

        properties = {
            "band_gap_ev": float(gap.get("gap", 0.0)),
            "vbm_ev": float(gap.get("vbm", 0.0)),
            "cbm_ev": float(gap.get("cbm", 0.0)),
            "fermi_ev": float(gap.get("fermi", 0.0)),
            "hopping_ev": float(params.get("hopping", -1.0)),
        }

        table = Table(
            name="Tight-binding result",
            columns=["quantity", "value"],
            rows=[[key, round(value, 5)] for key, value in properties.items()],
        )
        summary = (
            f"TB [internal:tight-binding] {calculation} on {formula}: "
            f"band gap {properties['band_gap_ev']:.3f} eV"
        )
        ports = {
            "material": material,
            "spectrum": spectrum,
            "table": table,
            "text": Text(name="Tight-binding", text=summary, data={"engine": "internal:tight-binding"}),
        }
        input_path = workdir / self.input_filename
        input_path.parent.mkdir(parents=True, exist_ok=True)
        input_path.write_text(self.generate_input(system, **params), encoding="utf-8")
        return SimulationResult(
            backend=self.name,
            engine="internal:tight-binding",
            family=self.family,
            metrics=properties,
            ports=ports,
            workdir=str(workdir),
            input_file=str(input_path),
            message="internal tight-binding engine",
            raw={"bands": bands.to_dict()},
        )


MATERIALS_BACKENDS: List[SimulationBackend] = [
    VASPBackend(),
    QuantumESPRESSOBackend(),
    TightBindingBackend(),
]

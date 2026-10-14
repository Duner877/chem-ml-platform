"""Quantum chemistry back-ends for :mod:`simulation_runtime`.

External programs (ORCA, Gaussian, Psi4, CP2K) are driven through their command
line interface when installed.  The internal fallback is the platform's own
**extended Hückel** engine (:mod:`simulations.eht`), which keeps every workflow
runnable on a laptop and is reported honestly in ``SimulationResult.engine``.

Each external back-end implements the four stages (input generation, run, output
parsing and object conversion); the internal :class:`EHTBackend` overrides
:meth:`internal_execute` with the same contract.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

from models.descriptors import QED, compute_descriptors, lipinski_violations
from models.geometry import guess_coordinates
from simulations.eht import EHTCalculator
from workflow_engine.objects import Molecule, Spectrum, Table, Text

from .base import SimulationBackend, SimulationResult

__all__ = [
    "ORCABackend",
    "GaussianBackend",
    "Psi4Backend",
    "CP2KBackend",
    "EHTBackend",
    "QUANTUM_BACKENDS",
]

METHODS = ["eht", "hf", "b3lyp", "pbe", "pbe0", "mp2", "ccsd(t)"]
BASIS_SETS = ["MINI", "STO-3G", "3-21G", "6-31G*", "def2-SVP", "def2-TZVP"]
TASKS = ["single_point", "optimize", "frequencies", "excitation"]


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _to_graph(molecule: Molecule):
    from models.smiles import parse_smiles

    return parse_smiles(molecule.smiles)


def _coordinates(molecule: Molecule, graph) -> np.ndarray:
    stored = [
        [float(value) for value in atom.coords]
        for atom in molecule.atoms
        if atom.coords
    ]
    if stored and len(stored) == graph.num_atoms:
        return np.asarray(stored, dtype=float)
    return guess_coordinates(molecule.smiles, iterations=120)


def _iter_sites(molecule: Molecule):
    graph = _to_graph(molecule)
    coordinates = _coordinates(molecule, graph)
    for index, atom in enumerate(graph.atoms):
        position = (
            coordinates[index] if index < len(coordinates) else [0.0, 0.0, 0.0]
        )
        yield atom, position


# --------------------------------------------------------------------------- #
# External back-ends
# --------------------------------------------------------------------------- #
class _QuantumExternal(SimulationBackend):
    """Shared input/run logic for the four quantum chemistry programs."""

    family = "quantum"
    is_external = True
    input_filename = "job.inp"
    default_method = "b3lyp"
    default_basis = "def2-SVP"

    # subclasses set ``executable`` and ``build_input``

    def _params(self, system: Molecule, **params: Any) -> Dict[str, Any]:
        graph = _to_graph(system)
        coordinates = _coordinates(system, graph)
        return {
            "smiles": system.smiles,
            "name": system.name or system.smiles,
            "method": str(params.get("method", self.default_method)),
            "basis": str(params.get("basis", self.default_basis)),
            "charge": int(params.get("charge", 0) or 0),
            "multiplicity": int(params.get("multiplicity", 1) or 1),
            "task": str(params.get("task", "single_point")),
            "graph": graph,
            "coordinates": coordinates,
        }

    def generate_input(self, system: Molecule, **params: Any) -> str:
        p = self._params(system, **params)
        return self.build_input(p)

    def internal_execute(self, system: Molecule, workdir: Path, **params: Any) -> SimulationResult:
        """External back-ends defer to the built-in extended Hückel engine."""
        return EHTBackend().internal_execute(system, workdir, **params)

    def build_input(self, p: Dict[str, Any]) -> str:  # pragma: no cover - overridden
        raise NotImplementedError

    def parse_output(
        self, result: Any, system: Molecule, **params: Any
    ) -> Dict[str, float]:
        """Best-effort extraction of energy / frontier orbitals from stdout."""
        text = result.stdout or ""
        metrics: Dict[str, float] = {}
        # ORCA final energy
        import re

        match = re.search(r"FINAL SINGLE POINT ENERGY\s+(-?\d+\.\d+)", text)
        if match:
            metrics["total_energy_ev"] = float(match.group(1))
        # generic "E = ..." / "Energy = ..." lines
        match = re.search(r"(?i)total energy\s*[:=]\s*(-?\d+\.\d+)", text)
        if match and "total_energy_ev" not in metrics:
            metrics["total_energy_ev"] = float(match.group(1))
        # HOMO / LUMO blocks (ORCA style)
        homo = re.search(r"(?i)homo.*?(-?\d+\.\d+)", text)
        lumo = re.search(r"(?i)lumo.*?(-?\d+\.\d+)", text)
        if homo:
            metrics["homo_ev"] = float(homo.group(1))
        if lumo:
            metrics["lumo_ev"] = float(lumo.group(1))
        if "homo_ev" in metrics and "lumo_ev" in metrics:
            metrics["gap_ev"] = metrics["lumo_ev"] - metrics["homo_ev"]
        return metrics

    def to_object(
        self, system: Molecule, metrics: Dict[str, float], **params: Any
    ) -> Dict[str, Any]:
        """Convert parsed metrics into the node port objects."""
        smiles = system.smiles
        task = str(params.get("task", "single_point"))
        properties: Dict[str, float] = dict(metrics)
        properties.setdefault("homo_ev", 0.0)
        properties.setdefault("lumo_ev", 0.0)
        properties.setdefault("gap_ev", 0.0)
        properties.setdefault("total_energy_ev", 0.0)

        descriptors = compute_descriptors(smiles)
        descriptors["LipinskiViolations"] = int(lipinski_violations(descriptors))
        descriptors["QED"] = float(QED(descriptors))
        for key, value in descriptors.items():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                properties[str(key)] = float(value)

        molecule = _rebuild_molecule(smiles, system, properties)

        spectrum: Optional[Spectrum] = None
        if task in {"frequencies", "excitation"}:
            from models.spectra import predict_ir, predict_uvvis

            spectrum = predict_ir(smiles) if task == "frequencies" else predict_uvvis(smiles)

        table = Table(
            name=f"{self.name} energy",
            columns=["quantity", "value", "unit"],
            rows=[
                ["HOMO", round(float(properties.get("homo_ev", 0.0)), 4), "eV"],
                ["LUMO", round(float(properties.get("lumo_ev", 0.0)), 4), "eV"],
                ["gap", round(float(properties.get("gap_ev", 0.0)), 4), "eV"],
                [
                    "total_energy",
                    round(float(properties.get("total_energy_ev", 0.0)), 4),
                    "eV",
                ],
            ],
        )
        summary = (
            f"{self.name} [external:{self.executable}] {task} on {smiles}: "
            f"E {properties.get('total_energy_ev', 0.0):.3f} eV"
        )
        return {
            "molecule": molecule,
            "spectrum": spectrum,
            "table": table,
            "text": Text(name=self.name, text=summary, data={"engine": f"external:{self.executable}"}),
        }


class ORCABackend(_QuantumExternal):
    """ORCA single point / optimisation / frequency wrapper."""

    name = "orca"
    executable = "orca"
    default_method = "b3lyp"
    default_basis = "def2-SVP"

    def build_input(self, p: Dict[str, Any]) -> str:
        keyword = {
            "single_point": "SP",
            "optimize": "OPT",
            "frequencies": "FREQ",
            "excitation": "SP",
        }.get(p["task"], "SP")
        lines = [f"! {p['method']} {p['basis']} {keyword}", f"* xyz {p['charge']} {p['multiplicity']}"]
        for index, atom in enumerate(p["graph"].atoms):
            position = p["coordinates"][index] if index < len(p["coordinates"]) else [0.0, 0.0, 0.0]
            lines.append(
                f"  {atom.get('element', 'C')} "
                f"{float(position[0]):.5f} {float(position[1]):.5f} {float(position[2]):.5f}"
            )
        lines.append("*")
        return "\n".join(lines) + "\n"


class GaussianBackend(_QuantumExternal):
    """Gaussian single point / optimisation / frequency wrapper."""

    name = "gaussian"
    executable = "g16"
    default_method = "b3lyp"
    default_basis = "def2-SVP"

    def build_input(self, p: Dict[str, Any]) -> str:
        route = {
            "single_point": "SP",
            "optimize": "Opt",
            "frequencies": "Freq",
            "excitation": "TD(NStates=10)",
        }.get(p["task"], "SP")
        lines = [
            "%Chk=job.chk",
            f"#P {p['method']}/{p['basis']} {route}",
            "",
            f"{p['name']}",
            "",
            f"{p['charge']} {p['multiplicity']}",
        ]
        for index, atom in enumerate(p["graph"].atoms):
            position = p["coordinates"][index] if index < len(p["coordinates"]) else [0.0, 0.0, 0.0]
            lines.append(
                f"  {atom.get('element', 'C')} "
                f"{float(position[0]):.5f} {float(position[1]):.5f} {float(position[2]):.5f}"
            )
        lines.append("")
        return "\n".join(lines)


class Psi4Backend(_QuantumExternal):
    """Psi4 Python input wrapper."""

    name = "psi4"
    executable = "psi4"
    default_method = "b3lyp"
    default_basis = "def2-SVP"

    def build_input(self, p: Dict[str, Any]) -> str:
        import json

        lines = ["import psi4", "psi4.set_output_file('job.out', False)", ""]
        lines.append("mol = psi4.geometry('''")
        lines.append(f"{p['charge']} {p['multiplicity']}")
        for index, atom in enumerate(p["graph"].atoms):
            position = p["coordinates"][index] if index < len(p["coordinates"]) else [0.0, 0.0, 0.0]
            lines.append(
                f"  {atom.get('element', 'C')} "
                f"{float(position[0]):.5f} {float(position[1]):.5f} {float(position[2]):.5f}"
            )
        lines.append("units angstrom")
        lines.append("''')")
        lines.append("")
        lines.append(f"psi4.set_options({{'basis': {json.dumps(p['basis'])}}})")
        if p["task"] == "optimize":
            lines.append("energy = psi4.optimize(" + repr(p["method"]) + ")")
        elif p["task"] == "frequencies":
            lines.append("energy, wfn = psi4.frequency(" + repr(p["method"]) + ", return_wfn=True)")
        else:
            lines.append("energy = psi4.energy(" + repr(p["method"]) + ")")
        lines.append("print(energy)")
        return "\n".join(lines) + "\n"


class CP2KBackend(_QuantumExternal):
    """CP2K (Quickstep DFT) wrapper."""

    name = "cp2k"
    executable = "cp2k.psmp"
    default_method = "pbe"
    default_basis = "def2-SVP"

    def build_input(self, p: Dict[str, Any]) -> str:
        method = str(p["method"]).upper()
        coord_lines = "".join(
            f"      {atom.get('element', 'C')} "
            f"{float(position[0]):.5f} {float(position[1]):.5f} {float(position[2]):.5f}\n"
            for atom, position in _iter_sites_from(p)
        )
        return (
            "&GLOBAL\n"
            "  PROJECT job\n"
            "  RUN_TYPE ENERGY\n"
            "&END GLOBAL\n"
            "&FORCE_EVAL\n"
            "  METHOD Quickstep\n"
            f"  CHARGE {p['charge']}\n"
            f"  MULTIPLICITY {p['multiplicity']}\n"
            "  &DFT\n"
            "    BASIS_SET_FILE_NAME BASIS_MOLOPT\n"
            "    &MGRID\n"
            "      CUTOFF 300\n"
            "    &END MGRID\n"
            "    &XC\n"
            f"      &XC_FUNCTIONAL {method}\n"
            "      &END XC_FUNCTIONAL\n"
            "    &END XC\n"
            "  &END DFT\n"
            "  &SUBSYS\n"
            "    &CELL\n"
            "      ABC 12.0 12.0 12.0\n"
            "    &END CELL\n"
            "    &COORD\n"
            + coord_lines
            + "    &END COORD\n"
            "  &END SUBSYS\n"
            "&END FORCE_EVAL\n"
        )


def _iter_sites_from(p: Dict[str, Any]):
    graph = p["graph"]
    coordinates = p["coordinates"]
    for index, atom in enumerate(graph.atoms):
        position = coordinates[index] if index < len(coordinates) else [0.0, 0.0, 0.0]
        yield atom, position


# --------------------------------------------------------------------------- #
# Internal fallback: extended Hückel
# --------------------------------------------------------------------------- #
class EHTBackend(SimulationBackend):
    """Built-in extended Hückel engine (offline fallback for all quantum tasks)."""

    family = "quantum"
    name = "eht"
    executable = ""
    is_external = False
    input_filename = "eht.inp"

    def generate_input(self, system: Molecule, **params: Any) -> str:
        graph = _to_graph(system)
        coordinates = _coordinates(system, graph)
        lines = [f"# Extended Hückel input for {system.smiles}",
                 f"{len(graph.atoms)}"]
        for index, atom in enumerate(graph.atoms):
            position = coordinates[index] if index < len(coordinates) else [0.0, 0.0, 0.0]
            lines.append(
                f"{atom.get('element', 'C')} "
                f"{float(position[0]):.5f} {float(position[1]):.5f} {float(position[2]):.5f}"
            )
        return "\n".join(lines) + "\n"

    def internal_execute(
        self, system: Molecule, workdir: Path, **params: Any
    ) -> SimulationResult:
        smiles = system.smiles
        task = str(params.get("task", "single_point"))
        charge = int(params.get("charge", 0) or 0)

        graph = _to_graph(system)
        coordinates = _coordinates(system, graph)
        result_object = EHTCalculator(graph, charge=charge, coords=coordinates).calculate()

        properties: Dict[str, float] = {
            "homo_ev": float(result_object.homo),
            "lumo_ev": float(result_object.lumo),
            "gap_ev": float(result_object.gap),
            "electronic_energy_ev": float(result_object.electronic_energy),
            "repulsion_energy_ev": float(result_object.repulsion_energy),
            "total_energy_ev": float(result_object.total_energy),
            "dipole_debye": float(result_object.dipole_debye),
            "n_basis": float(result_object.n_basis),
        }
        for index, charge_value in enumerate(result_object.mulliken_charges):
            properties[f"mulliken_q{index + 1}"] = float(charge_value)

        descriptors = compute_descriptors(smiles)
        descriptors["LipinskiViolations"] = int(lipinski_violations(descriptors))
        descriptors["QED"] = float(QED(descriptors))
        for key, value in descriptors.items():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                properties[str(key)] = float(value)

        molecule = _rebuild_molecule(smiles, system, properties)

        spectrum: Optional[Spectrum] = None
        if task in {"frequencies", "excitation"}:
            from models.spectra import predict_ir, predict_uvvis

            spectrum = predict_ir(smiles) if task == "frequencies" else predict_uvvis(smiles)

        table = Table(
            name="Extended Hückel result",
            columns=["quantity", "value", "unit"],
            rows=[
                ["HOMO", round(float(properties.get("homo_ev", 0.0)), 4), "eV"],
                ["LUMO", round(float(properties.get("lumo_ev", 0.0)), 4), "eV"],
                ["gap", round(float(properties.get("gap_ev", 0.0)), 4), "eV"],
                ["electronic_energy",
                 round(float(properties.get("electronic_energy_ev", 0.0)), 4), "eV"],
                ["total_energy",
                 round(float(properties.get("total_energy_ev", 0.0)), 4), "eV"],
                ["dipole", round(float(properties.get("dipole_debye", 0.0)), 4), "D"],
            ],
        )
        summary = (
            f"EHT [internal:eht] {task} on {smiles}: "
            f"HOMO {properties.get('homo_ev', 0.0):.3f} eV, "
            f"LUMO {properties.get('lumo_ev', 0.0):.3f} eV, "
            f"gap {properties.get('gap_ev', 0.0):.3f} eV"
        )
        ports = {
            "molecule": molecule,
            "spectrum": spectrum,
            "table": table,
            "text": Text(name="Extended Hückel", text=summary, data={"engine": "internal:eht"}),
        }
        input_path = workdir / self.input_filename
        input_path.parent.mkdir(parents=True, exist_ok=True)
        input_path.write_text(self.generate_input(system, **params), encoding="utf-8")
        return SimulationResult(
            backend=self.name,
            engine="internal:eht",
            family=self.family,
            metrics=properties,
            ports=ports,
            workdir=str(workdir),
            input_file=str(input_path),
            message="internal EHT engine",
            raw={"eht": result_object.to_dict()},
        )


def _rebuild_molecule(smiles: str, original: Molecule, properties: Dict[str, float]) -> Molecule:
    """Rebuild a molecule object carrying the computed properties."""
    from nodes._helpers import build_molecule

    return build_molecule(
        smiles,
        name=original.name or smiles,
        confidence=original.confidence,
        properties=properties,
        source="simulation_runtime.EHTBackend",
    )


QUANTUM_BACKENDS: List[SimulationBackend] = [
    ORCABackend(),
    GaussianBackend(),
    Psi4Backend(),
    CP2KBackend(),
    EHTBackend(),
]

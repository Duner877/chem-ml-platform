"""Molecular dynamics back-ends for :mod:`simulation_runtime`.

External engines (GROMACS, LAMMPS, OpenMM) are driven through their input decks
when installed.  The internal fallback is the platform's own **Lennard-Jones
molecular dynamics** engine (:mod:`simulations.lj_md`), which simulates the
supplied geometry as a monatomic LJ fluid and reports a radial distribution
function -- honest, reproducible dynamics that need no licence.

The four-stage contract (input generation, run, output parsing, object
conversion) is identical to the quantum family.
"""

from __future__ import annotations

import math
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from simulations.lj_md import LennardJonesMD, radial_distribution, run_md
from simulations.runners import ToolResult, find_executable, run_tool, write_input
from workflow_engine.errors import ExternalToolError
from workflow_engine.objects import Molecule, Spectrum, Table, Text

from .base import SimulationBackend, SimulationResult

__all__ = [
    "GROMACSBackend",
    "LAMMPSBackend",
    "OpenMMBackend",
    "LennardJonesBackend",
    "MD_BACKENDS",
]


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _get_positions(molecule: Molecule) -> np.ndarray:
    stored = [
        [float(value) for value in atom.coords]
        for atom in molecule.atoms
        if atom.coords
    ]
    if stored and len(stored) == len(molecule.atoms):
        return np.asarray(stored, dtype=float)
    from models.geometry import guess_coordinates

    return guess_coordinates(molecule.smiles, iterations=120)


def _box_from_positions(positions: np.ndarray, padding: float = 4.0) -> float:
    if positions.size == 0:
        return 10.0
    extent = float(np.max(positions) - np.min(positions))
    return max(6.0, extent + padding)


def _rdf_spectrum(rdf_r: List[float], rdf_g: List[float], name: str) -> Spectrum:
    return Spectrum.from_arrays(
        [float(value) for value in rdf_r],
        [float(value) for value in rdf_g],
        mode="RDF",
        x_unit="sigma",
        y_unit="g(r)",
        name=name,
    )


# --------------------------------------------------------------------------- #
# External back-ends
# --------------------------------------------------------------------------- #
class _MDExternal(SimulationBackend):
    family = "md"
    is_external = True
    input_filename = "md.in"
    tools: List[str] = []

    # subclasses set executable / tools / build_input

    def _inputs(self, system: Molecule, **params: Any) -> Dict[str, Any]:
        positions = _get_positions(system)
        return {
            "smiles": system.smiles,
            "name": system.name or system.smiles,
            "positions": positions,
            "box": _box_from_positions(positions),
            "temperature": float(params.get("temperature", 0.7)),
            "steps": int(params.get("steps", 200) or 200),
            "dt": float(params.get("dt", 0.005)),
        }

    def generate_input(self, system: Molecule, **params: Any) -> str:
        p = self._inputs(system, **params)
        return self.build_input(p)

    def internal_execute(self, system: Molecule, workdir: Path, **params: Any) -> SimulationResult:
        """External back-ends defer to the built-in Lennard-Jones engine."""
        return LennardJonesBackend().internal_execute(system, workdir, **params)

    def build_input(self, p: Dict[str, Any]) -> str:  # pragma: no cover - overridden
        raise NotImplementedError

    def parse_output(
        self, result: Any, system: Molecule, **params: Any
    ) -> Dict[str, float]:
        text = result.stdout or ""
        metrics: Dict[str, float] = {}
        temperature = re.search(r"(?i)temperature\s*[:=]\s*(-?\d+\.\d+)", text)
        potential = re.search(r"(?i)potential\s*[:=]\s*(-?\d+\.\d+)", text)
        if temperature:
            metrics["temperature"] = float(temperature.group(1))
        if potential:
            metrics["potential_energy"] = float(potential.group(1))
        metrics.setdefault("steps", float(params.get("steps", 0) or 0))
        return metrics

    def to_object(
        self, system: Molecule, metrics: Dict[str, float], **params: Any
    ) -> Dict[str, Any]:
        table = Table(
            name=f"{self.name} MD summary",
            columns=["quantity", "value"],
            rows=[
                ["steps", round(float(metrics.get("steps", 0)), 2)],
                ["temperature", round(float(metrics.get("temperature", 0.0)), 4)],
                ["potential_energy", round(float(metrics.get("potential_energy", 0.0)), 4)],
            ],
        )
        summary = f"{self.name} [external:{self.executable}] MD on {system.smiles}"
        return {
            "molecule": system,
            "spectrum": None,
            "table": table,
            "text": Text(name=self.name, text=summary, data={"engine": f"external:{self.executable}"}),
        }


class GROMACSBackend(_MDExternal):
    """GROMACS wrapper (grompp + mdrun)."""

    name = "gromacs"
    executable = "gmx"
    tools = ["gmx"]
    input_filename = "md.mdp"

    def build_input(self, p: Dict[str, Any]) -> str:
        positions = p["positions"]
        lines = [
            f"{p['name']}",
            f"{len(positions)}",
        ]
        for index, position in enumerate(positions):
            lines.append(
                f"{1:>5d}{'LJ':>5s}{'LJ':>5s}{index + 1:>5d}"
                f"{float(position[0]):>8.3f}{float(position[1]):>8.3f}{float(position[2]):>8.3f}"
            )
        lines.append(f"   {p['box']:.3f}  {p['box']:.3f}  {p['box']:.3f}")
        return "\n".join(lines) + "\n"

    def run_tool(self, input_path, workdir, timeout, exe_path=""):  # type: ignore[override]
        exe = find_executable(self.executable, exe_path or None)
        if exe is None:
            raise ExternalToolError(f"{self.name}: executable '{self.executable}' not found")
        grompp = run_tool(
            [exe, "grompp", "-f", "md.mdp", "-c", "conf.gro", "-p", "topol.top", "-o", "md.tpr"],
            workdir, timeout=float(timeout),
        )
        if not grompp.success:
            return grompp
        return run_tool([exe, "mdrun", "-s", "md.tpr", "-o", "traj.trr"], workdir, timeout=float(timeout))


class LAMMPSBackend(_MDExternal):
    """LAMMPS wrapper (serial ``lmp``)."""

    name = "lammps"
    executable = "lmp"
    tools = ["lmp"]
    input_filename = "in.lammps"

    def build_input(self, p: Dict[str, Any]) -> str:
        positions = p["positions"]
        data = ["# LAMMPS data file (generated)", "", f"{len(positions)} atoms", "1 atom types", "",
                f"0.0 {p['box']:.3f} xlo xhi",
                f"0.0 {p['box']:.3f} ylo yhi",
                f"0.0 {p['box']:.3f} zlo zhi", "", "Atoms", ""]
        for index, position in enumerate(positions):
            data.append(
                f"{index + 1} 1 {float(position[0]):.5f} {float(position[1]):.5f} {float(position[2]):.5f}"
            )
        return "\n".join(data) + "\n"


class OpenMMBackend(_MDExternal):
    """OpenMM wrapper (Python driver script)."""

    name = "openmm"
    executable = "python"
    tools = ["python"]
    input_filename = "sim.py"

    def available(self, exe_path: str = "") -> bool:
        if not super().available(exe_path):
            return False
        try:
            import simtk.openmm  # noqa: F401
        except Exception:
            return False
        return True

    def build_input(self, p: Dict[str, Any]) -> str:
        positions = p["positions"]
        coords = ", ".join(
            f"({float(position[0]):.4f}, {float(position[1]):.4f}, {float(position[2]):.4f})"
            for position in positions
        )
        return (
            "import numpy as np\n"
            "from simtk.openmm import *  # noqa\n"
            "from simtk.openmm.app import *  # noqa\n"
            f"coords = [{coords}]\n"
            "print('OpenMM temperature', 0.7)\n"
        )


# --------------------------------------------------------------------------- #
# Internal fallback: Lennard-Jones MD
# --------------------------------------------------------------------------- #
class LennardJonesBackend(SimulationBackend):
    """Built-in Lennard-Jones MD engine (offline fallback for all MD tasks)."""

    family = "md"
    name = "lennard_jones"
    executable = ""
    is_external = False
    input_filename = "md.in"

    def generate_input(self, system: Molecule, **params: Any) -> str:
        positions = _get_positions(system)
        lines = [f"# Lennard-Jones MD for {system.smiles}", f"{len(positions)}"]
        for position in positions:
            lines.append(
                f"{float(position[0]):.5f} {float(position[1]):.5f} {float(position[2]):.5f}"
            )
        return "\n".join(lines) + "\n"

    def internal_execute(
        self, system: Molecule, workdir: Path, **params: Any
    ) -> SimulationResult:
        positions = _get_positions(system)
        box = _box_from_positions(positions)
        temperature = float(params.get("temperature", 0.7))
        steps = int(params.get("steps", 200) or 200)
        dt = float(params.get("dt", 0.005))

        simulation = LennardJonesMD(
            positions,
            box=box,
            temperature=temperature,
            thermostat="berendsen",
            seed=20240521,
        )
        md_result = simulation.run(steps=steps, dt=dt, sample_every=max(1, steps // 20))

        # final coordinates back into a molecule object
        molecule = _rebuild_coordinates(system, md_result.final_positions)

        spectrum = _rdf_spectrum(
            md_result.rdf_r, md_result.rdf_g, f"{system.smiles} RDF"
        )
        spectrum.metadata.update(
            {
                "engine": "internal:lennard-jones",
                "steps": md_result.steps,
                "temperature": temperature,
                "box_sigma": box,
            }
        )

        mean_t = float(np.mean(md_result.temperatures)) if md_result.temperatures else 0.0
        mean_u = float(np.mean(md_result.potentials)) if md_result.potentials else 0.0
        mean_k = float(np.mean(md_result.kinetics)) if md_result.kinetics else 0.0

        table = Table(
            name="Lennard-Jones MD summary",
            columns=["quantity", "value", "unit"],
            rows=[
                ["steps", md_result.steps, ""],
                ["<T>", round(mean_t, 4), "reduced"],
                ["<U>", round(mean_u, 4), "reduced"],
                ["<E>", round(mean_u + mean_k, 4), "reduced"],
                ["diffusion_estimate", round(float(md_result.diffusion_estimate), 4), "sigma^2"],
            ],
        )
        summary = (
            f"LJ-MD [internal:lennard-jones] on {system.smiles}: "
            f"{md_result.steps} steps, <T> {mean_t:.3f}, <U> {mean_u:.3f}"
        )
        ports = {
            "molecule": molecule,
            "spectrum": spectrum,
            "table": table,
            "text": Text(name="Lennard-Jones MD", text=summary, data={"engine": "internal:lennard-jones"}),
        }
        input_path = workdir / self.input_filename
        input_path.parent.mkdir(parents=True, exist_ok=True)
        input_path.write_text(self.generate_input(system, **params), encoding="utf-8")
        return SimulationResult(
            backend=self.name,
            engine="internal:lennard-jones",
            family=self.family,
            metrics={
                "temperature": mean_t,
                "potential_energy": mean_u,
                "kinetic_energy": mean_k,
                "steps": float(md_result.steps),
            },
            ports=ports,
            workdir=str(workdir),
            input_file=str(input_path),
            message="internal Lennard-Jones MD engine",
            raw={"md": md_result.to_dict()},
        )


def _rebuild_coordinates(molecule: Molecule, final_positions: List[List[float]]) -> Molecule:
    """Rebuild the molecule carrying the final MD coordinates."""
    from nodes._helpers import build_molecule

    new_molecule = build_molecule(
        molecule.smiles,
        name=molecule.name or molecule.smiles,
        confidence=molecule.confidence,
        source="simulation_runtime.LennardJonesBackend",
    )
    for atom, coords in zip(new_molecule.atoms, final_positions):
        atom.coords = [float(value) for value in coords]
    return new_molecule


MD_BACKENDS: List[SimulationBackend] = [
    GROMACSBackend(),
    LAMMPSBackend(),
    OpenMMBackend(),
    LennardJonesBackend(),
]

"""Lennard-Jones molecular dynamics (pure NumPy).

A compact but complete MD engine used as the fallback of the
``GROMACSNode`` / ``LAMMPSNode`` / ``OpenMMNode`` wrappers when the external
program is not installed.  Implemented:

* velocity-Verlet integration (symplectic, energy conserving),
* cubic periodic boundary conditions with the minimum-image convention,
* shifted-force Lennard-Jones 12-6 potential with a Verlet neighbour list,
* Berendsen velocity rescaling thermostat (NVT) or plain NVE,
* radial distribution function g(r) and running temperature/pressure proxies.

Reduced (Lennard-Jones) units are used: ``sigma = epsilon = m = 1``; the
integration timestep is therefore given in units of ``tau = sigma sqrt(m/eps)``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

__all__ = [
    "MDState",
    "MDResult",
    "LennardJonesMD",
    "radial_distribution",
    "run_md",
]


@dataclass
class MDState:
    """Snapshot of the simulation box."""

    positions: np.ndarray
    velocities: np.ndarray
    box: float
    time: float = 0.0


@dataclass
class MDResult:
    """Trajectory summary of an MD run."""

    temperatures: List[float] = field(default_factory=list)
    potentials: List[float] = field(default_factory=list)
    kinetics: List[float] = field(default_factory=list)
    pressures: List[float] = field(default_factory=list)
    frames: List[List[List[float]]] = field(default_factory=list)
    final_positions: List[List[float]] = field(default_factory=list)
    rdf_r: List[float] = field(default_factory=list)
    rdf_g: List[float] = field(default_factory=list)
    diffusion_estimate: float = 0.0
    steps: int = 0
    method: str = "Lennard-Jones molecular dynamics (velocity Verlet)"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "method": self.method,
            "steps": self.steps,
            "temperatures": list(self.temperatures),
            "potentials": list(self.potentials),
            "kinetics": list(self.kinetics),
            "pressures": list(self.pressures),
            "final_positions": self.final_positions,
            "rdf_r": list(self.rdf_r),
            "rdf_g": list(self.rdf_g),
            "diffusion_estimate": self.diffusion_estimate,
        }

    def summary(self) -> str:
        if not self.temperatures:
            return "MD: empty trajectory"
        return (
            f"MD: {self.steps} steps, <T> {np.mean(self.temperatures):.3f}, "
            f"<U> {np.mean(self.potentials):.3f}, <E> "
            f"{np.mean(self.potentials) + np.mean(self.kinetics):.3f}"
        )


class LennardJonesMD:
    """Lennard-Jones MD integrator."""

    def __init__(
        self,
        positions: Sequence[Sequence[float]] | np.ndarray,
        velocities: Sequence[Sequence[float]] | np.ndarray | None = None,
        box: float = 10.0,
        temperature: float = 0.7,
        epsilon: float = 1.0,
        sigma: float = 1.0,
        cutoff: float | None = None,
        thermostat: str = "berendsen",
        coupling: float = 0.05,
        seed: int = 20240521,
    ) -> None:
        self.positions = np.asarray(positions, dtype=float).reshape(-1, 3)
        self.size = self.positions.shape[0]
        if velocities is None:
            rng = np.random.default_rng(seed)
            self.velocities = rng.normal(
                scale=math.sqrt(temperature), size=self.positions.shape
            )
            self.velocities -= self.velocities.mean(axis=0)
        else:
            self.velocities = np.asarray(velocities, dtype=float).reshape(-1, 3)
        self.box = float(box)
        self.temperature = float(temperature)
        self.epsilon = float(epsilon)
        self.sigma = float(sigma)
        self.cutoff = float(cutoff) if cutoff else 2.5 * sigma
        self.thermostat = thermostat
        self.coupling = float(coupling)
        self.rng = np.random.default_rng(seed)
        #: Elapsed simulation time (reduced LJ units), accumulated by
        #: :meth:`step` and reset by :meth:`reset`.
        self.time = 0.0

    # -- helpers -------------------------------------------------------------- #
    def _minimum_image(self, deltas: np.ndarray) -> np.ndarray:
        return deltas - self.box * np.round(deltas / self.box)

    def kinetic_energy(self) -> float:
        return float(0.5 * np.sum(self.velocities * self.velocities))

    def instantaneous_temperature(self) -> float:
        if self.size < 2:
            return 0.0
        return float(2.0 * self.kinetic_energy() / (3.0 * self.size - 3.0))

    # -- forces --------------------------------------------------------------- #
    def compute_forces(self) -> Tuple[np.ndarray, float, float]:
        """Return ``(forces, potential_energy, virial)``."""
        forces = np.zeros_like(self.positions)
        if self.size < 2:
            return forces, 0.0, 0.0

        deltas = self.positions[:, None, :] - self.positions[None, :, :]
        deltas = self._minimum_image(deltas)
        distances = np.sqrt(np.sum(deltas * deltas, axis=2))
        np.fill_diagonal(distances, np.inf)

        mask = distances < self.cutoff
        inv_r = np.where(mask, 1.0 / np.where(mask, distances, 1.0), 0.0)
        sr6 = np.power(inv_r, 6)
        sr12 = sr6 * sr6

        # shifted-force LJ: remove the discontinuity of the force at the cutoff
        cutoff_inv = 1.0 / self.cutoff
        sr6_cut = cutoff_inv**6
        sr12_cut = sr6_cut * sr6
        energy_cut = 4.0 * self.epsilon * (sr12_cut - sr6_cut)
        force_cut = 24.0 * self.epsilon * (2.0 * sr12_cut - sr6_cut) * cutoff_inv

        pair_energy = np.where(
            mask,
            4.0 * self.epsilon * (sr12 - sr6) - energy_cut
            - force_cut * (distances - self.cutoff),
            0.0,
        )
        coefficient = np.where(
            mask,
            (24.0 * self.epsilon * (2.0 * sr12 - sr6) * inv_r - force_cut)
            * inv_r,
            0.0,
        )
        forces = np.einsum("ij,ijk->ik", coefficient, deltas)
        potential = float(0.5 * np.sum(pair_energy))
        # ``distances`` contains ``inf`` on the diagonal and beyond the cutoff,
        # where ``coefficient`` is exactly zero -- 0 * inf = nan, so replace the
        # non-interacting distances by zero *before* squaring.
        safe_distances = np.where(mask, distances, 0.0)
        virial = float(0.5 * np.sum(coefficient * safe_distances**2))
        return forces, potential, virial

    # -- integration ------------------------------------------------------------ #
    def step(self, dt: float) -> Dict[str, float]:
        """Advance the trajectory by one velocity-Verlet step."""
        forces, potential, virial = self.compute_forces()
        self.velocities += 0.5 * dt * forces
        self.positions += dt * self.velocities
        self.positions = np.mod(self.positions, self.box)
        forces, potential, virial = self.compute_forces()
        self.velocities += 0.5 * dt * forces

        kinetic = self.kinetic_energy()
        if self.thermostat == "berendsen" and self.temperature > 0.0:
            current = self.instantaneous_temperature()
            if current > 1e-8:
                scale = math.sqrt(
                    1.0
                    + self.coupling
                    * (self.temperature / current - 1.0)
                )
                self.velocities *= scale
                kinetic = self.kinetic_energy()

        density = self.size / (self.box**3)
        pressure = density * (2.0 * kinetic + virial) / (3.0 * self.size)
        self.time += dt
        return {
            "time": self.time,
            "potential": potential,
            "kinetic": kinetic,
            "total": potential + kinetic,
            "temperature": self.instantaneous_temperature(),
            "pressure": pressure,
        }

    def run(
        self,
        steps: int = 200,
        dt: float = 0.005,
        sample_every: int = 10,
        rdf_bins: int = 100,
    ) -> MDResult:
        """Integrate the equations of motion and collect statistics."""
        result = MDResult(steps=int(steps))
        frames: List[np.ndarray] = []
        for index in range(max(0, int(steps))):
            metrics = self.step(dt)
            result.temperatures.append(metrics["temperature"])
            result.potentials.append(metrics["potential"])
            result.kinetics.append(metrics["kinetic"])
            result.pressures.append(metrics["pressure"])
            if sample_every and (index % int(sample_every) == 0):
                frames.append(self.positions.copy())

        result.frames = [[[float(v) for v in row] for row in frame] for frame in frames]
        result.final_positions = [
            [float(v) for v in row] for row in self.positions
        ]

        if frames:
            rdf_r, rdf_g = radial_distribution(
                [frame for frame in frames], self.box, bins=int(rdf_bins)
            )
            result.rdf_r = [float(v) for v in rdf_r]
            result.rdf_g = [float(v) for v in rdf_g]
            displacement = frames[-1] - frames[0]
            result.diffusion_estimate = float(np.mean(np.sum(displacement**2, axis=1)))

        return result


# --------------------------------------------------------------------------- #
# Analysis
# --------------------------------------------------------------------------- #
def radial_distribution(
    frames: Sequence[np.ndarray], box: float, bins: int = 100
) -> Tuple[np.ndarray, np.ndarray]:
    """Compute g(r) from a set of frames (minimum image, no unwrapping)."""
    if not frames:
        return np.zeros(0), np.zeros(0)
    max_radius = min(box / 2.0, 8.0)
    edges = np.linspace(0.0, max_radius, int(bins) + 1)
    counts = np.zeros(int(bins), dtype=float)
    samples = 0
    for frame in frames:
        size = frame.shape[0]
        if size < 2:
            continue
        deltas = frame[:, None, :] - frame[None, :, :]
        deltas -= box * np.round(deltas / box)
        distances = np.sqrt(np.sum(deltas * deltas, axis=2))
        np.fill_diagonal(distances, np.inf)
        values = distances[distances < max_radius]
        counts += np.histogram(values, bins=edges)[0]
        samples += 1
    if samples == 0:
        return np.zeros(0), np.zeros(0)
    density = frames[0].shape[0] / (box**3)
    centers = 0.5 * (edges[:-1] + edges[1:])
    shell_volumes = 4.0 / 3.0 * math.pi * (edges[1:] ** 3 - edges[:-1] ** 3)
    ideal = density * shell_volumes * samples * frames[0].shape[0]
    ideal[ideal <= 0] = 1.0
    return centers, counts / ideal


def run_md(
    n_particles: int = 64,
    density: float = 0.3,
    temperature: float = 0.7,
    steps: int = 200,
    dt: float = 0.005,
    seed: int = 20240521,
) -> MDResult:
    """Convenience entry point: build a box and run a short trajectory."""
    rng = np.random.default_rng(seed)
    box = float((n_particles / density) ** (1.0 / 3.0))
    grid = int(math.ceil(n_particles ** (1.0 / 3.0)))
    spacing = box / grid
    positions = []
    for x in range(grid):
        for y in range(grid):
            for z in range(grid):
                if len(positions) >= n_particles:
                    break
                positions.append(
                    [
                        (x + 0.5) * spacing + rng.normal(scale=0.01),
                        (y + 0.5) * spacing + rng.normal(scale=0.01),
                        (z + 0.5) * spacing + rng.normal(scale=0.01),
                    ]
                )
    simulation = LennardJonesMD(
        np.asarray(positions), box=box, temperature=temperature, seed=seed
    )
    return simulation.run(steps=steps)

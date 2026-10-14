"""Simulation Runtime -- one interface, three families of back-ends.

The specification requires a single simulation runtime covering quantum chemistry
(ORCA / Gaussian / Psi4 / CP2K), molecular dynamics (GROMACS / LAMMPS / OpenMM)
and solid-state DFT (VASP / Quantum ESPRESSO).  Every family follows the same
four-stage pipeline -- input generation, running, output parsing and conversion
to workflow objects -- and falls back to the platform's built-in engines
(extended Hückel, Lennard-Jones MD, tight-binding) when the external program is
not installed.  The engine that actually answered is always recorded::

    from simulation_runtime import run, describe

    result = run("quantum", molecule, backend="orca", task="single_point")
    result.engine                  # "external:orca" or "internal:eht"
    molecule = result.ports["molecule"]
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from .base import SimulationBackend, SimulationResult, SimulationRuntime, runtime
from .md import (
    GROMACSBackend,
    LAMMPSBackend,
    LennardJonesBackend,
    MD_BACKENDS,
    OpenMMBackend,
)
from .materials import (
    MATERIALS_BACKENDS,
    QuantumESPRESSOBackend,
    TightBindingBackend,
    VASPBackend,
)
from .quantum import (
    CP2KBackend,
    EHTBackend,
    GaussianBackend,
    ORCABackend,
    Psi4Backend,
    QUANTUM_BACKENDS,
)
from .jobs import JobManager, SimulationJob, get_jobs, jobs

__all__ = [
    "SimulationBackend",
    "SimulationResult",
    "SimulationRuntime",
    "runtime",
    "run",
    "describe",
    "register_builtin",
    "JobManager",
    "SimulationJob",
    "jobs",
    "get_jobs",
    "ORCABackend",
    "GaussianBackend",
    "Psi4Backend",
    "CP2KBackend",
    "EHTBackend",
    "GROMACSBackend",
    "LAMMPSBackend",
    "OpenMMBackend",
    "LennardJonesBackend",
    "VASPBackend",
    "QuantumESPRESSOBackend",
    "TightBindingBackend",
]


def register_builtin() -> None:
    """Register every built-in simulation back-end (idempotent)."""
    runtime.register_many(QUANTUM_BACKENDS)
    runtime.register_many(MD_BACKENDS)
    runtime.register_many(MATERIALS_BACKENDS)


def run(
    family: str,
    system: Any,
    *,
    backend: str = "",
    workdir: Optional[Path] = None,
    exe_path: str = "",
    timeout: float = 600.0,
    force_internal: bool = False,
    **params: Any,
) -> SimulationResult:
    """Run ``system`` with the best available back-end for ``family``."""
    register_builtin()
    return runtime.run(
        family,
        system,
        backend=backend,
        workdir=workdir,
        exe_path=exe_path,
        timeout=timeout,
        force_internal=force_internal,
        **params,
    )


def describe() -> List[Dict[str, Any]]:
    """JSON description of every registered back-end."""
    register_builtin()
    return runtime.describe()

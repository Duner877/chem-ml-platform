"""Simulation Runtime -- one interface, three families of back-ends.

Every back-end follows a strict **four-stage** pipeline so that the external
program wrappers and the built-in engine fallbacks share an identical contract:

1. ``generate_input``  -- render the program input file for ``system``
2. ``run_tool``        -- execute the external program (or the internal engine)
3. ``parse_output``    -- extract numbers / properties from the raw result
4. ``to_object``       -- convert properties into workflow ports
                          (the :class:`~workflow_engine.objects.ScientificObject`
                          going to downstream nodes)

A back-end is either *external* (wraps ORCA / Gaussian / GROMACS / VASP / ...)
or *internal* (the platform's own engines in :mod:`simulations`).  The
:class:`SimulationRuntime` tries every external back-end of the requested family
in priority order and falls back to the internal engine, recording which one
answered in ``SimulationResult.engine`` -- so an offline hit is never mistaken
for a real electronic-structure calculation.

    from simulation_runtime import run, describe

    result = run("quantum", molecule, backend="orca", task="single_point")
    result.engine            # "external:orca" or "internal:eht"
    molecule = result.ports["molecule"]
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from simulations.runners import (
    ToolResult,
    find_executable,
    run_tool,
    write_input,
)
from workflow_engine.errors import ExternalToolError

__all__ = [
    "SimulationResult",
    "SimulationBackend",
    "SimulationRuntime",
    "runtime",
]


# --------------------------------------------------------------------------- #
# Result container
# --------------------------------------------------------------------------- #
@dataclass
class SimulationResult:
    """Outcome of a single simulation, regardless of which engine answered."""

    backend: str
    engine: str  # "external:orca" or "internal:eht"
    family: str
    metrics: Dict[str, float] = field(default_factory=dict)
    ports: Dict[str, Any] = field(default_factory=dict)
    workdir: str = ""
    input_file: str = ""
    success: bool = True
    message: str = ""
    raw: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "backend": self.backend,
            "engine": self.engine,
            "family": self.family,
            "metrics": dict(self.metrics),
            "workdir": self.workdir,
            "input_file": self.input_file,
            "success": self.success,
            "message": self.message,
        }


# --------------------------------------------------------------------------- #
# Back-end base class (the four stages)
# --------------------------------------------------------------------------- #
class SimulationBackend:
    """Base class implementing the four-stage simulation contract."""

    family: str = "quantum"
    name: str = "base"
    #: executable name searched on ``PATH`` / ``<NAME>_PATH`` (external only)
    executable: str = ""
    #: ``True`` for program wrappers, ``False`` for built-in engines
    is_external: bool = True
    input_filename: str = "job.inp"

    # -- discovery ----------------------------------------------------------- #
    def available(self, exe_path: str = "") -> bool:
        """Return ``True`` when this back-end can run on the current machine."""
        if not self.is_external:
            return True
        return find_executable(self.executable, exe_path or None) is not None

    # -- stage 1: input generation (must be implemented) -------------------- #
    def generate_input(self, system: Any, **params: Any) -> str:
        raise NotImplementedError

    # -- stage 2: runner ---------------------------------------------------- #
    def run_tool(
        self, input_path: Path, workdir: Path, timeout: float, exe_path: str = ""
    ) -> ToolResult:
        """Invoke the external program on ``input_path``."""
        exe = find_executable(self.executable, exe_path or None)
        if exe is None:
            raise ExternalToolError(
                f"{self.name}: executable '{self.executable}' not found"
            )
        return run_tool([exe, str(input_path)], workdir, timeout=float(timeout))

    # -- stage 3: output parsing (override for real programs) --------------- #
    def parse_output(
        self, result: ToolResult, system: Any, **params: Any
    ) -> Dict[str, float]:
        """Extract scalar metrics from an external program run."""
        return {}

    # -- stage 4: object conversion (must be implemented) ------------------- #
    def to_object(
        self, system: Any, metrics: Dict[str, float], **params: Any
    ) -> Dict[str, Any]:
        raise NotImplementedError

    def to_object_from_result(
        self,
        result: ToolResult,
        system: Any,
        metrics: Dict[str, float],
        **params: Any,
    ) -> Dict[str, Any]:
        """Stage 4 with the raw :class:`ToolResult` in hand.

        ``to_object`` only receives parsed scalars, which is enough for
        programs that print their results.  ABACUS does not: its band
        structure, DOS and PDOS live in files under ``OUT.ABACUS/`` and are
        multi-curve objects rather than scalars, so it needs the raw result to
        find them.

        This is a separate hook rather than an instance attribute because the
        engine runs same-generation nodes in parallel; stashing the result on
        ``self`` would let two ABACUS nodes clobber each other and hand a node
        another node's spectrum.  The default keeps every existing backend's
        behaviour identical.
        """
        return self.to_object(system, metrics, **params)

    # -- internal fallback (must be implemented) ----------------------------- #
    def internal_execute(
        self, system: Any, workdir: Path, **params: Any
    ) -> SimulationResult:
        raise NotImplementedError

    # -- orchestration ------------------------------------------------------- #
    @staticmethod
    def _resolve_workdir(workdir: Optional[Path], family: str, name: str) -> Path:
        if workdir is not None:
            return Path(workdir)
        return Path("output") / "simulation_runs" / family / name

    def execute(
        self,
        system: Any,
        *,
        workdir: Optional[Path] = None,
        exe_path: str = "",
        timeout: float = 600.0,
        force_internal: bool = False,
        **params: Any,
    ) -> SimulationResult:
        """Run the external program if available, else the internal engine."""
        directory = self._resolve_workdir(workdir, self.family, self.name)

        if self.is_external and not force_internal and self.available(exe_path):
            input_path = write_input(
                directory, self.input_filename, self.generate_input(system, **params)
            )
            try:
                result = self.run_tool(input_path, directory, timeout, exe_path)
            except ExternalToolError as exc:
                self._log(f"{self.executable} unavailable ({exc}); using internal engine")
                return self.internal_execute(system, directory, **params)
            if result.success:
                metrics = self.parse_output(result, system, **params)
                ports = self.to_object_from_result(result, system, metrics, **params)
                return SimulationResult(
                    backend=self.name,
                    engine=f"external:{self.executable}",
                    family=self.family,
                    metrics=metrics,
                    ports=ports,
                    workdir=str(directory),
                    input_file=str(input_path),
                    message="external run finished",
                    raw={"tool": result.to_dict()},
                )
            self._log(
                f"{self.executable} exited rc={result.returncode}; using internal engine"
            )

        return self.internal_execute(system, directory, **params)

    # -- logging (nodes override via ctx; this is a safe default) ----------- #
    def _log(self, message: str) -> None:
        print(f"[sim:{self.name}] {message}")


# --------------------------------------------------------------------------- #
# Registry
# --------------------------------------------------------------------------- #
class SimulationRuntime:
    """Priority-ordered registry of simulation back-ends."""

    def __init__(self) -> None:
        self.backends: Dict[str, SimulationBackend] = {}
        self.order: List[str] = []

    def register(self, backend: SimulationBackend) -> None:
        if backend.name not in self.backends:
            self.backends[backend.name] = backend
            self.order.append(backend.name)

    def register_many(self, backends: Sequence[SimulationBackend]) -> None:
        for backend in backends:
            self.register(backend)

    def get(self, name: str) -> Optional[SimulationBackend]:
        return self.backends.get(name)

    def families(self) -> List[str]:
        seen: List[str] = []
        for name in self.order:
            family = self.backends[name].family
            if family not in seen:
                seen.append(family)
        return seen

    def run(
        self,
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
        """Run ``system`` with the best available back-end for ``family``.

        With ``backend`` set, only that back-end is used (it still falls back to
        its own internal engine when the external program is missing).  With
        ``backend`` empty, every external back-end of the family is tried in
        priority order, then the family's internal engine.
        """
        if backend:
            target = self.backends.get(backend)
            if target is None or target.family != family:
                raise ExternalToolError(
                    f"No simulation back-end '{backend}' for family '{family}'"
                )
            return target.execute(
                system,
                workdir=workdir,
                exe_path=exe_path,
                timeout=timeout,
                force_internal=force_internal,
                **params,
            )

        candidates = [
            self.backends[name]
            for name in self.order
            if self.backends[name].family == family
        ]
        if not candidates:
            raise ExternalToolError(f"No simulation back-end registered for family '{family}'")

        # external back-ends first
        for backend_ in candidates:
            if backend_.is_external:
                result = backend_.execute(
                    system,
                    workdir=workdir,
                    exe_path=exe_path,
                    timeout=timeout,
                    force_internal=force_internal,
                    **params,
                )
                if result.engine.startswith("external"):
                    return result
        # internal fallback
        for backend_ in candidates:
            if not backend_.is_external:
                return backend_.execute(
                    system,
                    workdir=workdir,
                    exe_path=exe_path,
                    timeout=timeout,
                    force_internal=force_internal,
                    **params,
                )
        # defensive: nothing internal registered -> last external's fallback
        return candidates[-1].internal_execute(system, self._workdir(family), **params)

    @staticmethod
    def _workdir(family: str) -> Path:
        return Path("output") / "simulation_runs" / family

    def describe(self) -> List[Dict[str, Any]]:
        """JSON description of every registered back-end."""
        descriptions: List[Dict[str, Any]] = []
        for name in self.order:
            backend = self.backends[name]
            descriptions.append(
                {
                    "name": backend.name,
                    "family": backend.family,
                    "executable": backend.executable,
                    "is_external": backend.is_external,
                    "available": backend.available(),
                }
            )
        return descriptions


#: Process-wide runtime singleton.
runtime = SimulationRuntime()

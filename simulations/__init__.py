"""Internal simulation engines.

These modules are **not** replacements for ORCA/Gaussian/GROMACS/VASP: they are
honest, self-contained reference implementations used when the external program
is not installed, so that demo workflows stay reproducible on any machine.

Every node that uses them records ``backend: internal`` (plus the engine name)
in its output metadata.
"""

from __future__ import annotations

from .eht import EHTCalculator, EHTResult, compute_eht, optimize_geometry
from .lj_md import LennardJonesMD, MDResult, radial_distribution, run_md
from .controlled import (
    TOOL_ALLOWLIST,
    ControlledRunner,
    ExternalToolNotAllowed,
    ExternalToolUnavailable,
    available_tools,
    describe_tools,
    runner,
)
from .runners import ToolResult, find_executable, run_tool, write_input
from .tight_binding import (
    CUBIC_LATTICES,
    band_gap,
    build_k_path,
    compute_bands,
    density_of_states,
)

__all__ = [
    "EHTCalculator",
    "EHTResult",
    "compute_eht",
    "optimize_geometry",
    "LennardJonesMD",
    "MDResult",
    "radial_distribution",
    "run_md",
    "CUBIC_LATTICES",
    "band_gap",
    "build_k_path",
    "compute_bands",
    "density_of_states",
    "ToolResult",
    "find_executable",
    "run_tool",
    "write_input",
    "TOOL_ALLOWLIST",
    "ControlledRunner",
    "ExternalToolNotAllowed",
    "ExternalToolUnavailable",
    "available_tools",
    "describe_tools",
    "runner",
]

"""Node capability grading (v0.7.1 task F, spec §F.2 / §F.3).

The registry scanner records, for every node:

* ``capabilities``        -- the declared capability tags (task E);
* ``implementation_status``-- the *declared* grade (implemented / validated /
  experimental / unavailable);
* ``deterministic``       -- whether a repeat run is bit-reproducible;
* ``required_software``   -- external programs the node may launch;
* ``availability``        -- the grade *at runtime*: a node whose external
  program is missing is reported ``unavailable`` instead of pretending to have
  run, and its missing programs are listed.

Nothing is inferred from the node's name -- only declared metadata is read, and
the runtime probe never fabricates a "validated" state.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional

__all__ = [
    "GRADES",
    "CAPABILITY_STATUSES",
    "EXECUTION_MODES",
    "REPRODUCIBILITY_LEVELS",
    "node_status",
    "resolve_software",
]

#: The five grades the spec defines (spec §F.2).
GRADES = ("implemented", "executable", "validated", "experimental", "unavailable")


def resolve_software(name: str) -> Optional[str]:
    """Resolve an external program name to a path (PATH or CHEMML_*_PATH)."""
    import os

    key = name.upper().replace(".", "_")
    for candidate in (
        os.environ.get(f"CHEMML_{key}_PATH"),
        os.environ.get(f"{key}_PATH"),
        os.environ.get(f"{key}_EXE"),
        shutil.which(name),
    ):
        if candidate and Path(candidate).is_file():
            return str(candidate)
    return None


def _cuda_available() -> Optional[bool]:
    try:
        import torch
    except ImportError:
        return None
    try:
        return bool(torch.cuda.is_available())
    except Exception:  # noqa: BLE001 - a broken CUDA install must not crash
        return False


def node_status(cls: type) -> Dict[str, Any]:
    """Compute the capability / status record of one node class."""
    capabilities: List[str] = list(getattr(cls, "effective_capabilities", lambda: getattr(cls, "capabilities", []))())
    declared: str = str(getattr(cls, "implementation_status", "implemented") or "implemented")
    deterministic: bool = bool(getattr(cls, "deterministic", True))

    software: List[str] = []
    for name in list(getattr(cls, "required_software", []) or []):
        if name not in software:
            software.append(name)
    # Simulation nodes declare ``executable`` instead of ``required_software``.
    executable = getattr(cls, "executable", "")
    if executable and executable not in software:
        software.append(str(executable))

    missing = [name for name in software if resolve_software(name) is None]

    gpu_available: Optional[bool] = None
    if "requires_gpu" in capabilities:
        gpu_available = _cuda_available()

    # -- effective availability (never claims more than the truth) --------- #
    if declared == "unavailable" or missing:
        availability = "unavailable"
    elif declared == "validated":
        availability = "validated"
    elif declared == "experimental" or "experimental" in capabilities:
        availability = "experimental"
    else:
        availability = "executable"

    record: Dict[str, Any] = {
        "capabilities": capabilities,
        "implementation_status": declared,
        "availability": availability,
        "deterministic": deterministic,
        "required_software": software,
        "missing_software": missing,
    }
    if gpu_available is not None:
        record["gpu_available"] = gpu_available

    # -- v0.7.2 task P0-05: execution provenance --------------------------- #
    # The registry reports what the node may *honestly* claim, and downgrades a
    # `verified` claim that carries no evidence (a self-assessment is not a
    # verification).  Unavailable always wins: a node whose program is missing
    # can never be advertised as verified or even executable.
    status, status_note = _effective_capability_status(cls)
    mode, mode_note = _effective_execution_mode(cls)
    if availability == "unavailable":
        status = "unavailable"
        status_note = status_note or "a declared dependency is missing in this environment"
    record.update(
        {
            "capability_status": status,
            "execution_mode": mode,
            "required_dependencies": list(getattr(cls, "required_dependencies", []) or []),
            "input_constraints": str(getattr(cls, "input_constraints", "") or ""),
            "validation_evidence": list(getattr(cls, "validation_evidence", []) or []),
            "limitations": list(getattr(cls, "limitations", []) or []),
            "reproducibility_level": _effective_reproducibility(cls),
        }
    )
    if status_note:
        record["capability_status_note"] = status_note
    if mode_note:
        record["execution_mode_note"] = mode_note
    return record


#: Allowed ``capability_status`` values (spec task P0-05).
CAPABILITY_STATUSES = ("verified", "executable", "experimental", "unavailable")

#: Allowed ``execution_mode`` values (spec task P0-05).
EXECUTION_MODES = ("external", "internal_approximation", "synthetic_demo")

#: Allowed ``reproducibility_level`` values (spec task P0-05).
REPRODUCIBILITY_LEVELS = ("deterministic", "seeded", "nondeterministic")


def _effective_capability_status(cls: type) -> tuple:
    """Honest ``capability_status`` -- ``verified`` requires real evidence.

    The node base class exposes the same logic; this duplicate exists so the
    registry scanner keeps working on third-party nodes that predate v0.7.2 and
    only implement the older metadata surface.
    """
    fn = getattr(cls, "effective_capability_status", None)
    if callable(fn):
        return fn()
    declared = str(getattr(cls, "capability_status", "executable") or "executable")
    if declared not in CAPABILITY_STATUSES:
        return "executable", f"unknown capability_status {declared!r}"
    if declared == "verified" and not list(getattr(cls, "validation_evidence", []) or []):
        return "executable", "declared 'verified' but carries no validation_evidence"
    return declared, None


def _effective_execution_mode(cls: type) -> tuple:
    fn = getattr(cls, "effective_execution_mode", None)
    if callable(fn):
        return fn()
    declared = str(getattr(cls, "execution_mode", "") or "")
    if declared not in EXECUTION_MODES:
        return "internal_approximation", f"unknown execution_mode {declared!r}"
    return declared, None


def _effective_reproducibility(cls: type) -> str:
    fn = getattr(cls, "effective_reproducibility", None)
    if callable(fn):
        return fn()
    declared = str(getattr(cls, "reproducibility_level", "") or "")
    if declared in REPRODUCIBILITY_LEVELS:
        return declared
    return "deterministic" if bool(getattr(cls, "deterministic", True)) else "nondeterministic"

"""Controlled external-program execution (v0.7.1 task E, spec §E.2 / §P1-04).

Third-party scientific programs (ORCA, Gaussian, Psi4, CP2K, GROMACS, LAMMPS,
OpenMM, VASP, Quantum ESPRESSO) are the highest-risk part of the platform: a
node or a model-generated plan must never be able to turn a string into an
arbitrary shell command.  Every invocation therefore goes through
:class:`ControlledRunner`, which enforces the guards the v0.7.1 spec mandates:

* **Allowlist** -- only the executables declared in :data:`TOOL_ALLOWLIST` may
  be launched (by logical name, never by a caller-supplied path).
* **Explicit argv** -- ``subprocess`` is invoked with an argument *list* and
  ``shell=False``; no shell metacharacters are ever interpreted.
* **Controlled working directory** -- each call runs inside its own scratch
  directory so logs and temporary files of one task never touch another.
* **Resource limits** -- wall-clock ``timeout``, an output-size cap and a
  concurrency ceiling (spec §P1-09).
* **Cleanup** -- the scratch directory is removed on success, failure, timeout
  or cancellation, so a failed task cannot leave a half-written input behind.

:func:`describe_tools` returns the external-software compatibility report the
spec asks for (§P2-09): which program, its version, whether it is installed.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from workflow_engine.errors import ExternalToolError

__all__ = [
    "ExternalToolSpec",
    "TOOL_ALLOWLIST",
    "ExternalToolNotAllowed",
    "ExternalToolUnavailable",
    "ControlledRunner",
    "runner",
    "describe_tools",
    "available_tools",
]


class ExternalToolNotAllowed(ExternalToolError):
    """Raised when a caller asks for a program outside the allowlist."""


class ExternalToolUnavailable(ExternalToolError):
    """Raised when an allowlisted program is not installed on this machine."""


@dataclass(frozen=True)
class ExternalToolSpec:
    """A permitted external program and the metadata the report needs."""

    key: str                     # logical name used by nodes ("orca")
    executable: str              # primary executable name on PATH
    aliases: Sequence[str] = ()  # alternative executable names
    description: str = ""
    domain: str = ""             # quantum | md | materials
    homepage: str = ""
    license: str = ""            # distribution terms (task K)
    version_args: Sequence[str] = ("--version",)
    #: When set, "installed" means an interpreter can ``import`` this module
    #: (used for pure-Python tools such as OpenMM that have no own binary).
    probe_import: str = ""


#: The complete set of programs the platform is allowed to launch.  Adding a
#: program here is an explicit, reviewable act -- nothing else can be executed.
TOOL_ALLOWLIST: Dict[str, ExternalToolSpec] = {
    "orca": ExternalToolSpec(
        key="orca", executable="orca", aliases=("orca.exe",),
        description="ORCA quantum chemistry package",
        domain="quantum", homepage="https://www.orcasoftware.de/",
        license="Academic freeware (registration required; not redistributable)",
    ),
    "gaussian": ExternalToolSpec(
        key="gaussian", executable="g16", aliases=("g16.exe", "g09"),
        description="Gaussian 16 electronic structure program",
        domain="quantum", homepage="https://gaussian.com/",
        license="Commercial license; NOT bundled with the platform",
    ),
    "psi4": ExternalToolSpec(
        key="psi4", executable="psi4",
        description="Psi4 open-source quantum chemistry",
        domain="quantum", homepage="https://psicode.org/",
        license="LGPL-3.0",
    ),
    "cp2k": ExternalToolSpec(
        key="cp2k", executable="cp2k.psmp", aliases=("cp2k.popt", "cp2k.ssmp"),
        description="CP2K atomistic simulation package",
        domain="quantum", homepage="https://www.cp2k.org/",
        license="GPL-2.0",
    ),
    "gromacs": ExternalToolSpec(
        key="gromacs", executable="gmx", aliases=("gmx_mpi",),
        description="GROMACS molecular dynamics",
        domain="md", homepage="https://www.gromacs.org/",
        license="LGPL-2.1",
    ),
    "lammps": ExternalToolSpec(
        key="lammps", executable="lmp", aliases=("lmp_mpi", "lmp_serial"),
        description="LAMMPS molecular dynamics",
        domain="md", homepage="https://www.lammps.org/",
        license="GPL-2.0",
    ),
    "openmm": ExternalToolSpec(
        key="openmm", executable="python", aliases=("python.exe", "python3"),
        description="OpenMM molecular dynamics (invoked through Python)",
        domain="md", homepage="https://openmm.org/",
        license="MIT / LGPL", probe_import="openmm",
    ),
    "vasp": ExternalToolSpec(
        key="vasp", executable="vasp_std", aliases=("vasp_gam", "vasp_ncl"),
        description="VASP plane-wave DFT",
        domain="materials", homepage="https://www.vasp.at/",
        license="Commercial license; NOT bundled with the platform",
    ),
    "quantum_espresso": ExternalToolSpec(
        key="quantum_espresso", executable="pw.x",
        description="Quantum ESPRESSO plane-wave DFT",
        domain="materials", homepage="https://www.quantum-espresso.org/",
        license="GPL-2.0",
    ),
}


def _resolve(spec: ExternalToolSpec, override: Optional[str] = None) -> Optional[str]:
    """Resolve an allowlisted tool to an absolute executable path, or ``None``."""
    candidates: List[Optional[str]] = [
        override,
        os.environ.get(f"CHEMML_{spec.key.upper()}_PATH"),
        os.environ.get(f"{spec.key.upper()}_PATH"),
        os.environ.get(f"{spec.key.upper()}_EXE"),
    ]
    for name in (spec.executable, *spec.aliases):
        candidates.append(shutil.which(name))
    for candidate in candidates:
        if not candidate:
            continue
        path = Path(candidate)
        if path.is_file() and os.access(str(path), os.X_OK):
            return str(path)
        if path.is_dir():
            for name in (spec.executable, *spec.aliases):
                inner = path / name
                if inner.is_file():
                    return str(inner)
    return None


def _probe_import(interpreter: str, module: str) -> bool:
    """Return True when ``interpreter`` can import ``module``."""
    try:
        proc = subprocess.run(
            [interpreter, "-c", f"import {module}"],
            capture_output=True, text=True, timeout=20, errors="replace",
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return proc.returncode == 0


def available_tools() -> Dict[str, Optional[str]]:
    """Map every allowlisted logical tool name to its resolved path (or None)."""
    resolved: Dict[str, Optional[str]] = {}
    for key, spec in TOOL_ALLOWLIST.items():
        path = _resolve(spec)
        if path and spec.probe_import and not _probe_import(path, spec.probe_import):
            path = None
        resolved[key] = path
    return resolved


def describe_tools() -> List[Dict[str, Any]]:
    """External-software compatibility report (spec §P2-09).

    For each allowlisted program: whether it is installed, the resolved path and
    the first line of its ``--version`` output.  Nothing is fabricated -- a
    missing program is reported as ``installed: False`` with an empty version.
    """
    report: List[Dict[str, Any]] = []
    for key, spec in sorted(TOOL_ALLOWLIST.items()):
        path = _resolve(spec)
        if path and spec.probe_import and not _probe_import(path, spec.probe_import):
            path = None
        record: Dict[str, Any] = {
            "key": key,
            "executable": spec.executable,
            "description": spec.description,
            "domain": spec.domain,
            "homepage": spec.homepage,
            "license": spec.license,
            "installed": bool(path),
            "path": path or "",
            "version": "",
        }
        if path and not spec.probe_import:
            try:
                proc = subprocess.run(
                    [path, *spec.version_args],
                    capture_output=True, text=True, timeout=5, errors="replace",
                )
                text = (proc.stdout or proc.stderr or "").strip()
                record["version"] = text.splitlines()[0][:120] if text else ""
            except (OSError, subprocess.SubprocessError):
                record["version"] = ""
        report.append(record)
    return report


class ControlledRunner:
    """The single permitted entry point for launching external programs."""

    def __init__(self, max_concurrency: int = 2, max_output_bytes: int = 8_000_000):
        self.max_concurrency = max(1, int(max_concurrency))
        self.max_output_bytes = int(max_output_bytes)
        self._semaphore = threading.BoundedSemaphore(self.max_concurrency)
        self._lock = threading.Lock()
        self._active: int = 0

    # -- introspection ------------------------------------------------------- #
    @property
    def active(self) -> int:
        with self._lock:
            return self._active

    def resolve(self, tool: str) -> ExternalToolSpec:
        """Return the allowlist entry for ``tool`` or raise."""
        spec = TOOL_ALLOWLIST.get(str(tool).strip().lower())
        if spec is None:
            raise ExternalToolNotAllowed(
                f"external program {tool!r} is not on the execution allowlist"
            )
        return spec

    def is_installed(self, tool: str) -> bool:
        try:
            spec = self.resolve(tool)
        except ExternalToolNotAllowed:
            return False
        return _resolve(spec) is not None

    # -- execution ------------------------------------------------------------ #
    def run(
        self,
        tool: str,
        args: Sequence[str],
        *,
        workdir: Optional[str | Path] = None,
        timeout: float = 120.0,
        env: Optional[Dict[str, str]] = None,
        input_files: Optional[Dict[str, str]] = None,
        keep_workdir: bool = False,
    ) -> Dict[str, Any]:
        """Run an allowlisted program with an explicit argv.

        Returns a structured result; raises :class:`ExternalToolUnavailable`
        when the program is missing so callers fall back honestly rather than
        pretending the computation happened.
        """
        spec = self.resolve(tool)
        # Argument hygiene: every argv entry must be a plain string, and the
        # first entry is the resolved executable -- never a caller path.
        argv = [str(a) for a in args]
        executable = _resolve(spec)
        if executable is None:
            raise ExternalToolUnavailable(
                f"{spec.description} ({spec.executable}) is not installed; "
                f"set CHEMML_{spec.key.upper()}_PATH to point at it"
            )

        owned_dir: Optional[Path] = None
        if workdir is None:
            owned_dir = Path(tempfile.mkdtemp(prefix=f"chemml_{spec.key}_"))
            directory = owned_dir
        else:
            directory = Path(workdir)
            directory.mkdir(parents=True, exist_ok=True)

        if input_files:
            for name, content in input_files.items():
                target = directory / Path(name).name  # never escape the dir
                target.write_text(content, encoding="utf-8")

        environment = dict(os.environ)
        environment.setdefault("LC_ALL", "C")
        if env:
            environment.update(env)

        self._semaphore.acquire()
        with self._lock:
            self._active += 1
        try:
            try:
                completed = subprocess.run(
                    [executable, *argv],
                    cwd=str(directory),
                    capture_output=True,
                    text=True,
                    timeout=float(timeout),
                    env=environment,
                    check=False,
                    shell=False,  # explicit: never a shell string
                )
            except subprocess.TimeoutExpired as exc:
                raise ExternalToolError(
                    f"{spec.key} timed out after {timeout:.1f} s"
                ) from exc
            except FileNotFoundError as exc:
                raise ExternalToolUnavailable(
                    f"Executable not found: {executable} ({exc})"
                ) from exc

            stdout = (completed.stdout or "")[: self.max_output_bytes]
            stderr = (completed.stderr or "")[: self.max_output_bytes]
            result = {
                "tool": spec.key,
                "command": [Path(executable).name, *argv],
                "returncode": int(completed.returncode),
                "success": int(completed.returncode) == 0,
                "workdir": str(directory),
                "stdout": stdout,
                "stderr": stderr,
                "backend": f"external:{Path(executable).name}",
            }
        finally:
            with self._lock:
                self._active -= 1
            self._semaphore.release()
            if owned_dir is not None and not keep_workdir:
                shutil.rmtree(owned_dir, ignore_errors=True)
        return result


#: Process-wide controlled runner (bounded concurrency).
runner = ControlledRunner()

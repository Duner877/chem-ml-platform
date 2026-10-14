"""Helpers to invoke third-party scientific programs.

The computational chemistry nodes delegate the heavy lifting to the real
programs (ORCA, Gaussian, Psi4, CP2K, GROMACS, LAMMPS, OpenMM, VASP, Quantum
ESPRESSO).  This module centralises:

* executable discovery (``PATH`` or an explicit override),
* input-file generation inside a scratch directory,
* running the process with a timeout and capturing stdout/stderr,
* parsing the most important numbers out of the output.

When the executable is missing the callers fall back to the internal engines
in :mod:`simulations.eht`, :mod:`simulations.lj_md` and
:mod:`simulations.tight_binding`; the fallback is always reported in the node
metadata so a workflow result is never silently downgraded.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from workflow_engine.errors import ExternalToolError

__all__ = [
    "ToolResult",
    "find_executable",
    "run_tool",
    "write_input",
    "parse_key_value_output",
    "extract_float",
]


@dataclass
class ToolResult:
    """Outcome of an external program invocation."""

    command: List[str]
    returncode: int
    stdout: str = ""
    stderr: str = ""
    workdir: str = ""
    success: bool = field(default=False)
    metrics: Dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "command": list(self.command),
            "returncode": self.returncode,
            "success": self.success,
            "workdir": self.workdir,
            "metrics": dict(self.metrics),
            "stdout_tail": self.stdout[-4000:],
            "stderr_tail": self.stderr[-2000:],
        }


def find_executable(name: str, override: str | None = None) -> Optional[str]:
    """Locate ``name`` honouring an explicit path / environment override."""
    candidates = [
        override,
        os.environ.get(f"{name.upper()}_PATH"),
        os.environ.get(f"{name.upper()}_EXE"),
        shutil.which(name),
    ]
    for candidate in candidates:
        if not candidate:
            continue
        path = Path(candidate)
        if path.is_file() and os.access(str(path), os.X_OK):
            return str(path)
        if path.is_dir():
            for inner in (path / name, path / f"{name}.exe"):
                if inner.is_file():
                    return str(inner)
    return None


def write_input(directory: str | Path, filename: str, content: str) -> Path:
    """Write ``content`` into ``directory/filename`` and return the path."""
    path = Path(directory) / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def run_tool(
    command: Sequence[str],
    workdir: str | Path,
    timeout: float = 120.0,
    env: Optional[Dict[str, str]] = None,
) -> ToolResult:
    """Run ``command`` inside ``workdir`` and capture its output."""
    directory = Path(workdir)
    directory.mkdir(parents=True, exist_ok=True)
    environment = dict(os.environ)
    if env:
        environment.update(env)
    try:
        completed = subprocess.run(
            list(command),
            cwd=str(directory),
            capture_output=True,
            text=True,
            timeout=float(timeout),
            env=environment,
            check=False,
        )
    except FileNotFoundError as exc:
        raise ExternalToolError(f"Executable not found: {command[0]} ({exc})") from exc
    except subprocess.TimeoutExpired as exc:
        raise ExternalToolError(
            f"{command[0]} timed out after {timeout:.1f} s"
        ) from exc
    return ToolResult(
        command=list(command),
        returncode=int(completed.returncode),
        stdout=completed.stdout or "",
        stderr=completed.stderr or "",
        workdir=str(directory),
        success=int(completed.returncode) == 0,
    )


def parse_key_value_output(text: str, separators: Sequence[str] = (":", "=")) -> Dict[str, str]:
    """Extract simple ``key: value`` lines from a program output."""
    parsed: Dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        for separator in separators:
            if separator in stripped:
                key, value = stripped.split(separator, 1)
                key, value = key.strip(), value.strip()
                if key and value:
                    parsed[key] = value
                break
    return parsed


def extract_float(text: str, pattern: str, group: int = 1) -> Optional[float]:
    """Return the first float captured by ``pattern`` in ``text``."""
    import re

    match = re.search(pattern, text)
    if match is None:
        return None
    try:
        return float(match.group(group))
    except (TypeError, ValueError):
        return None

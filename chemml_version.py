"""Single source of truth for the Chem ML Platform version.

Every artefact -- the Python backend, the node registry, the Electron shell,
the frontend bundle, the release scripts and the documentation -- must read the
version from *this one file*.  v0.7.2 (spec task P0-04) makes this a release
blocker: a version that appears in two places eventually disagrees with itself,
and a release report that quotes a version no artefact carries is not traceable.

Usage::

    from chemml_version import __version__, VERSION, build_metadata

    print(__version__)        # "0.7.2"
    print(VERSION)            # backwards-compatible alias
    print(build_metadata())   # {"version": ..., "commit": ..., "built_at": ...}

The ``package.json`` files cannot import Python, so ``scripts/version.py
--write`` stamps them and ``--check`` proves they still agree with this file.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any, Dict

__all__ = [
    "__version__",
    "VERSION",
    "__codename__",
    "build_metadata",
    "git_commit",
]

#: The product version.  Bump here and nowhere else.
__version__ = "0.7.2"

#: Backwards-compatible alias (older modules read ``VERSION``).
VERSION = __version__

#: Human-readable release codename (spec: v0.7.2 -- Trusted Delivery Release).
__codename__ = "Trusted Delivery Release"

ROOT = Path(__file__).resolve().parent


def git_commit(short: bool = True) -> str:
    """Return the current Git commit hash, or ``"unknown"`` outside a repo.

    A release report must be traceable to a commit (spec §9).  When the source
    tree is not a Git checkout the honest answer is ``"unknown"`` -- never a
    fabricated hash.
    """
    override = os.environ.get("CHEMML_BUILD_COMMIT", "").strip()
    if override:
        return override
    args = ["git", "rev-parse", "--short", "HEAD"] if short else ["git", "rev-parse", "HEAD"]
    try:
        out = subprocess.run(
            args,
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    if out.returncode != 0:
        return "unknown"
    return (out.stdout or "").strip() or "unknown"


def build_metadata() -> Dict[str, Any]:
    """Version + provenance of the artefacts produced from this tree."""
    import sys

    return {
        "version": __version__,
        "codename": __codename__,
        "commit": git_commit(),
        "built_at": os.environ.get("CHEMML_BUILD_TIME", "") or "",
        "python": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
    }

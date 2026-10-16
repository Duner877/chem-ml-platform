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

import json
import os
import subprocess
from pathlib import Path
from typing import Any, Dict

__all__ = [
    "__version__",
    "VERSION",
    "__codename__",
    "build_metadata",
    "build_stamp",
    "git_commit",
    "read_build_info",
]

#: The product version.  Bump here and nowhere else.
__version__ = "0.7.3"

#: Backwards-compatible alias (older modules read ``VERSION``).
VERSION = __version__

#: Human-readable release codename (spec: v0.7.2 -- Trusted Delivery Release).
__codename__ = "Trusted Delivery Release"

ROOT = Path(__file__).resolve().parent

#: Build stamp shipped inside the source archive by ``scripts/package.py``.
#:
#: v0.7.2 fix (ISSUE-21): an extracted archive is not a Git checkout, so
#: ``git_commit()`` used to answer ``"unknown"`` for every distributed copy --
#: including the ones the release report claims are traceable to a commit.  The
#: packaging step therefore records the commit *at build time* alongside the
#: tree, and this is the last link in the resolution chain.
BUILD_INFO_PATH = ROOT / "BUILD_INFO.json"


def read_build_info() -> Dict[str, Any]:
    """The packaged build stamp, or ``{}`` when this is a working tree."""
    try:
        data = json.loads(BUILD_INFO_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _git_repo_is_this_tree() -> bool:
    """True only when ``ROOT`` itself is the top level of a Git checkout.

    ``git rev-parse`` succeeds for *any* ancestor repository, not just this
    one.  Without this guard a distributed copy extracted inside an unrelated
    checkout -- or a test fixture parked under the repo's ``output/`` -- would
    report that repository's HEAD as its own build commit.  That is a
    fabricated provenance, which is the one thing this module must never do.
    """
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    if out.returncode != 0:
        return False
    top = (out.stdout or "").strip()
    if not top:
        return False
    try:
        return Path(top).resolve() == ROOT.resolve()
    except OSError:
        return False


def git_commit(short: bool = True) -> str:
    """Return the commit this tree came from, or ``"unknown"``.

    Resolution order:

    1. ``CHEMML_BUILD_COMMIT`` -- an explicit override for hermetic builds;
    2. ``git rev-parse HEAD`` -- a live checkout is always the best answer,
       but only when this directory *is* that checkout (see
       :func:`_git_repo_is_this_tree`);
    3. ``BUILD_INFO.json`` -- the stamp recorded when the archive was packaged;
    4. ``"unknown"``.

    A release report must be traceable to a commit (spec §9), and when none of
    the above is available the honest answer is ``"unknown"`` -- never a
    fabricated hash.  Step 3 exists so that an *extracted* copy can answer this
    question too, instead of weakening its own provenance record.
    """
    override = os.environ.get("CHEMML_BUILD_COMMIT", "").strip()
    if override:
        return override
    if _git_repo_is_this_tree():
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
            out = None
        if out is not None and out.returncode == 0:
            found = (out.stdout or "").strip()
            if found:
                return found
    info = read_build_info()
    recorded = str(
        info.get("commit_short" if short else "commit", "") or ""
    ).strip()
    return recorded or "unknown"


def commit_source() -> str:
    """Where :func:`git_commit` got its answer -- never a guess."""
    if os.environ.get("CHEMML_BUILD_COMMIT", "").strip():
        return "env:CHEMML_BUILD_COMMIT"
    if _git_repo_is_this_tree():
        return "git"
    if read_build_info().get("commit"):
        return "BUILD_INFO.json"
    return "unknown"


def build_stamp(produced_by: str) -> Dict[str, Any]:
    """The ``BUILD_INFO.json`` payload, shared by every packaging step.

    Kept here so the source archive (``scripts/package.py``) and the Electron
    shell payload (``scripts/refresh_desktop_payload.py``) stamp *the same*
    fields from the *same* code.  When they diverge, one of them is lying about
    provenance -- which is the failure mode this module exists to prevent.
    """
    from datetime import datetime, timezone

    def _git(*args: str) -> str:
        if not _git_repo_is_this_tree():
            return ""
        try:
            out = subprocess.run(
                ["git", *args], cwd=str(ROOT), capture_output=True, text=True, timeout=10
            )
        except (OSError, subprocess.SubprocessError):
            return ""
        return (out.stdout or "").strip() if out.returncode == 0 else ""

    commit = _git("rev-parse", "HEAD")
    if not commit:
        # Repackaging a distributed copy (no Git of its own): carry the
        # original stamp forward instead of downgrading it to "unknown".
        previous = read_build_info()
        commit = str(previous.get("commit", "") or "").strip() or "unknown"
    return {
        "version": __version__,
        "codename": __codename__,
        "commit": commit,
        "commit_short": commit[:7] if commit else "unknown",
        "branch": _git("rev-parse", "--abbrev-ref", "HEAD"),
        "dirty": bool(_git("status", "--porcelain")),
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "produced_by": produced_by,
        "note": (
            "Generated at packaging time and injected next to the code it "
            "describes. `dirty: true` means the tree had uncommitted changes, "
            "so the commit identifies the base, not the exact content."
        ),
    }


def build_metadata() -> Dict[str, Any]:
    """Version + provenance of the artefacts produced from this tree."""
    import sys

    info = read_build_info()
    return {
        "version": __version__,
        "codename": __codename__,
        "commit": git_commit(),
        "commit_source": commit_source(),
        "built_at": os.environ.get("CHEMML_BUILD_TIME", "") or str(info.get("built_at", "") or ""),
        "python": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
    }

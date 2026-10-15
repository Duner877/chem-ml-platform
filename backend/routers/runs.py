"""Run history and artefact download."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

router = APIRouter(prefix="/runs", tags=["runs"])

#: Everything a run writes lives below this directory.
ARTIFACT_ROOTS = [
    ROOT / "output" / "api_runs",
    ROOT / "output" / "demo_runs",
    ROOT / "output" / "artifacts",
]


def _iter_runs() -> List[Dict[str, Any]]:
    """Return one entry per run directory found under the artefact roots."""
    runs: List[Dict[str, Any]] = []
    for base in ARTIFACT_ROOTS:
        if not base.exists():
            continue
        for run_dir in sorted(base.glob("**/run_*"), reverse=True):
            # POSIX separators: these paths are handed to the browser as URL
            # segments, and a Windows "output\runs\x.html" is not a valid one.
            artifacts = sorted(
                p.relative_to(ROOT).as_posix()
                for p in run_dir.rglob("*")
                if p.is_file()
            )
            runs.append(
                {
                    "run_id": run_dir.name,
                    "workflow": run_dir.parent.name,
                    "path": run_dir.relative_to(ROOT).as_posix(),
                    "artifacts": artifacts,
                }
            )
    return runs


@router.get("")
async def list_runs() -> List[Dict[str, Any]]:
    """Every executed run with its artefacts, newest first."""
    return _iter_runs()


def _registered_artifact_root(candidate: Path) -> bool:
    """True when ``candidate`` lives inside one of the registered artifact roots.

    v0.7 note (spec section 8.2): containment is checked with
    ``Path.relative_to`` on *resolved* paths -- never with string prefix
    comparison, which ``../``-style escapes can defeat.
    """
    for base in ARTIFACT_ROOTS:
        base_r = base.resolve()
        try:
            candidate.resolve().relative_to(base_r)
        except ValueError:
            continue
        return True
    return False


@router.get("/artifacts/{file_path:path}")
async def download_artifact(file_path: str) -> FileResponse:
    """Download a single artefact (report, CSV, JSON, PNG, ...).

    Only files inside the registered run/artifact roots are downloadable;
    path traversal attempts are rejected with 403.
    """
    candidate = (ROOT / file_path).resolve()
    if not _registered_artifact_root(candidate):
        raise HTTPException(status_code=403, detail="path is outside the registered artifact roots")
    if not candidate.is_file():
        raise HTTPException(status_code=404, detail=f"artefact {file_path!r} not found")
    return FileResponse(str(candidate), filename=candidate.name)

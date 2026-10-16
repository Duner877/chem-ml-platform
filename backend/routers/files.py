"""Local filesystem browsing for the file-parameter picker (v0.7.2).
 *
 * The editor lets the user click a ``file`` parameter and pick a measurement
 * from disk.  In the packaged desktop build that is a *native* dialog raised by
 * the Electron main process, which needs no HTTP surface at all.  The browser
 * launcher (``start-platform.bat``) has no such dialog, and a browser
 * ``<input type=file>`` deliberately hides the path -- so this router is the
 * fallback that lets the same UI work there.
 *
:Security
---------
This is the most sensitive read-only route in the platform: it enumerates
arbitrary directories.  The mitigations are deliberate and layered:

* **Authentication.**  ``GET /api/files/browse`` is classified as ``READ`` in
  :data:`backend.security.ROUTE_RULES`, so a packaged (release) build demands
  the per-session token.  A release build that somehow lost its token fails
  closed, so an unauthenticated caller gets 401, never a listing.
* **No writes.**  Nothing here creates, moves or deletes a file; the router only
  calls ``iterdir`` / ``stat``.
* **Bounded listing.**  At most :data:`MAX_ENTRIES` entries are returned, hidden
  dot-entries are skipped and symlinks are *not* followed out of the listing.
* **Honest about what it is.**  ``/api/security/status`` already reports the
  posture, and this route is only reachable on the loopback interface the
  backend binds to.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException, Query

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

router = APIRouter(prefix="/files", tags=["files"])

#: Hard cap on entries returned per listing (a folder with 50k files is not a
#: picker, it is a mistake).
MAX_ENTRIES = 500

#: Extensions the importer nodes can actually open.  Everything else is listed
#: but flagged, so the picker can grey it out instead of hiding real data.
READABLE_SUFFIXES = {
    ".mzml", ".mzxml", ".mgf", ".msp", ".xy", ".raw", ".d",
    ".csv", ".tsv", ".txt", ".json",
    ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp",
    ".sdf", ".mol", ".mol2", ".smi", ".smiles", ".cif", ".xyz", ".vasp", ".poscar",
}


def _is_hidden(name: str) -> bool:
    return name.startswith(".")


def _resolve(raw: str) -> Path:
    """Resolve a browse request to an existing directory.

    An empty path means "start where the user usually works": the repository
    root when it exists, otherwise the user's home directory.  A *file* path is
    accepted too and its parent is browsed, because that is what happens when a
    parameter already holds a path and the user clicks Browse again.
    """
    text = (raw or "").strip()
    if not text:
        for candidate in (ROOT, Path.home()):
            if candidate.is_dir():
                return candidate
        return ROOT

    path = Path(text).expanduser()
    # A repo-relative path ("datasets/demo/x.csv") is what every bundled
    # workflow stores, so resolve those against the repository root first.
    if not path.is_absolute():
        candidate = ROOT / text
        if candidate.exists():
            path = candidate
    try:
        path = path.resolve()
    except OSError as exc:  # pragma: no cover - unresolvable path
        raise HTTPException(status_code=400, detail=f"cannot resolve path: {text}") from exc

    if path.is_file():
        path = path.parent
    if not path.is_dir():
        raise HTTPException(status_code=404, detail=f"not a directory: {text}")
    return path


@router.get("/browse")
async def browse(
    path: str = Query("", description="directory to list; empty starts at the repo root"),
) -> Dict[str, Any]:
    """List one directory: sub-directories plus files, with the parent path."""
    target = _resolve(path)

    directories: List[Dict[str, Any]] = []
    files: List[Dict[str, Any]] = []
    truncated = False

    try:
        with os.scandir(target) as iterator:
            for index, entry in enumerate(iterator):
                if index >= MAX_ENTRIES:
                    truncated = True
                    break
                if _is_hidden(entry.name):
                    continue
                try:
                    is_dir = entry.is_dir(follow_symlinks=False)
                except OSError:
                    continue
                if is_dir:
                    directories.append({"name": entry.name, "path": str(target / entry.name)})
                    continue
                try:
                    size = entry.stat(follow_symlinks=False).st_size
                except OSError:
                    size = None
                files.append(
                    {
                        "name": entry.name,
                        "path": str(target / entry.name),
                        "size": size,
                        "readable": Path(entry.name).suffix.lower() in READABLE_SUFFIXES,
                    }
                )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=f"permission denied: {target}") from exc
    except OSError as exc:
        raise HTTPException(status_code=400, detail=f"cannot list {target}: {exc}") from exc

    directories.sort(key=lambda item: item["name"].lower())
    files.sort(key=lambda item: item["name"].lower())

    parent = str(target.parent) if target.parent != target else ""
    return {
        "path": str(target),
        "name": target.name or str(target),
        "parent": parent,
        "directories": directories[:MAX_ENTRIES],
        "files": files[:MAX_ENTRIES],
        "truncated": truncated,
    }


@router.get("/exists")
async def exists(path: str = Query("", description="file path to probe")) -> Dict[str, Any]:
    """Report whether a path exists and whether it is a directory.

    The picker uses this to tell the user *honestly* that a typed path cannot
    be found, instead of letting the run fail later with a node error.
    """
    text = (path or "").strip()
    if not text:
        return {"path": "", "exists": False, "is_dir": False, "size": None}
    candidate = Path(text).expanduser()
    if not candidate.is_absolute():
        relative = ROOT / text
        if relative.exists():
            candidate = relative
    try:
        resolved = candidate.resolve()
    except OSError:
        return {"path": text, "exists": False, "is_dir": False, "size": None}
    if not resolved.exists():
        return {"path": str(resolved), "exists": False, "is_dir": False, "size": None}
    try:
        stat = resolved.stat()
        size = None if resolved.is_dir() else stat.st_size
    except OSError:
        size = None
    return {
        "path": str(resolved),
        "exists": True,
        "is_dir": resolved.is_dir(),
        "size": size,
    }
"""Secure file upload / workspace browsing API (v0.7.1 -- spec sections 8, 22-C).

Every byte of user-supplied data enters the platform through this router and
its backing :class:`~storage.workspace.WorkspaceService`:

* uploads are read in fixed-size chunks and written straight to a temp file
  (P1-01) -- an oversized payload is aborted the moment it crosses the byte
  budget instead of being buffered completely in memory first;
* concurrent uploads are capped by a semaphore (P1-09);
* archives are extracted with zip-slip, zip-bomb, entry-count and depth
  limits;
* directory listings are root-relative and cannot escape;
* responses never expose absolute server paths (only category-relative ones).
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from storage import StorageLimits, WorkspaceService  # noqa: E402
from storage.paths import SafePathError  # noqa: E402
from storage.service import UploadLimitExceeded  # noqa: E402
from workflow_engine.error_model import ErrorCode, PlatformError  # noqa: E402

router = APIRouter(prefix="/storage", tags=["storage"])

#: Read size for streamed uploads (never holds more than this in memory).
CHUNK_SIZE = 1024 * 1024  # 1 MiB

#: Single shared workspace instance (backend process wide).
workspace = WorkspaceService(ROOT / "workspace", StorageLimits())

#: Caps the number of simultaneous uploads so a burst cannot exhaust memory
#: or the disk (P1-09).  Lazily bound to the running loop.
_upload_semaphore: Optional[asyncio.Semaphore] = None


def _uploads_guard() -> asyncio.Semaphore:
    global _upload_semaphore
    if _upload_semaphore is None:
        _upload_semaphore = asyncio.Semaphore(workspace.limits.max_concurrent_uploads)
    return _upload_semaphore


#: Extension sets used for the coarse format detection shown in the UI.
FORMAT_HINTS: Dict[str, List[str]] = {
    "mass spectrometry": [".mzml", ".mzxml", ".mgf", ".msp", ".xy", ".raw"],
    "nmr": [".jcamp", ".dx", ".fid"],
    "chemical structure": [".smi", ".smiles", ".sdf", ".mol", ".mol2", ".xyz"],
    "crystal structure": [".cif", ".poscar", ".vasp"],
    "scientific image": [".tif", ".tiff", ".png", ".jpg", ".jpeg"],
    "scientific array": [".csv", ".tsv", ".txt", ".npy", ".npz", ".h5", ".hdf5"],
}

UNIVERSAL_FORMATS = {
    ".csv", ".tsv", ".txt", ".json", ".png", ".jpg", ".jpeg", ".tif", ".tiff",
    ".npy", ".npz", ".h5", ".hdf5", ".smi", ".smiles", ".xyz",
}

#: Categories a user may upload into (never ``runs`` or ``cache``).
UPLOADABLE = {"raw_data", "uploads", "models"}


def _detect_format(filename: str) -> Dict[str, Any]:
    """Coarse format classification for the upload confirmation UI."""
    suffix = Path(filename).suffix.lower()
    detected = [name for name, exts in FORMAT_HINTS.items() if suffix in exts]
    return {
        "suffix": suffix,
        "detected_types": detected,
        "format_class": (
            "Universal Format" if suffix in UNIVERSAL_FORMATS
            else "Vendor Native Format" if detected
            else "Unknown"
        ),
        "vendor_warning": (
            suffix in {".raw"}  # e.g. Thermo RAW: identification != parsing
        ),
    }


class StorageEntry(BaseModel):
    name: str
    type: str
    path: str
    size: Optional[int] = None


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, SafePathError):
        unified = PlatformError.storage_security(str(exc))
        status = 413 if isinstance(exc, UploadLimitExceeded) else 403
    else:
        unified = PlatformError.validation(str(exc))
        status = 400
    payload = unified.to_dict()
    return HTTPException(status_code=status, detail=payload)


@router.get("/limits")
async def limits() -> Dict[str, Any]:
    """The upload policy so the UI can pre-validate and explain rejections."""
    lim = workspace.limits
    return {
        "max_upload_bytes": lim.max_upload_bytes,
        "max_archive_bytes": lim.max_archive_bytes,
        "max_archive_uncompressed": lim.max_archive_uncompressed,
        "max_archive_entries": lim.max_archive_entries,
        "max_archive_depth": lim.max_archive_depth,
        "max_concurrent_uploads": lim.max_concurrent_uploads,
        "upload_timeout_s": lim.upload_timeout_s,
        "chunk_size": CHUNK_SIZE,
        "uploadable_categories": sorted(UPLOADABLE),
    }


@router.get("/categories")
async def categories() -> Dict[str, Any]:
    """Whitelisted workspace categories with their absolute-less layout."""
    layout = workspace.layout()
    return {
        "categories": sorted(layout),
        "usage_bytes": workspace.total_disk_usage(),
    }


@router.post("/upload/{category}")
async def upload_file(category: str, file: UploadFile = File(...)) -> Dict[str, Any]:
    """Stream one file into a whitelisted workspace category (chunked)."""
    if category not in UPLOADABLE:
        raise HTTPException(
            status_code=400,
            detail={
                "code": ErrorCode.VALIDATION_ERROR.value,
                "message": f"category {category!r} is not uploadable; "
                           f"use one of {sorted(UPLOADABLE)}",
            },
        )
    service = workspace.category(category)
    semaphore = _uploads_guard()
    async with semaphore:
        try:
            with service.begin_upload("", file.filename or "") as session:
                while True:
                    chunk = await file.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    session.write(chunk)
                stored = session.commit()
        except SafePathError as exc:
            raise _http_error(exc) from exc
        finally:
            await file.close()
    stored_dict = stored.to_dict()
    stored_dict["category"] = category
    return {**stored_dict, "format": _detect_format(file.filename or "")}


@router.post("/extract/{category}")
async def extract_archive(category: str, file: UploadFile = File(...)) -> Dict[str, Any]:
    """Stream-upload an archive, then extract it with zip-slip/bomb limits."""
    if category not in UPLOADABLE:
        raise HTTPException(
            status_code=400,
            detail={
                "code": ErrorCode.VALIDATION_ERROR.value,
                "message": f"category {category!r} is not uploadable",
            },
        )
    service = workspace.category(category)
    semaphore = _uploads_guard()
    async with semaphore:
        staging = Path(tempfile.mkdtemp(prefix="chemml_zip_"))
        archive_path = staging / "upload.zip"
        try:
            with archive_path.open("wb") as handle:
                while True:
                    chunk = await file.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    handle.write(chunk)
            await file.close()
            try:
                stored = service.extract_zip(archive_path, "")
            except SafePathError as exc:
                raise _http_error(exc) from exc
        finally:
            # always remove the transient staging dir (no residue, P1-09)
            for child in staging.glob("*"):
                try:
                    child.unlink()
                except OSError:
                    pass
            try:
                staging.rmdir()
            except OSError:
                pass
    return {
        "category": category,
        "extracted": len(stored),
        "files": [
            {**item.to_dict(), "category": category} for item in stored[:200]
        ],
    }


@router.get("/list/{category}/{path:path}")
@router.get("/list/{category}")
async def list_directory(category: str, path: str = "") -> List[Dict[str, Any]]:
    """List a directory inside a whitelisted category (safe, non-recursive)."""
    try:
        return workspace.category(category).list_dir(path)
    except (SafePathError, KeyError) as exc:
        raise _http_error(exc) from exc


@router.delete("/file/{category}/{path:path}")
async def delete_file(category: str, path: str) -> Dict[str, Any]:
    """Delete a file inside a whitelisted category."""
    try:
        removed = workspace.category(category).remove(path)
    except (SafePathError, KeyError) as exc:
        raise _http_error(exc) from exc
    return {"removed": removed, "path": path}

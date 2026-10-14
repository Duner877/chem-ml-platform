"""Scientific data layer endpoints: ingest files and browse the catalog."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from data_layer.catalog import CATALOG_PATH, get_catalog

router = APIRouter(prefix="/data", tags=["data"])


def _catalog():
    """Resolve the catalog per request so ``CHEMML_CATALOG`` is honoured."""
    return get_catalog()


class IngestPayload(BaseModel):
    path: str = Field(description="file, directory or dataset id to ingest")
    tags: List[str] = Field(default_factory=list)
    note: str = ""
    embed: bool = True


@router.get("/catalog")
async def list_catalog(
    query: str = "",
    type: str = "",
    source: str = "",
    tag: str = "",
    limit: int = 50,
    with_embedding: bool = False,
) -> Dict[str, Any]:
    """Search the scientific data catalog."""
    catalog = _catalog()
    entries = catalog.search(
        query,
        type=type,
        source=source,
        tag=tag,
        limit=limit,
        with_embedding=with_embedding,
    )
    return {"count": len(entries), "entries": entries, "stats": catalog.stats()}


@router.get("/catalog/{entry_id}")
async def read_entry(entry_id: str) -> Dict[str, Any]:
    """One catalog entry by catalog id or data id."""
    entry = _catalog().get(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"unknown catalog entry {entry_id!r}")
    return entry


@router.get("/stats")
async def stats() -> Dict[str, Any]:
    """Catalog counts and histograms."""
    return {"path": str(CATALOG_PATH), **_catalog().stats()}


@router.post("/ingest")
async def ingest(payload: IngestPayload) -> Dict[str, Any]:
    """Ingest a path through the data layer and index every object produced."""
    target = payload.path.strip()
    if not target:
        raise HTTPException(status_code=422, detail="path must not be empty")
    catalog = _catalog()
    try:
        records = catalog.ingest(
            target,
            tags=payload.tags,
            note=payload.note,
            embed=payload.embed,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - surfaced as 400
        raise HTTPException(
            status_code=400, detail=f"{type(exc).__name__}: {exc}"
        ) from exc
    return {"count": len(records), "entries": records, "stats": catalog.stats()}


@router.get("/quality")
async def quality() -> Dict[str, Any]:
    """Dataset metadata quality report (v0.7.1 task G / §P1-07).

    Surfaces metadata problems (family/content mismatch, missing units,
    checksum drift, duplicate files) *before* a user analyses the data.
    """
    from data_layer.quality import quality_report

    return quality_report()


@router.get("/datasets")
async def datasets() -> List[Dict[str, Any]]:
    """Shipped dataset files that can be ingested from the GUI."""
    root = Path(__file__).resolve().parents[2] / "datasets"
    found: List[Dict[str, Any]] = []
    if root.is_dir():
        for path in sorted(root.rglob("*")):
            if path.is_file() and path.suffix.lower() in {
                ".xy", ".csv", ".tsv", ".txt", ".json", ".mzml", ".spc", ".jdx",
                ".dx", ".cif", ".png", ".jpg", ".tif", ".d",
            }:
                found.append(
                    {
                        "path": path.relative_to(root.parents[0]).as_posix(),
                        "name": path.name,
                        "size": path.stat().st_size,
                    }
                )
    return found[:300]

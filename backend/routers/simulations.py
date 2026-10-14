"""Simulation runtime endpoints: back-end catalogue and job queue."""

from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from simulation_runtime import describe as describe_backends
from simulation_runtime.jobs import jobs

router = APIRouter(prefix="/simulations", tags=["simulations"])

#: Families the runtime understands.
FAMILIES = ["quantum", "md", "materials"]


class SimulationPayload(BaseModel):
    family: str = Field(description="quantum | md | materials")
    backend: str = ""
    smiles: str = ""
    formula: str = ""
    params: Dict[str, Any] = Field(default_factory=dict)
    force_internal: bool = False
    timeout: float = 600.0
    wait: bool = True


def _build_system(payload: SimulationPayload) -> Any:
    """Turn the request into a Molecule / Material the runtime understands."""
    from nodes._helpers import build_material, build_molecule

    if payload.smiles.strip():
        return build_molecule(payload.smiles.strip(), name=payload.smiles.strip())
    if payload.formula.strip():
        return build_material(payload.formula.strip(), name=payload.formula.strip())
    raise HTTPException(
        status_code=422, detail="provide either 'smiles' or 'formula'"
    )


@router.get("/families")
async def families() -> List[str]:
    """Simulation families served by the runtime."""
    return list(FAMILIES)


@router.get("/backends")
async def backends() -> Dict[str, Any]:
    """Every registered back-end with its availability."""
    items = describe_backends()
    return {
        "count": len(items),
        "available": [item["name"] for item in items if item["available"]],
        "backends": items,
    }


@router.get("/tools")
async def external_tools() -> Dict[str, Any]:
    """External-software compatibility report (v0.7.1 spec §P2-09).

    Lists every program the platform is allowed to launch, whether it is
    installed, its resolved path, version and licence terms.  Nothing is
    fabricated: a missing program is reported as ``installed: false``.
    """
    from simulations.controlled import describe_tools

    items = describe_tools()
    return {
        "count": len(items),
        "installed": [item["key"] for item in items if item["installed"]],
        "missing": [item["key"] for item in items if not item["installed"]],
        "tools": items,
    }


@router.post("/run")
async def run(payload: SimulationPayload) -> Dict[str, Any]:
    """Submit a simulation; wait for it (``wait=true``) or return the job."""
    family = payload.family.strip().lower()
    if family not in FAMILIES:
        raise HTTPException(status_code=422, detail=f"unknown family {family!r}")
    system = _build_system(payload)
    params = dict(payload.params)
    params["force_internal"] = payload.force_internal
    params["timeout"] = payload.timeout
    try:
        if payload.wait:
            job = jobs.run_now(family, system, backend=payload.backend, **params)
        else:
            job = jobs.submit(family, system, backend=payload.backend, **params)
    except Exception as exc:  # noqa: BLE001 - surfaced as 400
        raise HTTPException(
            status_code=400, detail=f"{type(exc).__name__}: {exc}"
        ) from exc
    return job.to_dict()


@router.get("/jobs")
async def list_jobs(limit: int = 50, family: str = "") -> Dict[str, Any]:
    """Recent simulation jobs, newest first."""
    return {
        "count": len(jobs.list(limit=limit, family=family)),
        "stats": jobs.stats(),
        "jobs": jobs.list(limit=limit, family=family),
    }


@router.get("/jobs/{job_id}")
async def read_job(job_id: str) -> Dict[str, Any]:
    """One job by id."""
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"unknown job {job_id!r}")
    return job

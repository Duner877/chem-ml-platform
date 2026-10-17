"""Workflow CRUD, validation and execution endpoints."""

from __future__ import annotations

import json
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from backend.run_registry import may_subscribe, register_run
from backend.security import PRINCIPAL_DEV, current_principal, load_security_config
from workflow_engine.engine import WorkflowEngine
from workflow_engine.errors import WorkflowValidationError
from workflow_engine.events import Event
from workflow_engine.workflow import Workflow

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

router = APIRouter(prefix="/workflows", tags=["workflows"])

#: Directory where workflows created through the API are persisted.
WORKFLOW_DIR = ROOT / "workflows"
RUN_DIR = ROOT / "output" / "api_runs"

#: In-memory event buffers for every finished / running run, so that a client
#: can poll the event history over plain HTTP as well as over WebSocket.
EVENT_BUFFERS: Dict[str, List[Dict[str, Any]]] = {}


def _principal_of(http_request: Request) -> str:
    """The caller's principal, or ``dev`` when authentication is disabled."""
    principal = current_principal(http_request)
    if principal:
        return principal
    return PRINCIPAL_DEV if not load_security_config().enforced else ""


# --------------------------------------------------------------------------- #
# request / response models
# --------------------------------------------------------------------------- #
class WorkflowPayload(BaseModel):
    """A workflow graph as produced by the React Flow editor."""

    name: str = "Untitled Workflow"
    description: str = ""
    nodes: List[Dict[str, Any]] = Field(default_factory=list)
    edges: List[Dict[str, Any]] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class RunRequest(BaseModel):
    """Optional per-node input injection for a workflow run."""

    inputs: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    save: bool = Field(False, description="persist the workflow before running")


class RunResponse(BaseModel):
    run_id: str
    workflow: str
    status: str
    nodes: int
    duration_ms: float
    records: Dict[str, Any] = Field(default_factory=dict)
    artifacts: List[str] = Field(default_factory=list)
    errors: List[Dict[str, str]] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _engine(origin: str = "manual", approved_node_types: Optional[List[str]] = None) -> WorkflowEngine:
    """A fresh engine bound to the populated global registry.

    v0.7.3 (audit P0-3): ``origin`` and ``approved_node_types`` reach the
    engine's tool guard, so a run started through this REST endpoint is
    classified the same way the agent path classifies it.  The default
    (``"manual"``) is the authenticated local user pressing Run -- their own
    decision -- which is why it does not require per-node approval.
    """
    from nodes.loader import get_registry

    return WorkflowEngine(
        registry=get_registry(),
        workdir=RUN_DIR,
        max_workers=4,
        use_cache=False,
        origin=origin,
        approved_node_types=approved_node_types,
    )


def _safe_name(name: str) -> str:
    """Turn a workflow name into a filesystem friendly stem."""
    keep = [c if (c.isalnum() or c in "-_") else "-" for c in name.strip()]
    stem = "".join(keep).strip("-") or "workflow"
    return stem[:80]


def _collect(event: Event, buffer: List[Dict[str, Any]]) -> None:
    """Append an engine event to an in-memory buffer."""
    buffer.append(event.to_dict() if hasattr(event, "to_dict") else {"type": str(event)})


def _relative_artifacts(paths: Iterable[Any]) -> List[str]:
    """Repo-relative artefact paths, so ``GET /api/runs/artifacts/{path}`` works.

    Engine records hold absolute paths; the download endpoint (and the SDK's
    ``artifact_url`` helper) expect paths relative to the repository root.
    Separators are normalised to ``/`` because the value travels as a URL
    path -- a Windows ``output\\runs\\x.html`` is not a usable link.
    """
    relative: List[str] = []
    for item in paths or []:
        try:
            relative.append(Path(item).resolve().relative_to(ROOT).as_posix())
        except (ValueError, OSError):
            relative.append(str(item).replace("\\", "/"))
    return relative


# --------------------------------------------------------------------------- #
# endpoints
# --------------------------------------------------------------------------- #
@router.get("")
async def list_workflows() -> List[Dict[str, Any]]:
    """Every workflow JSON stored under ``workflows/``."""
    items: List[Dict[str, Any]] = []
    for path in sorted(WORKFLOW_DIR.glob("*.json")):
        try:
            workflow = Workflow.from_file(path)
            items.append(
                {
                    "file": path.name,
                    "name": workflow.name,
                    "description": workflow.description,
                    "nodes": len(workflow.nodes),
                    "edges": len(workflow.edges),
                }
            )
        except Exception as exc:  # noqa: BLE001 - a broken file must not 500
            items.append({"file": path.name, "error": str(exc)})
    return items


@router.get("/{filename}")
async def load_workflow(filename: str) -> Dict[str, Any]:
    """Load a stored workflow by file name.

    ``?workflow=`` deep links name a workflow by stem (``07_mzml_mass_spec_analysis``)
    while the UI lists bare file names (``07_mzml_mass_spec_analysis.json``), so
    accept either spelling rather than 404-ing on the documented deep link.
    """
    candidates = [filename]
    if not filename.endswith(".json"):
        candidates.append(f"{filename}.json")
    for candidate in candidates:
        path = (WORKFLOW_DIR / candidate).resolve()
        if str(path).startswith(str(WORKFLOW_DIR.resolve())) and path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    raise HTTPException(status_code=404, detail=f"workflow {filename!r} not found")


@router.post("", status_code=201)
async def create_workflow(payload: WorkflowPayload) -> Dict[str, Any]:
    """Validate and persist a workflow created in the editor."""
    workflow = Workflow.from_dict(payload.model_dump())
    issues = workflow.validate(_engine().registry)
    if issues:
        raise HTTPException(status_code=422, detail={"issues": issues})

    WORKFLOW_DIR.mkdir(parents=True, exist_ok=True)
    path = WORKFLOW_DIR / f"{_safe_name(payload.name)}.json"
    workflow.save(path)
    return {"file": path.name, "name": workflow.name, "nodes": len(workflow.nodes)}


@router.post("/validate")
async def validate_workflow(payload: WorkflowPayload) -> Dict[str, Any]:
    """Validate a workflow without executing it."""
    workflow = Workflow.from_dict(payload.model_dump())
    issues = workflow.validate(_engine().registry)
    return {"valid": not issues, "issues": issues}


@router.post("/{filename}/run", response_model=RunResponse)
async def run_workflow(filename: str, request: RunRequest, http_request: Request) -> RunResponse:
    """Execute a stored workflow and return the full run result."""
    path = (WORKFLOW_DIR / filename).resolve()
    if not str(path).startswith(str(WORKFLOW_DIR.resolve())) or not path.exists():
        raise HTTPException(status_code=404, detail=f"workflow {filename!r} not found")

    workflow = Workflow.from_file(path)
    engine = _engine()

    try:
        engine.assert_valid(workflow)
    except WorkflowValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    run_id = f"api_{uuid.uuid4().hex[:12]}"
    buffer: List[Dict[str, Any]] = []
    EVENT_BUFFERS[run_id] = buffer
    # v0.7.2 task P0-01: bind the run to the calling principal so the WebSocket
    # layer can refuse subscriptions from a different session holding a valid
    # token.
    register_run(run_id, current_principal(http_request), kind="workflow", workflow=filename)

    started = time.perf_counter()
    result = engine.run(
        workflow,
        inputs=request.inputs,
        run_id=run_id,
        event_listener=lambda event: _collect(event, buffer),
    )
    elapsed_ms = (time.perf_counter() - started) * 1000.0

    return RunResponse(
        run_id=run_id,
        workflow=workflow.name,
        status=result.status,
        nodes=len(workflow.nodes),
        duration_ms=round(elapsed_ms, 2),
        records={
            node_id: record.to_dict()
            for node_id, record in (result.records or {}).items()
        },
        artifacts=_relative_artifacts(result.artifacts),
        errors=list(result.errors),
    )


@router.post("/run", response_model=RunResponse)
async def run_workflow_inline(payload: WorkflowPayload, http_request: Request) -> RunResponse:
    """Execute a workflow supplied in the request body (no persistence)."""
    workflow = Workflow.from_dict(payload.model_dump())
    engine = _engine()

    try:
        engine.assert_valid(workflow)
    except WorkflowValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    run_id = f"api_{uuid.uuid4().hex[:12]}"
    buffer: List[Dict[str, Any]] = []
    EVENT_BUFFERS[run_id] = buffer
    register_run(run_id, current_principal(http_request), kind="api", inline=True)

    started = time.perf_counter()
    result = engine.run(
        workflow,
        run_id=run_id,
        event_listener=lambda event: _collect(event, buffer),
    )
    elapsed_ms = (time.perf_counter() - started) * 1000.0

    return RunResponse(
        run_id=run_id,
        workflow=workflow.name,
        status=result.status,
        nodes=len(workflow.nodes),
        duration_ms=round(elapsed_ms, 2),
        records={
            node_id: record.to_dict()
            for node_id, record in (result.records or {}).items()
        },
        artifacts=_relative_artifacts(result.artifacts),
        errors=list(result.errors),
    )


@router.get("/runs/{run_id}/events")
async def run_events(run_id: str, http_request: Request) -> List[Dict[str, Any]]:
    """Event history of a run, for clients that cannot use WebSockets.

    v0.7.2: the same run-level authorisation the WebSocket enforces.  Without
    it this endpoint would be a trivial way to read another session's event
    stream and would defeat the socket check entirely (spec P0-01 #3).
    """
    allowed, reason = may_subscribe(run_id, _principal_of(http_request))
    if not allowed:
        raise HTTPException(status_code=403, detail=f"run {run_id!r} is not accessible ({reason})")
    return EVENT_BUFFERS.get(run_id, [])


@router.get("/runs/{run_id}")
async def run_status(run_id: str, http_request: Request) -> Dict[str, Any]:
    """Minimal status payload for a previously started run."""
    allowed, reason = may_subscribe(run_id, _principal_of(http_request))
    if not allowed:
        # 404 for an unknown run and 403 for a foreign one would leak whether
        # somebody else's run exists; answer uniformly.
        raise HTTPException(status_code=404, detail=f"unknown run {run_id!r}")
    buffer = EVENT_BUFFERS.get(run_id)
    if buffer is None:
        raise HTTPException(status_code=404, detail=f"unknown run {run_id!r}")
    return {
        "run_id": run_id,
        "events": len(buffer),
        "finished": bool(buffer),
        "reason": reason,
    }

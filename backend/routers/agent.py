"""Agent endpoints (v0.7.1 -- spec task B).

Every execution goes through :mod:`agent_runtime` -- the unified task state
machine.  ``/api/agent/ask`` no longer runs the pipeline directly: it creates a
task, returns the plan for review, and only executes after approval (or
immediately when the plan needs no sensitive permission).
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent_runtime import scheduler  # noqa: E402
from memory import get_memory  # noqa: E402
from nodes.agent import plan_question  # noqa: E402
from workflow_engine.agent_state import IllegalTransition  # noqa: E402

router = APIRouter(prefix="/agent", tags=["agent"])


class AskPayload(BaseModel):
    question: str
    language: str = "zh"
    use_llm: bool = True
    max_nodes: int = 12
    remember: bool = False
    #: When True (default) the task runs immediately on submit if the plan
    #: needs no sensitive permission; otherwise it waits for approval.
    auto_approve: bool = True


class PlanPayload(BaseModel):
    question: str
    language: str = "zh"
    max_nodes: int = 12


class FragmentationPayload(BaseModel):
    """Request for the mass-spectrum fragmentation pathway deduction.

    ``spectrum`` is the *serialised* Spectrum exactly as the GUI already holds
    it (``{type: "Spectrum", x: [...], y: [...], peaks: [...]}``), so the panel
    can ask without re-running the workflow.
    """

    spectrum: Dict[str, Any]
    #: Optional candidate structure (serialised Molecule) or a bare SMILES.
    molecule: Optional[Dict[str, Any]] = None
    smiles: str = ""
    adduct: str = "[M+H]+"
    tolerance_ppm: float = 20.0
    max_steps: int = 8
    max_depth: int = 2
    min_relative: float = 0.01
    use_ai: bool = True
    language: str = "zh"


def _task_or_404(task_id: str):
    try:
        return scheduler.get(task_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/ask")
async def ask(payload: AskPayload) -> Dict[str, Any]:
    """Create an agent task (state machine driven).

    Returns the task snapshot.  When the plan requires a sensitive permission
    the task stops at ``WAITING_FOR_APPROVAL``; call
    ``POST /api/agent/tasks/{id}/approve`` to run it.
    """
    question = (payload.question or "").strip()
    if not question:
        raise HTTPException(status_code=422, detail="question must not be empty")
    task = scheduler.submit(
        question,
        language=payload.language,
        use_llm=payload.use_llm,
        max_nodes=payload.max_nodes,
        require_approval=True,
        auto_approve=payload.auto_approve,
    )
    snapshot = task.snapshot()
    snapshot["requires_approval"] = task.state.value == "WAITING_FOR_APPROVAL"
    return snapshot


@router.post("/plan")
async def plan(payload: PlanPayload) -> Dict[str, Any]:
    """Plan only: return the workflow the agent *would* run."""
    question = (payload.question or "").strip()
    if not question:
        raise HTTPException(status_code=422, detail="question must not be empty")
    outputs = plan_question(
        question, language=payload.language, max_nodes=payload.max_nodes
    )
    return {
        "workflow": getattr(outputs.get("workflow"), "text", ""),
        "explanation": getattr(outputs.get("text"), "text", ""),
    }


@router.post("/fragmentation")
async def fragmentation(payload: FragmentationPayload) -> Dict[str, Any]:
    """Deduce the fragmentation pathway of a measured spectrum.

    Runs the node through the real registry (rather than re-implementing its
    logic here) so the panel and a workflow node always agree.  The response
    separates the two engines honestly:

    * ``engine``   -- the rule engine that produced the pathway;
    * ``ai_engine``-- the model that wrote the narrative, or
      ``internal:fragmentation-rules`` when no provider answered.
    """
    from nodes.loader import get_registry

    spectrum_data = dict(payload.spectrum or {})
    if spectrum_data.get("type") not in (None, "Spectrum"):
        raise HTTPException(
            status_code=422,
            detail=f"expected a serialized Spectrum, got {spectrum_data.get('type')!r}",
        )

    smiles = str(payload.smiles or "").strip()
    if not smiles and isinstance(payload.molecule, dict):
        smiles = str(payload.molecule.get("smiles", "") or "").strip()

    node = get_registry().create("FragmentationPathwayNode")
    node.params.update(
        {
            "adduct": payload.adduct,
            "tolerance_ppm": payload.tolerance_ppm,
            "max_steps": payload.max_steps,
            "max_depth": payload.max_depth,
            "min_relative": payload.min_relative,
            "use_ai": payload.use_ai,
            "language": payload.language,
        }
    )

    from workflow_engine.objects import Molecule, Spectrum

    spectrum = Spectrum(**{k: v for k, v in spectrum_data.items() if k != "type"})
    inputs: Dict[str, Any] = {"spectrum": spectrum}
    if smiles:
        # The molecule only supplies a SMILES; building a full descriptor set
        # here would be wasted work, so the node takes the string directly.
        inputs["molecule"] = Molecule(name="candidate", smiles=smiles, formula="")

    outputs = node.process(inputs, ctx=None)
    table = outputs.get("pathway")
    steps_text = getattr(outputs.get("steps"), "text", "")
    narrative = getattr(outputs.get("text"), "text", "")
    narrative_data = getattr(outputs.get("text"), "data", {}) or {}

    return {
        "pathway": list(getattr(table, "rows", []) or []),
        "columns": list(getattr(table, "columns", []) or []),
        "metadata": dict(getattr(table, "metadata", {}) or {}),
        "rules_text": steps_text,
        "narrative": narrative,
        "engine": str((getattr(table, "metadata", {}) or {}).get("engine", "internal:fragmentation-rules")),
        "ai_engine": str(narrative_data.get("engine", "internal:fragmentation-rules")),
        "confidence": float(narrative_data.get("confidence", 0.0) or 0.0),
    }


@router.get("/tasks")
async def list_tasks(limit: int = 50) -> Dict[str, Any]:
    """All known agent tasks with their state machine status."""
    return {"stats": scheduler.stats(), "tasks": scheduler.list(limit=limit)}


@router.get("/tasks/{task_id}")
async def get_task(task_id: str) -> Dict[str, Any]:
    """Full audit record of one task: plan, transitions, verification, result."""
    return _task_or_404(task_id).snapshot()


@router.post("/tasks/{task_id}/approve")
async def approve_task(task_id: str) -> Dict[str, Any]:
    """Approve a reviewed plan and start execution."""
    task = _task_or_404(task_id)
    try:
        scheduler.approve(task_id)
    except IllegalTransition as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return task.snapshot()


@router.post("/tasks/{task_id}/reject")
async def reject_task(task_id: str) -> Dict[str, Any]:
    """Reject a reviewed plan (records the decision, executes nothing)."""
    task = _task_or_404(task_id)
    try:
        scheduler.reject(task_id)
    except IllegalTransition as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return task.snapshot()


@router.post("/tasks/{task_id}/cancel")
async def cancel_task(task_id: str) -> Dict[str, Any]:
    """Cancel a task; execution stops scheduling further nodes."""
    task = _task_or_404(task_id)
    try:
        scheduler.cancel(task_id)
    except IllegalTransition as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return task.snapshot()


@router.post("/tasks/{task_id}/retry")
async def retry_task(task_id: str) -> Dict[str, Any]:
    """Retry a failed/cancelled task as a fresh, approval-gated attempt."""
    _task_or_404(task_id)
    try:
        new_task = scheduler.retry(task_id)
    except IllegalTransition as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    snapshot = new_task.snapshot()
    snapshot["requires_approval"] = new_task.state.value == "WAITING_FOR_APPROVAL"
    return snapshot


@router.get("/history")
async def history(limit: int = 20) -> Dict[str, Any]:
    """Recently remembered agent workflows."""
    memory = get_memory()
    return {
        "stats": memory.stats(),
        "workflows": memory.workflows(limit=max(1, int(limit))),
        "knowledge": memory.recall("", limit=max(1, int(limit))),
    }

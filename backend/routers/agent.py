"""Agent endpoints (v0.7.1 -- spec task B).

Every execution goes through :mod:`agent_runtime` -- the unified task state
machine.  ``/api/agent/ask`` no longer runs the pipeline directly: it creates a
task, returns the plan for review, and only executes after approval (or
immediately when the plan needs no sensitive permission).
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict

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

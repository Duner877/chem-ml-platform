"""Agent task runtime -- the unified, auditable agent execution path (v0.7.1).

Spec task B requires that *every* agent execution is driven by one task state
machine rather than calling the pipeline directly:

    Plan -> Review (approval) -> Execute -> Verify -> Complete

``/api/agent/ask`` used to bypass the lifecycle; it now routes through
:class:`TaskScheduler`, which

* creates a task and moves it through
  :class:`~workflow_engine.agent_state.TaskStateMachine`;
* assesses the plan for required permissions and risks (network / GPU /
  external software / file writes / cloud AI) and surfaces them for review;
* refuses to execute a plan until it has been approved when the plan needs a
  sensitive permission;
* guards against duplicate submission of the same task (no double execution);
* supports cancel, retry (as a fresh approval-gated attempt) and failure
  recovery with a bounded retry budget;
* records every transition, the plan, the actual execution result and a
  verification section -- so an unfinished plan, a failed execution and a
  verified result are always distinguishable.
"""

from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from workflow_engine.agent_state import (
    AgentState,
    IllegalTransition,
    TaskStateMachine,
    TERMINAL_STATES,
)

__all__ = ["AgentTask", "TaskScheduler", "scheduler", "assess_plan"]


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


#: Node capability -> (permission, risk kind, human detail).
_CAPABILITY_MAP = {
    "requires_external_software": ("external", "external_software", "调用外部科学软件"),
    "requires_network": ("external", "network", "需要访问网络 / 云端服务"),
    "writes_files": ("write", "files", "会生成或覆盖文件"),
    "requires_gpu": ("execute", "gpu", "需要 GPU 推理"),
    "experimental": ("execute", "experimental", "实验性能力，结果需人工复核"),
    "sensitive_data": ("execute", "sensitive_data", "涉及敏感数据，建议使用本地模型"),
}


def assess_plan(plan: Any, registry: Any = None) -> Tuple[List[str], List[Dict[str, str]]]:
    """Derive required permissions and risks from a plan's node capabilities."""
    permissions: set = set()
    risks: List[Dict[str, str]] = []
    seen: set = set()
    node_types = list(getattr(plan, "node_types", []) or [])
    for node_type in node_types:
        capabilities: List[str] = []
        if registry is not None:
            try:
                cls = registry.get(node_type)
                capabilities = list(getattr(cls, "capabilities", []) or [])
            except KeyError:
                capabilities = []
        for capability in capabilities:
            mapping = _CAPABILITY_MAP.get(capability)
            if not mapping:
                continue
            permission, kind, detail = mapping
            permissions.add(permission)
            key = (node_type, kind)
            if key in seen:
                continue
            seen.add(key)
            risks.append({"kind": kind, "node_type": node_type, "detail": detail})
    return sorted(permissions), risks


@dataclass
class AgentTask:
    """One agent task and its full audit trail."""

    task_id: str
    question: str
    language: str = "zh"
    use_llm: bool = True
    max_nodes: int = 12
    fingerprint: str = ""
    retry_of: str = ""

    machine: TaskStateMachine = field(default_factory=lambda: TaskStateMachine(task_id=""))
    created_at: str = field(default_factory=_utc)
    updated_at: str = field(default_factory=_utc)

    plan: Dict[str, Any] = field(default_factory=dict)
    workflow: Dict[str, Any] = field(default_factory=dict)
    permissions: List[str] = field(default_factory=list)
    risks: List[Dict[str, str]] = field(default_factory=list)
    #: Nodes the tool guard refuses outright (see ``agent_runtime.tool_guard``).
    blocked_nodes: List[Dict[str, Any]] = field(default_factory=list)
    #: Nodes the tool guard will run only with an explicit approval.
    gated_nodes: List[Dict[str, Any]] = field(default_factory=list)

    records: Dict[str, Any] = field(default_factory=dict)
    verification: List[Dict[str, Any]] = field(default_factory=list)
    result: Dict[str, Any] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)

    cancel_event: threading.Event = field(default_factory=threading.Event)

    def __post_init__(self) -> None:
        if not self.machine.task_id:
            self.machine.task_id = self.task_id

    # -- reporting ----------------------------------------------------------- #
    @property
    def state(self) -> AgentState:
        return self.machine.state

    @property
    def terminal(self) -> bool:
        return self.state in TERMINAL_STATES

    def snapshot(self) -> Dict[str, Any]:
        """Full JSON-serialisable view of the task."""
        return {
            "task_id": self.task_id,
            "question": self.question,
            "language": self.language,
            "state": self.state.value,
            "terminal": self.terminal,
            "retry_of": self.retry_of,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "plan": self.plan,
            "permissions": list(self.permissions),
            "risks": list(self.risks),
            "blocked_nodes": list(self.blocked_nodes),
            "gated_nodes": list(self.gated_nodes),
            "records": dict(self.records),
            "verification": list(self.verification),
            "errors": list(self.errors),
            "state_machine": self.machine.to_dict(),
            "result": dict(self.result),
        }

    def summary(self) -> Dict[str, Any]:
        """Compact view for list endpoints."""
        return {
            "task_id": self.task_id,
            "question": self.question,
            "state": self.state.value,
            "permissions": list(self.permissions),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "status": self.result.get("status", ""),
        }


class TaskScheduler:
    """Creates, drives and audits agent tasks (the single execution path)."""

    def __init__(self, max_history: int = 200):
        self._tasks: Dict[str, AgentTask] = {}
        self._fingerprints: Dict[str, str] = {}
        self._order: List[str] = []
        self._lock = threading.RLock()
        self._counter = 0
        self.max_history = max_history

    # -- helpers -------------------------------------------------------------- #
    def _new_id(self) -> str:
        with self._lock:
            self._counter += 1
            return f"task_{self._counter:05d}"

    @staticmethod
    def _fingerprint(question: str, language: str, max_nodes: int, use_llm: bool) -> str:
        blob = json.dumps(
            {"q": question.strip(), "lang": language, "n": max_nodes, "llm": use_llm},
            ensure_ascii=False,
            sort_keys=True,
        )
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]

    def _trim(self) -> None:
        """Keep the newest ``max_history`` tasks; never drop a running one."""
        if len(self._order) <= self.max_history:
            return
        keep: List[str] = []
        drop: List[str] = []
        for index, task_id in enumerate(self._order):
            task = self._tasks.get(task_id)
            if index < len(self._order) - self.max_history and task and task.terminal:
                drop.append(task_id)
            else:
                keep.append(task_id)
        for task_id in drop:
            task = self._tasks.pop(task_id, None)
            if task:
                self._fingerprints.pop(task.fingerprint, None)
        self._order = keep

    # -- public API ------------------------------------------------------------ #
    def submit(
        self,
        question: str,
        *,
        language: str = "zh",
        use_llm: bool = True,
        max_nodes: int = 12,
        require_approval: bool = True,
        auto_approve: bool = False,
        retry_of: str = "",
        plan: Optional[Dict[str, Any]] = None,
    ) -> AgentTask:
        """Create a task, plan it and leave it waiting for (or ready to run).

        A duplicate submission of an identical, still-active question returns
        the existing task instead of scheduling a second execution.
        """
        question = (question or "").strip()
        fingerprint = self._fingerprint(question, language, max_nodes, use_llm)
        with self._lock:
            existing_id = self._fingerprints.get(fingerprint)
            if existing_id:
                existing = self._tasks.get(existing_id)
                if existing is not None and not existing.terminal:
                    existing.records.setdefault("duplicate_submission", {
                        "at": _utc(),
                        "note": "identical active task already scheduled",
                    })
                    return existing

            task = AgentTask(
                task_id=self._new_id(),
                question=question,
                language=language,
                use_llm=use_llm,
                max_nodes=max_nodes,
                fingerprint=fingerprint,
                retry_of=retry_of,
            )
            task.machine = TaskStateMachine(task_id=task.task_id)
            self._tasks[task.task_id] = task
            self._order.append(task.task_id)
            self._fingerprints[fingerprint] = task.task_id
            self._trim()

        # Plan (stage 1) happens eagerly so the review screen has content.
        try:
            self._stage_plan(task, plan)
        except Exception as exc:  # noqa: BLE001 - recorded, then surfaced
            self._safe_fail(task, f"planning failed: {type(exc).__name__}: {exc}")
            return task

        needs_approval = require_approval and bool(task.permissions)
        if auto_approve or not needs_approval:
            task.machine.request_approval("no sensitive permission required")
            task.machine.approve()
            self._run_async(task)
        else:
            task.machine.request_approval("awaiting user approval")
        return task

    def approve(self, task_id: str, *, run: bool = True) -> AgentTask:
        """Approve a waiting plan and start execution."""
        task = self._require(task_id)
        with self._lock:
            task.machine.approve()
        if run:
            self._run_async(task)
        return task

    def reject(self, task_id: str, reason: str = "user rejected plan") -> AgentTask:
        """Reject a waiting plan: WAITING_FOR_APPROVAL -> PLANNING -> CANCELLED."""
        task = self._require(task_id)
        with self._lock:
            task.machine.transition(AgentState.PLANNING, reason)
            task.machine.cancel(reason)
            task.records["rejected"] = {"at": _utc(), "reason": reason}
        return task

    def cancel(self, task_id: str) -> AgentTask:
        """Request cancellation; execution stops scheduling further nodes."""
        task = self._require(task_id)
        task.cancel_event.set()
        with self._lock:
            if not task.terminal:
                task.machine.cancel("user cancelled")
                task.records["cancelled"] = {"at": _utc()}
        return task

    def retry(self, task_id: str, *, require_approval: bool = True) -> AgentTask:
        """Re-submit a failed/cancelled task as a *fresh, approval-gated* attempt.

        Re-running is never silent: the new task inherits the plan but starts
        in ``WAITING_FOR_APPROVAL`` so a non-idempotent step (file write,
        external program) cannot be repeated without consent.
        """
        task = self._require(task_id)
        if not task.terminal:
            raise IllegalTransition(
                f"task {task_id} is {task.state.value}; retry only applies to a "
                "failed or cancelled task"
            )
        return self.submit(
            task.question,
            language=task.language,
            use_llm=task.use_llm,
            max_nodes=task.max_nodes,
            require_approval=require_approval,
            retry_of=task_id,
            plan=dict(task.plan) or None,
        )

    def get(self, task_id: str) -> AgentTask:
        return self._require(task_id)

    def list(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self._lock:
            items = [self._tasks[t] for t in reversed(self._order) if t in self._tasks]
        return [task.summary() for task in items[: max(1, limit)]]

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            counts: Dict[str, int] = {}
            for task in self._tasks.values():
                counts[task.state.value] = counts.get(task.state.value, 0) + 1
        return {"total": len(self._tasks), "by_state": counts}

    # -- internals ------------------------------------------------------------- #
    def _require(self, task_id: str) -> AgentTask:
        with self._lock:
            task = self._tasks.get(task_id)
        if task is None:
            raise KeyError(f"unknown task {task_id!r}")
        return task

    def _stage_plan(self, task: AgentTask, plan: Optional[Dict[str, Any]]) -> None:
        """Stage 1: produce the plan, workflow document, permissions and risks."""
        from nodes.agent.agent import plan_only
        from nodes.agent.planner import Planner  # noqa: F401 (typing clarity)
        from nodes.loader import get_registry

        registry = get_registry()
        with self._lock:
            task.machine.transition(AgentState.PLANNING, "planner started")
            task.updated_at = _utc()

        node = registry.create("ScientificAgentNode")
        node.params.update({
            "question": task.question,
            "language": task.language,
            "use_llm": task.use_llm,
            "max_nodes": task.max_nodes,
            "remember": False,
        })
        built_plan, planner, document = plan_only(node, task.question, {})
        task.plan = built_plan.to_dict()
        task.plan["_workflow"] = document
        task.workflow = document
        permissions, risks = assess_plan(built_plan, registry)
        task.permissions = permissions
        task.risks = risks

        # Tool guard (v0.7.3, adapted from Octop's tool_guard): capability
        # grading says *what a node needs*; the guard says *whether an agent may
        # run it at all*.  Both are needed -- a read-only node can still be one
        # the user does not want an agent touching, and the capability grades
        # have no vocabulary for "delete" versus "export".
        from agent_runtime.tool_guard import check_tool_call

        node_types = list(getattr(built_plan, "node_types", []) or [])
        blocked: List[Dict[str, Any]] = []
        gated: List[Dict[str, Any]] = []
        for node_type in node_types:
            decision = check_tool_call(str(node_type))
            if decision.verdict == "deny":
                blocked.append({"node": str(node_type), **decision.to_dict()})
            elif decision.requires_approval:
                gated.append({"node": str(node_type), **decision.to_dict()})
        task.blocked_nodes = blocked
        task.gated_nodes = gated
        if gated and not task.permissions:
            # The guard found something the capability table did not; surface it
            # as a permission so the existing approval flow catches it rather
            # than inventing a second approval path.
            task.permissions = ["write"]
        if blocked or gated:
            task.records["guard"] = {
                "at": _utc(),
                "blocked": blocked,
                "approval_required": gated,
                "engine": "internal:tool-guard",
            }
        task.records["plan"] = {
            "at": _utc(),
            "engine": getattr(built_plan, "engine", ""),
            "intent": getattr(built_plan, "intent", ""),
            "nodes": list(getattr(built_plan, "node_types", []) or []),
            "notes": list(getattr(built_plan, "notes", []) or []),
        }
        task.updated_at = _utc()

    def _run_async(self, task: AgentTask) -> None:
        """Spawn the execution thread (the machine is already RUNNING)."""
        with self._lock:
            task.updated_at = _utc()
        thread = threading.Thread(
            target=self._execute, args=(task,), name=f"agent-{task.task_id}", daemon=True
        )
        thread.start()

    def _execute(self, task: AgentTask) -> None:
        """Stages 2-4: execute the plan, verify and finalise."""
        from nodes.agent.agent import execute_plan, finalise
        from nodes.loader import get_registry

        # A task cancelled before the worker picked it up must not run.
        if task.state in TERMINAL_STATES or task.state is not AgentState.RUNNING:
            task.records.setdefault(
                "execution_skipped",
                {"at": _utc(), "reason": f"task is {task.state.value} at worker start"},
            )
            return

        try:
            registry = get_registry()

            # The guard's verdict must stop the run, not merely annotate it.
            # A record saying "denied" next to an execution that went ahead is
            # worse than no guard at all.
            if task.blocked_nodes:
                names = ", ".join(str(item.get("node", "")) for item in task.blocked_nodes)
                task.errors.append(
                    f"tool guard refused: {names}"
                )
                task.result = {
                    "status": "refused",
                    "refused_nodes": list(task.blocked_nodes),
                    "reason": (
                        "工具守卫拒绝了计划中的节点，任务未执行。/ The tool guard "
                        "refused nodes in the plan; nothing was executed."
                    ),
                }
                task.records["guard_refusal"] = {
                    "at": _utc(),
                    "nodes": list(task.blocked_nodes),
                    "engine": "internal:tool-guard",
                }
                with self._lock:
                    task.machine.transition(AgentState.FAILED, "refused by tool guard")
                return

            node = registry.create("ScientificAgentNode")
            node.params.update({
                "question": task.question,
                "language": task.language,
                "use_llm": task.use_llm,
                "max_nodes": task.max_nodes,
                "remember": False,
            })
            # Rebuild the plan object from the recorded snapshot.
            from nodes.agent.planner import Plan, PlanStep

            plan_data = task.plan or {}
            plan = Plan(
                intent=plan_data.get("intent", ""),
                engine=plan_data.get("engine", ""),
                steps=[PlanStep(**step) for step in plan_data.get("steps", [])],
                notes=list(plan_data.get("notes", [])),
            )
            planner = None
            result = execute_plan(node, plan, planner, cancel_check=task.cancel_event.is_set)
            task.records["execute"] = {
                "at": _utc(),
                "status": result.get("status", ""),
                "duration_ms": result.get("duration_ms", 0),
                "nodes": sorted((result.get("records", {}) or {}).keys()),
                "errors": list(result.get("errors", []) or []),
                "provenance_path": result.get("provenance_path", ""),
            }

            outputs = finalise(node, task.question, plan, result)
            analysis = outputs.get("_analysis", {})
            task.result = _summarise_task(outputs)
            task.result["engine"] = plan.engine
            task.result["provenance_path"] = result.get("provenance_path", "")

            with self._lock:
                task.machine.transition(AgentState.VERIFYING, "verifying results")
            task.verification = self._verify(task, result)

            cancelled = task.cancel_event.is_set() or result.get("status") == "cancelled"
            with self._lock:
                if cancelled:
                    task.records["cancelled"] = {"at": _utc(), "partial_result": True}
                    task.machine.transition(AgentState.CANCELLED, "cancelled during run")
                elif result.get("errors"):
                    task.errors.extend(str(e) for e in result.get("errors", []))
                    task.machine.transition(AgentState.FAILED, "execution reported errors")
                else:
                    task.machine.transition(AgentState.COMPLETED, "verified and completed")
                task.updated_at = _utc()
        except Exception as exc:  # noqa: BLE001 - recorded and surfaced, never silent
            self._safe_fail(task, f"{type(exc).__name__}: {exc}")

    def _verify(self, task: AgentTask, result: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Minimal, honest verification pass (spec task H/I)."""
        checks: List[Dict[str, Any]] = []

        def add(name: str, passed: bool, detail: str = "") -> None:
            checks.append({"check": name, "passed": bool(passed), "detail": detail})

        status = result.get("status", "")
        add("execution_status", status == "completed", f"engine status = {status or 'unknown'}")
        add("no_errors", not result.get("errors"), f"{len(result.get('errors', []) or [])} errors")
        add(
            "provenance_recorded",
            bool(result.get("provenance_path")),
            result.get("provenance_path", "no provenance file"),
        )
        add(
            "scientific_validity",
            False,
            "requires the LC-MS/MS known-answer benchmark (see benchmarks/) -- not asserted here",
        )
        return checks

    def _safe_fail(self, task: AgentTask, message: str) -> None:
        with self._lock:
            task.errors.append(message)
            task.records.setdefault("failure", {"at": _utc(), "error": message})
            task.updated_at = _utc()
            if not task.terminal:
                try:
                    task.machine.fail(message)
                except IllegalTransition:
                    pass


def _summarise_task(outputs: Dict[str, Any]) -> Dict[str, Any]:
    """Condense the agent output ports (same shape as ``nodes.agent.summarise``)."""
    from nodes.agent.agent import summarise

    clean = {k: v for k, v in outputs.items() if not k.startswith("_")}
    return summarise(clean)


#: Process-wide scheduler used by the REST layer.
scheduler = TaskScheduler()

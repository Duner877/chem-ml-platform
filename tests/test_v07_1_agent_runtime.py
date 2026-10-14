"""v0.7.1 agent-runtime tests (task B / spec §P0-03).

The scheduler is the single execution path for every agent task.  These tests
drive it with a deterministic stub planner/executor so the *state machine*
logic -- plan -> approval gate -> execute -> verify -> complete, plus the
duplicate-submission guard, cancel, reject and retry -- is exercised precisely.

The planner and the workflow engine have their own suites
(``test_v07_agent_state.py``, ``test_engine.py``); here we only assert the
lifecycle wiring.
"""

from __future__ import annotations

import time

import pytest

from agent_runtime.tasks import TaskScheduler, assess_plan
from nodes.agent.planner import Plan, PlanStep
from workflow_engine.agent_state import AgentState, IllegalTransition


def _plan(node_types, intent="test intent"):
    """A deterministic plan over the given node types."""
    return Plan(
        intent=intent,
        question="stub",
        engine="stub",
        steps=[PlanStep(node_type=t, node_id=f"n{i}") for i, t in enumerate(node_types)],
        notes=["stub plan"],
    )


def _install_stubs(monkeypatch, plan, *, result=None, fail=False):
    """Patch the agent pipeline so the scheduler runs without real execution."""
    import nodes.agent.agent as agent_mod

    def fake_plan_only(node, question, data=None):
        return plan, None, {"nodes": [s.to_dict() for s in plan.steps], "edges": []}

    def fake_execute(node, plan_obj, planner, cancel_check=None):
        if fail:
            return {"status": "failed", "duration_ms": 1, "records": {}, "errors": ["boom"]}
        return {
            "status": "completed",
            "duration_ms": 3,
            "records": {"n0": {"status": "completed"}},
            "errors": [],
            "provenance_path": "output/runs/run_x/provenance.json",
            "workflow": "wf",
        }

    def fake_finalise(node, question, plan_obj, run_result):
        return {"_analysis": {"narrative": "ok"}}

    monkeypatch.setattr(agent_mod, "plan_only", fake_plan_only)
    monkeypatch.setattr(agent_mod, "execute_plan", fake_execute)
    monkeypatch.setattr(agent_mod, "finalise", fake_finalise)
    monkeypatch.setattr(agent_mod, "summarise", lambda outputs: {"status": "ok"})


def _wait_terminal(task, timeout=10.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if task.terminal:
            return True
        time.sleep(0.02)
    return False


class TestPermissionGating:
    def test_sensitive_plan_waits_for_approval(self, monkeypatch):
        # PubChemNode declares requires_network -> needs an 'external' permission.
        _install_stubs(monkeypatch, _plan(["PubChemNode", "NormalizeNode"]))
        sched = TaskScheduler()
        task = sched.submit("查询阿司匹林", require_approval=True)
        assert task.state is AgentState.WAITING_FOR_APPROVAL
        assert "external" in task.permissions
        assert any(r["kind"] == "network" for r in task.risks)

    def test_benign_plan_runs_without_approval(self, monkeypatch):
        _install_stubs(monkeypatch, _plan(["NormalizeNode", "SmoothingNode"]))
        sched = TaskScheduler()
        task = sched.submit("归一化光谱", require_approval=True)
        assert task.permissions == []
        assert _wait_terminal(task)
        assert task.state is AgentState.COMPLETED

    def test_approve_then_execute_completes(self, monkeypatch):
        _install_stubs(monkeypatch, _plan(["PubChemNode"]))
        sched = TaskScheduler()
        task = sched.submit("查询分子", require_approval=True)
        assert task.state is AgentState.WAITING_FOR_APPROVAL
        sched.approve(task.task_id)
        assert _wait_terminal(task)
        assert task.state is AgentState.COMPLETED
        assert task.verification  # a verification section was recorded
        assert task.records["plan"]["nodes"] == ["PubChemNode"]

    def test_execution_error_leads_to_failed(self, monkeypatch):
        _install_stubs(monkeypatch, _plan(["PubChemNode"]), fail=True)
        sched = TaskScheduler()
        task = sched.submit("查询分子")
        sched.approve(task.task_id)
        assert _wait_terminal(task)
        assert task.state is AgentState.FAILED
        assert task.errors


class TestDuplicateAndHistory:
    def test_duplicate_submission_returns_same_task(self, monkeypatch):
        _install_stubs(monkeypatch, _plan(["PubChemNode"]))
        sched = TaskScheduler()
        first = sched.submit("同一个问题")
        second = sched.submit("同一个问题")
        assert first.task_id == second.task_id
        assert "duplicate_submission" in second.records

    def test_history_is_trimmed_but_keeps_running(self, monkeypatch):
        _install_stubs(monkeypatch, _plan(["PubChemNode"]))
        sched = TaskScheduler(max_history=2)
        t1 = sched.submit("问题甲")
        t2 = sched.submit("问题乙")
        t3 = sched.submit("问题丙")
        assert len(sched.list(limit=10)) <= 3  # active tasks are not dropped
        assert sched.get(t3.task_id).state is AgentState.WAITING_FOR_APPROVAL
        assert t1.task_id and t2.task_id


class TestCancelRejectRetry:
    def test_reject_cancels_without_running(self, monkeypatch):
        _install_stubs(monkeypatch, _plan(["PubChemNode"]))
        sched = TaskScheduler()
        task = sched.submit("别跑")
        sched.reject(task.task_id, reason="不需要")
        assert task.state is AgentState.CANCELLED
        assert task.records["rejected"]["reason"] == "不需要"

    def test_cancel_sets_event_and_state(self, monkeypatch):
        _install_stubs(monkeypatch, _plan(["PubChemNode"]))
        sched = TaskScheduler()
        task = sched.submit("取消我")
        sched.cancel(task.task_id)
        assert task.state is AgentState.CANCELLED
        assert task.cancel_event.is_set()

    def test_retry_requires_terminal_state(self, monkeypatch):
        _install_stubs(monkeypatch, _plan(["PubChemNode"]))
        sched = TaskScheduler()
        task = sched.submit("等待中")
        with pytest.raises(IllegalTransition):
            sched.retry(task.task_id)

    def test_retry_of_failed_is_approval_gated(self, monkeypatch):
        _install_stubs(monkeypatch, _plan(["PubChemNode"]), fail=True)
        sched = TaskScheduler()
        task = sched.submit("会失败")
        sched.approve(task.task_id)
        assert _wait_terminal(task)
        assert task.state is AgentState.FAILED
        retried = sched.retry(task.task_id)
        assert retried.retry_of == task.task_id
        assert retried.state is AgentState.WAITING_FOR_APPROVAL  # never silent


class TestAssessPlan:
    def test_maps_capabilities_to_permissions(self):
        from nodes.loader import get_registry

        plan = _plan(["PubChemNode", "GpuDeviceInfoNode", "ReportExportNode"])
        permissions, risks = assess_plan(plan, get_registry())
        assert "external" in permissions   # PubChem network
        assert "execute" in permissions    # GPU node
        assert "write" in permissions      # report export writes files
        kinds = {r["kind"] for r in risks}
        assert {"network", "gpu", "files"} <= kinds

    def test_unknown_node_types_are_ignored(self):
        permissions, risks = assess_plan(_plan(["NoSuchNode"]))
        assert permissions == [] and risks == []

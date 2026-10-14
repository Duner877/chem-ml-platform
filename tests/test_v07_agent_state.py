"""v0.7 Phase D tests -- Agent task state machine (spec section 5.1)."""

from __future__ import annotations

import pytest

from workflow_engine.agent_state import (
    TERMINAL_STATES,
    AgentState,
    IllegalTransition,
    TaskStateMachine,
)


def new_task() -> TaskStateMachine:
    return TaskStateMachine(task_id="task_1")


class TestHappyPath:
    def test_full_lifecycle(self):
        task = new_task()
        task.transition(AgentState.PLANNING)
        task.transition(AgentState.WAITING_FOR_APPROVAL, "plan ready")
        task.approve()
        task.transition(AgentState.VERIFYING)
        task.transition(AgentState.COMPLETED)
        assert task.state is AgentState.COMPLETED
        assert task.to_dict()["terminal"] is True
        # 5 transitions + creation entry
        assert len(task.history) == 6

    def test_history_records_reasons(self):
        task = new_task()
        task.transition(AgentState.PLANNING, "goal parsed")
        entry = task.history[-1]
        assert entry["from"] == "CREATED"
        assert entry["to"] == "PLANNING"
        assert entry["reason"] == "goal parsed"
        assert entry["at"]


class TestIllegalTransitions:
    def test_created_to_running_rejected(self):
        task = new_task()
        with pytest.raises(IllegalTransition):
            task.transition(AgentState.RUNNING)

    def test_completed_to_running_rejected(self):
        task = new_task()
        for step in (AgentState.PLANNING, AgentState.WAITING_FOR_APPROVAL,
                     AgentState.RUNNING, AgentState.VERIFYING, AgentState.COMPLETED):
            task.transition(step)
        with pytest.raises(IllegalTransition):
            task.transition(AgentState.RUNNING)

    def test_cancel_from_terminal_rejected(self):
        task = new_task()
        task.fail("unrecoverable")
        with pytest.raises(IllegalTransition):
            task.cancel()

    def test_require_guard(self):
        task = new_task()
        with pytest.raises(IllegalTransition):
            task.approve()  # not WAITING_FOR_APPROVAL


class TestAbortPaths:
    @pytest.mark.parametrize("mid", [AgentState.PLANNING, AgentState.RUNNING, AgentState.VERIFYING])
    def test_cancel_from_any_active_state(self, mid):
        task = new_task()
        task.transition(AgentState.PLANNING)
        task.transition(AgentState.WAITING_FOR_APPROVAL)
        if mid is AgentState.PLANNING:
            # user asks for a revised plan before approving, then cancels
            task.transition(AgentState.PLANNING, "revise plan")
        else:
            task.approve()
            if mid is AgentState.VERIFYING:
                task.transition(AgentState.VERIFYING)
        task.cancel()
        assert task.state is AgentState.CANCELLED

    def test_pause_and_resume(self):
        task = new_task()
        for step in (AgentState.PLANNING, AgentState.WAITING_FOR_APPROVAL):
            task.transition(step)
        task.approve()
        task.transition(AgentState.PAUSED, "user paused")
        task.transition(AgentState.RUNNING, "resumed")
        assert task.state is AgentState.RUNNING

    def test_waiting_for_input_then_replan(self):
        task = new_task()
        task.transition(AgentState.PLANNING)
        task.transition(AgentState.WAITING_FOR_INPUT, "missing dataset")
        task.transition(AgentState.PLANNING, "user supplied data")
        assert task.state is AgentState.PLANNING


class TestRetryBudget:
    def test_retry_counts(self):
        task = new_task()
        assert task.register_retry() == 1
        assert task.register_retry() == 2

    def test_retry_budget_exhausted(self):
        task = TaskStateMachine(task_id="t", max_retries=2)
        task.register_retry()
        task.register_retry()
        with pytest.raises(IllegalTransition):
            task.register_retry()

    def test_terminal_states_frozen(self):
        from workflow_engine.agent_state import TRANSITIONS

        assert TERMINAL_STATES == {AgentState.COMPLETED, AgentState.FAILED, AgentState.CANCELLED}
        for state in TERMINAL_STATES:
            assert TRANSITIONS[state] == set()

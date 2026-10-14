"""Agent task state machine (v0.7 -- spec section 5.1).

A strict, auditable lifecycle for agent-driven scientific tasks:

    CREATED -> PLANNING -> WAITING_FOR_APPROVAL -> RUNNING -> VERIFYING -> COMPLETED

Abort states reachable from any state: FAILED, CANCELLED.
Intermediate pauses: PAUSED (from RUNNING/VERIFYING), WAITING_FOR_INPUT.

Illegal transitions raise :class:`IllegalTransition`; every accepted
transition is appended to ``history`` with a timestamp so the whole
execution is auditable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional

__all__ = [
    "AgentState",
    "IllegalTransition",
    "TaskStateMachine",
    "TERMINAL_STATES",
]


class AgentState(str, Enum):
    CREATED = "CREATED"
    PLANNING = "PLANNING"
    WAITING_FOR_APPROVAL = "WAITING_FOR_APPROVAL"
    WAITING_FOR_INPUT = "WAITING_FOR_INPUT"
    RUNNING = "RUNNING"
    VERIFYING = "VERIFYING"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


TERMINAL_STATES = {AgentState.COMPLETED, AgentState.FAILED, AgentState.CANCELLED}


class IllegalTransition(Exception):
    """Raised when a state transition is not allowed by the lifecycle rules."""


#: Legal transitions of the lifecycle (spec section 5.1).
TRANSITIONS: Dict[AgentState, set] = {
    AgentState.CREATED: {AgentState.PLANNING, AgentState.CANCELLED, AgentState.FAILED},
    AgentState.PLANNING: {
        AgentState.WAITING_FOR_APPROVAL,   # plan produced, needs user consent
        AgentState.WAITING_FOR_INPUT,      # missing data / clarification
        AgentState.FAILED,                 # planner error
        AgentState.CANCELLED,
    },
    AgentState.WAITING_FOR_APPROVAL: {
        AgentState.RUNNING,                # user approved
        AgentState.PLANNING,               # user asked for a revised plan
        AgentState.CANCELLED,
    },
    AgentState.WAITING_FOR_INPUT: {
        AgentState.PLANNING,               # user supplied input, re-plan
        AgentState.RUNNING,                # direct continue
        AgentState.CANCELLED,
    },
    AgentState.RUNNING: {
        AgentState.VERIFYING,              # nodes finished, verify results
        AgentState.PAUSED,                 # user paused
        AgentState.WAITING_FOR_INPUT,      # agent needs a decision mid-run
        AgentState.FAILED,
        AgentState.CANCELLED,
    },
    AgentState.VERIFYING: {
        AgentState.COMPLETED,
        AgentState.RUNNING,                # verification spawned a retry
        AgentState.PAUSED,
        AgentState.FAILED,
        AgentState.CANCELLED,
    },
    AgentState.PAUSED: {
        AgentState.RUNNING,
        AgentState.CANCELLED,
    },
    AgentState.COMPLETED: set(),
    AgentState.FAILED: set(),
    AgentState.CANCELLED: set(),
}


@dataclass
class TaskStateMachine:
    """Auditable lifecycle holder for one agent task."""

    task_id: str
    state: AgentState = AgentState.CREATED
    history: List[dict] = field(default_factory=list)
    retry_count: int = 0
    max_retries: int = 3

    def __post_init__(self) -> None:
        if not self.history:
            self.history.append(self._entry(None, self.state, "task created"))

    # -- transitions --------------------------------------------------------- #
    def transition(self, to: AgentState | str, reason: str = "") -> AgentState:
        """Move to ``to`` if legal; otherwise raise :class:`IllegalTransition`."""
        target = AgentState(to) if not isinstance(to, AgentState) else to
        if target not in TRANSITIONS[self.state]:
            raise IllegalTransition(
                f"illegal transition {self.state.value} -> {target.value}"
                + (f" ({reason})" if reason else "")
            )
        previous = self.state
        self.state = target
        self.history.append(self._entry(previous, target, reason))
        return self.state

    # -- convenience guards ---------------------------------------------------- #
    def require(self, *states: AgentState) -> None:
        """Assert the machine is in one of ``states`` (guards execution)."""
        if self.state not in states:
            raise IllegalTransition(
                f"operation requires state in {[s.value for s in states]} "
                f"but machine is {self.state.value}"
            )

    def can(self, to: AgentState | str) -> bool:
        target = AgentState(to) if not isinstance(to, AgentState) else to
        return target in TRANSITIONS[self.state]

    # -- lifecycle helpers ------------------------------------------------------- #
    def approve(self) -> None:
        """User approved the plan: WAITING_FOR_APPROVAL -> RUNNING."""
        self.require(AgentState.WAITING_FOR_APPROVAL)
        self.transition(AgentState.RUNNING, "user approved plan")

    def request_approval(self, reason: str = "plan ready") -> None:
        self.transition(AgentState.WAITING_FOR_APPROVAL, reason)

    def fail(self, reason: str = "") -> None:
        self.transition(AgentState.FAILED, reason)

    def cancel(self, reason: str = "user cancelled") -> None:
        if self.state in TERMINAL_STATES:
            raise IllegalTransition(f"cannot cancel a {self.state.value} task")
        self.transition(AgentState.CANCELLED, reason)

    def register_retry(self) -> int:
        """Count a retry; refusing endless retry loops (spec section 5.5)."""
        if self.retry_count >= self.max_retries:
            raise IllegalTransition(
                f"retry budget exhausted ({self.max_retries}); refusing to retry"
            )
        self.retry_count += 1
        return self.retry_count

    # -- serialisation --------------------------------------------------------------- #
    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "state": self.state.value,
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
            "history": list(self.history),
            "terminal": self.state in TERMINAL_STATES,
        }

    # -- internals -------------------------------------------------------------------- #
    @staticmethod
    def _entry(previous: Optional[AgentState], target: AgentState, reason: str) -> dict:
        return {
            "from": previous.value if previous else "",
            "to": target.value,
            "reason": reason,
            "at": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        }

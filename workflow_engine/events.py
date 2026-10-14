"""Execution events.

The engine emits events while a workflow is running.  The FastAPI layer
forwards them over a WebSocket so the React Flow canvas can render live
progress; the CLI simply prints them.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Dict, List, Optional

from .utils import now_iso

RUN_STARTED = "run_started"
RUN_COMPLETED = "run_completed"
RUN_FAILED = "run_failed"
RUN_CANCELLED = "run_cancelled"
NODE_STARTED = "node_started"
NODE_LOG = "node_log"
NODE_COMPLETED = "node_completed"
NODE_FAILED = "node_failed"
NODE_SKIPPED = "node_skipped"
NODE_CACHED = "node_cached"

ALL_EVENTS = (
    RUN_STARTED,
    RUN_COMPLETED,
    RUN_FAILED,
    NODE_STARTED,
    NODE_LOG,
    NODE_COMPLETED,
    NODE_FAILED,
    NODE_SKIPPED,
    NODE_CACHED,
)


@dataclass
class Event:
    """A single execution event."""

    type: str
    run_id: str = ""
    node_id: str = ""
    node_type: str = ""
    message: str = ""
    progress: float = 0.0
    timestamp: str = field(default_factory=now_iso)
    payload: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


EventListener = Callable[[Event], None]


class EventBus:
    """Minimal synchronous publish/subscribe bus."""

    def __init__(self) -> None:
        self._listeners: List[EventListener] = []
        self.history: List[Event] = []

    def subscribe(self, listener: EventListener) -> None:
        if listener not in self._listeners:
            self._listeners.append(listener)

    def unsubscribe(self, listener: EventListener) -> None:
        if listener in self._listeners:
            self._listeners.remove(listener)

    def publish(self, event: Event) -> None:
        self.history.append(event)
        for listener in list(self._listeners):
            try:
                listener(event)
            except Exception as exc:  # pragma: no cover - listener isolation
                print(f"[events] listener error: {exc}")

    def emit(
        self,
        type_: str,
        message: str = "",
        *,
        run_id: str = "",
        node_id: str = "",
        node_type: str = "",
        progress: float = 0.0,
        **payload: Any,
    ) -> Event:
        event = Event(
            type=type_,
            run_id=run_id,
            node_id=node_id,
            node_type=node_type,
            message=message,
            progress=progress,
            payload=payload,
        )
        self.publish(event)
        return event

    def clear(self) -> None:
        self.history.clear()

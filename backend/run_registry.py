"""Run ownership registry (v0.7.2 spec task P0-01 #3 / #7).

v0.7.1 authenticated a WebSocket *token*, which is not the same thing as
authorising a *subscription*.  Anyone holding a valid token could subscribe to
``/api/ws/run/{run_id}`` for **any** run by guessing or observing its id -- the
spec calls this out explicitly ("不能只检查令牌是否有效", "防止不同用户之间通过
猜测或泄露运行 ID 订阅其他人的事件").

This module records which principal started which run, so the socket layer can
answer "may *this* caller watch *that* run?" rather than merely "is this caller
authenticated?".

The registry is process-local and in-memory on purpose: a run only lives as
long as the backend process that executes it, so persisting ownership would
create stale grants after a restart.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from backend.security import (
    PRINCIPAL_DEV,
    REASON_FOREIGN_RUN,
    REASON_UNKNOWN_RUN,
    REASON_OK,
)

__all__ = ["RunOwnership", "RunRegistry", "register_run", "may_subscribe", "run_snapshot"]


@dataclass
class RunOwnership:
    """Who created a run, and when."""

    run_id: str
    principal: str
    kind: str = "api"          # "api" | "workflow" | "agent" | "external"
    created_at: float = field(default_factory=time.time)
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "principal": self.principal,
            "kind": self.kind,
            "created_at": self.created_at,
            "extra": dict(self.extra),
        }


class RunRegistry:
    """Thread-safe ``run_id -> owner`` map."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._runs: Dict[str, RunOwnership] = {}

    def register(
        self,
        run_id: str,
        principal: Optional[str],
        *,
        kind: str = "api",
        **extra: Any,
    ) -> RunOwnership:
        """Record that ``principal`` created ``run_id``."""
        owner = RunOwnership(
            run_id=run_id,
            principal=principal or PRINCIPAL_DEV,
            kind=kind,
            extra=dict(extra),
        )
        with self._lock:
            self._runs[run_id] = owner
        return owner

    def owner(self, run_id: str) -> Optional[str]:
        with self._lock:
            record = self._runs.get(run_id)
        return record.principal if record else None

    def get(self, run_id: str) -> Optional[RunOwnership]:
        with self._lock:
            return self._runs.get(run_id)

    def forget(self, run_id: str) -> None:
        with self._lock:
            self._runs.pop(run_id, None)

    def snapshot(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [record.to_dict() for record in self._runs.values()]

    def may_subscribe(self, run_id: str, principal: Optional[str]) -> Tuple[bool, str]:
        """Return ``(allowed, reason)`` for subscribing to ``run_id``.

        * loopback developer mode (principal ``dev``) -- allowed, the API is
          explicitly open and reports itself as such;
        * the run's recorded owner -- allowed;
        * a *known* run owned by somebody else -- refused (``run_not_owned``);
        * an *unknown* run -- refused (``unknown_run``).  The documented client
          flow is POST-then-subscribe, so a subscription to a run this backend
          never created is either a typo or an enumeration attempt; guessing an
          id must not grant access.
        """
        if principal == PRINCIPAL_DEV:
            return True, REASON_OK
        if not principal:
            return False, REASON_UNKNOWN_RUN

        record = self.get(run_id)
        if record is None:
            return False, REASON_UNKNOWN_RUN
        if record.principal == principal or record.principal == PRINCIPAL_DEV:
            return True, REASON_OK
        return False, REASON_FOREIGN_RUN


#: Process-wide registry shared by the HTTP routers and the WebSocket layer.
_REGISTRY = RunRegistry()


def register_run(run_id: str, principal: Optional[str], *, kind: str = "api", **extra: Any) -> RunOwnership:
    return _REGISTRY.register(run_id, principal, kind=kind, **extra)


def may_subscribe(run_id: str, principal: Optional[str]) -> Tuple[bool, str]:
    return _REGISTRY.may_subscribe(run_id, principal)


def run_snapshot() -> List[Dict[str, Any]]:
    return _REGISTRY.snapshot()


def get_registry() -> RunRegistry:
    """The process-wide registry (exposed for tests and diagnostics)."""
    return _REGISTRY

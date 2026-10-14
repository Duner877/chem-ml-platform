"""WebSocket endpoint streaming live workflow execution events.

**v0.7.2 (spec task P0-01).**  v0.7.1 forwarded every engine event to anyone who
connected: the auth middleware returned early for any non-HTTP scope, and the
socket never checked that the caller was allowed to watch *that* run.  A
loopback API is still reachable by every process on the machine and by any web
page the user visits, so "it is only local" is not an access-control policy.

The connection now has to clear three independent gates before a single event
is delivered:

1. **Origin** -- an allowlist check, refused *before* ``accept()`` so the
   handshake itself fails (HTTP 403).  This is CSRF defence, never a stand-in
   for authentication.
2. **Authentication** -- the session token, taken from the
   ``Sec-WebSocket-Protocol`` subprotocol (preferred: a browser can set it, and
   it never lands in a URL), the ``X-ChemML-Token`` header, or -- discouraged
   but still supported -- ``?token=``.
3. **Authorisation** -- the run-level ownership check from
   :mod:`backend.run_registry`: a valid token may only subscribe to runs it
   created.

A refusal is always explicit: the socket is accepted, a structured error frame
is sent, and the socket is closed with a distinct application close code
(4401 unauthenticated / 4408 expired / 4403 forbidden / 4400 policy) so a
client can react without parsing prose.  Nothing about the presented credential
is ever echoed back or written to the audit log.
"""

from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.run_registry import may_subscribe, register_run, run_snapshot  # noqa: E402
from backend.security import (  # noqa: E402
    READ,
    append_audit,
    current_principal,
    load_security_config,
)
from backend.ws_auth import origin_from_headers, select_subprotocol  # noqa: E402

router = APIRouter(prefix="/ws", tags=["websocket"])


class ConnectionManager:
    """Track the websockets currently attached to a run."""

    def __init__(self) -> None:
        self.active: Dict[str, list] = {}

    def count(self) -> int:
        return sum(len(sockets) for sockets in self.active.values())

    async def connect(self, run_id: str, websocket: WebSocket, *, subprotocol: Optional[str] = None) -> None:
        if subprotocol:
            await websocket.accept(subprotocol=subprotocol)
        else:
            await websocket.accept()
        self.active.setdefault(run_id, []).append(websocket)

    def disconnect(self, run_id: str, websocket: WebSocket) -> None:
        sockets = self.active.get(run_id, [])
        if websocket in sockets:
            sockets.remove(websocket)
        if not sockets:
            self.active.pop(run_id, None)

    async def broadcast(self, run_id: str, message: Dict[str, Any]) -> None:
        """Send ``message`` to every socket of ``run_id``; drop dead ones."""
        for websocket in list(self.active.get(run_id, [])):
            try:
                await websocket.send_json(message)
            except Exception:  # noqa: BLE001 - client vanished mid-stream
                self.disconnect(run_id, websocket)


manager = ConnectionManager()


def _client_of(websocket: WebSocket) -> str:
    try:
        return str(websocket.client.host) if websocket.client else ""
    except Exception:  # noqa: BLE001
        return ""


def _handshake_inputs(websocket: WebSocket):
    """Collect the raw handshake fields (headers / query / subprotocols)."""
    headers = list(websocket.scope.get("headers", []) or [])
    query = websocket.scope.get("query_string", b"") or b""
    protocols: List[str] = list(websocket.scope.get("subprotocols", []) or [])
    if not protocols:
        # Fallback: uvicorn may not populate ``subprotocols`` for every server.
        for name, value in headers:
            if name.decode("latin-1").lower() == "sec-websocket-protocol":
                protocols = [p.strip() for p in value.decode("latin-1").split(",") if p.strip()]
                break
    return headers, query, protocols


def _audit_ws(config, websocket: WebSocket, *, run_id: str, permission: str,
              outcome: str, reason: str) -> None:
    append_audit(
        config,
        method="WS",
        path=f"/api/ws/run/{run_id}",
        permission=permission,
        outcome=outcome,
        client=_client_of(websocket),
        reason=reason,
        transport="websocket",
    )


@router.websocket("/run/{run_id}")
async def run_stream(websocket: WebSocket, run_id: str) -> None:
    """Stream engine events for ``run_id`` once the caller is authorised.

    The documented flow is: ``POST /api/workflows/{file}/run`` (which registers
    the run against the calling principal), then subscribe here with the same
    ``run_id`` and the same credential.
    """
    config = load_security_config()
    headers, query, protocols = _handshake_inputs(websocket)
    origin = origin_from_headers(headers)
    subprotocol = select_subprotocol(protocols)

    # -- gate 1: Origin (refused before accept -> HTTP 403 at the handshake) --
    if not config.origin_allowed(origin):
        _audit_ws(config, websocket, run_id=run_id, permission=READ,
                  outcome="deny", reason="origin_not_allowed")
        await websocket.close(code=4400)
        return

    # -- gate 2 + 3: authentication, then run-level authorisation ------------ #
    from backend.ws_auth import authorize_handshake

    decision = authorize_handshake(
        config,
        origin=origin,
        headers=headers,
        query_string=query,
        protocols=protocols,
        permission=READ,
        run_id=run_id,
        may_subscribe=may_subscribe,
    )

    if not decision.allowed:
        _audit_ws(config, websocket, run_id=run_id, permission=READ,
                  outcome="deny", reason=decision.reason)
        # Accept first so the client receives a machine-readable reason *and* a
        # specific close code instead of an opaque "connection failed".
        if subprotocol:
            await websocket.accept(subprotocol=subprotocol)
        else:
            await websocket.accept()
        try:
            await websocket.send_json(decision.error_frame())
        except Exception:  # noqa: BLE001 - the peer may already be gone
            pass
        await websocket.close(code=decision.close_code)
        return

    _audit_ws(config, websocket, run_id=run_id, permission=READ,
              outcome="allow", reason=f"principal={decision.principal}")

    await manager.connect(run_id, websocket, subprotocol=subprotocol)
    await websocket.send_json(
        {
            "type": "connected",
            "run_id": run_id,
            "principal": decision.principal,
            "message": "listening for events",
        }
    )
    try:
        while True:
            # Keep the socket open; the engine pushes events from its own
            # thread pool through ``manager.broadcast``.  Incoming text is
            # ignored -- the socket is a one-way event stream.
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(run_id, websocket)
    except Exception:  # noqa: BLE001 - never let one client kill the server
        manager.disconnect(run_id, websocket)


def make_listener(run_id: str):
    """Return an engine event listener that forwards to the websockets."""

    async def _send(event: Any) -> None:
        payload = (
            event.to_dict()
            if hasattr(event, "to_dict")
            else {"type": getattr(event, "type", "event"), "message": str(event)}
        )
        payload.setdefault("run_id", run_id)
        await manager.broadcast(run_id, payload)

    return _send


@router.get("/sessions")
async def active_sessions() -> Dict[str, Any]:
    """Diagnostics: how many sockets are attached to each run.

    Requires the ``execute`` permission (see ``ROUTE_RULES``) and is hidden in
    release builds -- debug endpoints must not be reachable in a packaged app
    (spec P1-02).
    """
    from fastapi import HTTPException

    config = load_security_config()
    if config.is_release:
        raise HTTPException(status_code=404, detail="not found")
    return {
        "sockets": manager.count(),
        "runs": {run_id: len(sockets) for run_id, sockets in manager.active.items()},
        "ownership": run_snapshot(),
    }


def new_run_id() -> str:
    """A fresh run id a client can hand to both the POST and the socket."""
    return f"api_{uuid.uuid4().hex[:12]}"


def dump_event(event: Any) -> str:
    """Serialise an engine event for logging / debugging."""
    payload = (
        event.to_dict()
        if hasattr(event, "to_dict")
        else {"type": getattr(event, "type", "event"), "message": str(event)}
    )
    return json.dumps(payload, ensure_ascii=False, default=str)


__all__ = [
    "router",
    "manager",
    "make_listener",
    "new_run_id",
    "dump_event",
    "register_run",
    "current_principal",
]

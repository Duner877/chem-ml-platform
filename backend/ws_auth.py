"""WebSocket handshake authentication (v0.7.2 spec task P0-01).

The HTTP layer gets its credentials from headers, but a browser ``WebSocket``
cannot set arbitrary headers.  The v0.7.1 code simply let **every** non-HTTP
scope through (``if scope.get("type") != "http": return await self.app(...)``),
so ``/api/ws/run/{run_id}`` was fully unauthenticated and unlisted in the
permission table -- a hole the spec names as the first release blocker.

This module holds the *pure* decision logic so it can be unit-tested without a
server.  :func:`authorize_handshake` returns a structured decision with a
distinct close code and reason, so the client is told precisely why it was
refused instead of seeing a generic disconnect.

Credential sources, in preference order (spec P0-01 #4 -- a token should not be
left in a URL that ends up in logs and browser history):

1. ``Sec-WebSocket-Protocol: chemml.token.<token>`` -- a subprotocol.  The
   browser can set this from JavaScript, and, critically, it survives the
   handshake exactly like a header.  The server must echo the chosen
   subprotocol back, which the caller does via ``accept(subprotocol=...)``.
2. ``X-ChemML-Token`` header -- available to native clients (the bundled
   desktop shell, tests, the Python SDK).
3. ``?token=`` query parameter -- **legacy and discouraged**; accepted only so
   existing integrations keep working, and reported as such in the audit log.

An ``Origin`` allowlist is enforced as CSRF defence.  The spec is explicit that
an origin check must never stand in for authentication, so both checks run
independently and either can refuse the connection.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

from backend.security import (
    CLOSE_EXPIRED,
    CLOSE_FORBIDDEN,
    CLOSE_POLICY,
    CLOSE_UNAUTHENTICATED,
    EXECUTE,
    PRINCIPAL_DEV,
    REASON_EXPIRED,
    REASON_FOREIGN_RUN,
    REASON_INVALID,
    REASON_MISSING,
    REASON_OK,
    REASON_ORIGIN,
    REASON_SCOPE,
    REASON_UNKNOWN_RUN,
    READ,
    SecurityConfig,
)

__all__ = [
    "SUBPROTOCOL_PREFIX",
    "HandshakeDecision",
    "extract_token",
    "origin_from_headers",
    "select_subprotocol",
    "authorize_handshake",
    "REASON_HTTP_STATUS",
]

logger = logging.getLogger(__name__)

#: Token-bearing subprotocol prefix.  The full value is
#: ``chemml.token.<urlsafe-token>``.
SUBPROTOCOL_PREFIX = "chemml.token."

#: Human-readable HTTP status a client would see when the handshake is refused
#: before ``accept()`` (Starlette answers 403 for a pre-accept close).
REASON_HTTP_STATUS: Dict[str, int] = {
    REASON_MISSING: 401,
    REASON_INVALID: 401,
    REASON_EXPIRED: 401,
    REASON_SCOPE: 403,
    REASON_ORIGIN: 403,
    REASON_FOREIGN_RUN: 403,
    REASON_UNKNOWN_RUN: 403,
}

#: Reason -> application close code, used when the socket is accepted first so
#: the client can read a structured error frame.
REASON_CLOSE_CODE: Dict[str, int] = {
    REASON_MISSING: CLOSE_UNAUTHENTICATED,
    REASON_INVALID: CLOSE_UNAUTHENTICATED,
    REASON_EXPIRED: CLOSE_EXPIRED,
    REASON_SCOPE: CLOSE_FORBIDDEN,
    REASON_ORIGIN: CLOSE_POLICY,
    REASON_FOREIGN_RUN: CLOSE_FORBIDDEN,
    REASON_UNKNOWN_RUN: CLOSE_FORBIDDEN,
}


@dataclass(frozen=True)
class HandshakeDecision:
    """Outcome of authenticating + authorising a WebSocket handshake."""

    allowed: bool
    reason: str
    principal: Optional[str] = None
    permission: str = READ
    origin: Optional[str] = None
    subprotocol: Optional[str] = None
    token_source: str = "none"
    run_id: str = ""

    @property
    def close_code(self) -> int:
        if self.allowed:
            return 1000
        return REASON_CLOSE_CODE.get(self.reason, CLOSE_POLICY)

    @property
    def http_status(self) -> int:
        return REASON_HTTP_STATUS.get(self.reason, 403)

    def error_frame(self) -> Dict[str, object]:
        """Client-facing error payload -- never echoes the presented token."""
        return {
            "type": "error",
            "code": "WS_AUTH_ERROR",
            "reason": self.reason,
            "message": {
                REASON_MISSING: "未提供会话令牌，WebSocket 连接被拒绝。",
                REASON_INVALID: "会话令牌无效，WebSocket 连接被拒绝。",
                REASON_EXPIRED: "会话令牌已过期，请重新启动应用。",
                REASON_SCOPE: "当前会话权限不足，无法订阅该事件流。",
                REASON_ORIGIN: "来源（Origin）不在允许列表中，连接被拒绝。",
                REASON_FOREIGN_RUN: "该运行任务不属于当前会话，订阅被拒绝。",
                REASON_UNKNOWN_RUN: "未知的运行任务标识，订阅被拒绝。",
            }.get(self.reason, "连接被拒绝。"),
            "run_id": self.run_id,
            "close_code": self.close_code,
        }


def origin_from_headers(headers: Sequence[Tuple[bytes, bytes]]) -> Optional[str]:
    """Return the ``Origin`` header value (decoded), or ``None``."""
    for name, value in headers or []:
        if name.decode("latin-1").lower() == "origin":
            return value.decode("latin-1").strip()
    return None


def extract_token(
    headers: Sequence[Tuple[bytes, bytes]],
    query_string: bytes = b"",
    protocols: Sequence[str] = (),
) -> Tuple[Optional[str], str, Optional[str]]:
    """Pull the session token out of a handshake.

    Returns ``(token, source, subprotocol)`` where ``source`` is one of
    ``"subprotocol" | "header" | "query" | "none"``.  The resolved subprotocol
    (when the token came that way) must be echoed back on ``accept``.
    """
    for protocol in protocols or []:
        if isinstance(protocol, str) and protocol.startswith(SUBPROTOCOL_PREFIX):
            token = protocol[len(SUBPROTOCOL_PREFIX):].strip()
            if token:
                return token, "subprotocol", protocol

    for name, value in headers or []:
        key = name.decode("latin-1").lower()
        if key == "x-chemml-token":
            token = value.decode("latin-1").strip()
            if token:
                return token, "header", None
        if key == "authorization":
            text = value.decode("latin-1").strip()
            if text.lower().startswith("bearer ") and text[7:].strip():
                return text[7:].strip(), "header", None

    query = (query_string or b"").decode("latin-1")
    for pair in query.split("&"):
        if pair.startswith("token=") and pair[6:]:
            return pair[6:], "query", None

    return None, "none", None


def select_subprotocol(protocols: Sequence[str]) -> Optional[str]:
    """The token subprotocol to echo back, if any (else ``None``)."""
    for protocol in protocols or []:
        if isinstance(protocol, str) and protocol.startswith(SUBPROTOCOL_PREFIX):
            return protocol
    return None


def authorize_handshake(
    config: SecurityConfig,
    *,
    origin: Optional[str] = None,
    headers: Sequence[Tuple[bytes, bytes]] = (),
    query_string: bytes = b"",
    protocols: Sequence[str] = (),
    permission: str = READ,
    run_id: str = "",
    may_subscribe=None,
) -> HandshakeDecision:
    """Authenticate the handshake, then authorise the requested subscription.

    ``may_subscribe`` is a callable ``(run_id, principal) -> (bool, reason)``
    used for the run-level check; when omitted (or ``run_id`` is empty) the
    run-level check is skipped so the function stays usable for a plain
    authenticated socket.
    """
    subprotocol = select_subprotocol(protocols)

    # 1. Origin first: never honour credentials that arrive from a disallowed
    #    origin, and be explicit that this is CSRF defence, not authentication.
    if not config.origin_allowed(origin):
        return HandshakeDecision(
            allowed=False, reason=REASON_ORIGIN, origin=origin,
            subprotocol=subprotocol, run_id=run_id,
        )

    # 2. Credential extraction.
    token, source, proto = extract_token(headers, query_string, protocols)

    # 3. Developer mode: explicitly open, and reported as such by /api/security/status.
    if not config.enforced:
        if config.fail_closed:
            return HandshakeDecision(
                allowed=False, reason=REASON_MISSING, origin=origin,
                subprotocol=subprotocol, run_id=run_id, token_source="none",
            )
        principal = PRINCIPAL_DEV
    else:
        allowed, reason = config.authorize(token or "", permission)
        if not allowed:
            return HandshakeDecision(
                allowed=False, reason=reason, origin=origin,
                permission=permission, subprotocol=subprotocol,
                token_source=source, run_id=run_id,
            )
        principal = config.identify(token or "")

    # 4. Run-level authorisation (P0-01 #3, #7) -- a valid token is not enough.
    if run_id and may_subscribe is not None:
        ok, reason = may_subscribe(run_id, principal)
        if not ok:
            return HandshakeDecision(
                allowed=False, reason=reason, principal=principal, origin=origin,
                permission=permission, subprotocol=subprotocol,
                token_source=source, run_id=run_id,
            )

    return HandshakeDecision(
        allowed=True, reason=REASON_OK, principal=principal, origin=origin,
        permission=permission, subprotocol=subprotocol,
        token_source=source, run_id=run_id,
    )


def stream_permission(path: str) -> str:
    """Permission required to subscribe to ``path`` (defaults to read).

    Kept as a hook so a future "trigger a run over the socket" endpoint can
    require ``execute`` without touching the handshake logic.
    """
    return EXECUTE if "/ws/execute" in path else READ

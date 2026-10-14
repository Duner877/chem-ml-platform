"""Local API authentication, authorisation and audit (v0.7.1 -- spec task D).

A desktop scientific application still exposes a loopback HTTP API, and any
process on the machine -- or a malicious web page the user visits -- could try
to reach it.  This module adds the boundary the v0.7.1 spec requires:

* **Session token** -- the launcher / Electron shell generates a random token
  and hands it to the backend (``CHEMML_SESSION_TOKEN``).  Requests to
  protected routes must present it (``X-ChemML-Token`` header,
  ``Authorization: Bearer`` or ``?token=``).
* **Permission categories** -- ``read`` / ``write`` / ``execute`` /
  ``external``.  A route declares the permission it needs; a read-only token
  can never reach a write or execute route ("只读操作不能隐式获得文件写入或
  命令执行能力").
* **Explicit CORS allowlist** -- never ``*`` (P1-03).
* **Audit log** -- every allow / deny decision is appended as one JSON line.

Auth is *enforced* when a token is configured; a bare ``uvicorn`` developer
run (no token) stays open on loopback only and reports this honestly through
``/api/security/status`` so it can never masquerade as a secured deployment.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

__all__ = [
    "READ",
    "WRITE",
    "EXECUTE",
    "EXTERNAL",
    "ALL_PERMISSIONS",
    "PRINCIPAL_FULL",
    "PRINCIPAL_READONLY",
    "PRINCIPAL_DEV",
    "REASON_OK",
    "REASON_MISSING",
    "REASON_INVALID",
    "REASON_EXPIRED",
    "REASON_SCOPE",
    "REASON_ORIGIN",
    "REASON_FOREIGN_RUN",
    "REASON_UNKNOWN_RUN",
    "CLOSE_UNAUTHENTICATED",
    "CLOSE_FORBIDDEN",
    "CLOSE_EXPIRED",
    "CLOSE_POLICY",
    "RouteRule",
    "SecurityConfig",
    "AuthMiddleware",
    "load_security_config",
    "classify_route",
    "generate_token",
    "append_audit",
    "current_principal",
]

ROOT = Path(__file__).resolve().parents[1]

#: Permission categories -- a route declares which one it needs and a token
#: must be granted it.  Kept as plain strings so they serialise trivially.
READ = "read"
WRITE = "write"
EXECUTE = "execute"
EXTERNAL = "external"

ALL_PERMISSIONS = frozenset({READ, WRITE, EXECUTE, EXTERNAL})

#: Principals (v0.7.2 task P0-01).  A *principal* is the identity a presented
#: credential resolves to.  Run-level authorisation uses it to decide whether a
#: socket may subscribe to a specific run -- a valid token is not enough.
PRINCIPAL_FULL = "full"          # the full session token
PRINCIPAL_READONLY = "readonly"  # the read-only token
PRINCIPAL_DEV = "dev"            # no auth configured (loopback developer mode)

#: Machine-readable authorisation reasons (v0.7.2).  Distinct reasons let the
#: HTTP layer answer 401 vs 403 and let the WebSocket layer send a specific
#: close code instead of an undifferentiated "connection failed".
REASON_OK = "ok"
REASON_MISSING = "missing_token"
REASON_INVALID = "invalid_token"
REASON_EXPIRED = "expired_token"
REASON_SCOPE = "insufficient_scope"
REASON_ORIGIN = "origin_not_allowed"
REASON_FOREIGN_RUN = "run_not_owned"
REASON_UNKNOWN_RUN = "unknown_run"

#: WebSocket close codes in the application-private range (4000-4999) so a
#: client can tell *why* it was rejected without parsing free text.
CLOSE_UNAUTHENTICATED = 4401  # no token / unknown token
CLOSE_FORBIDDEN = 4403        # valid token, insufficient scope or not the owner
CLOSE_EXPIRED = 4408          # token lifetime elapsed
CLOSE_POLICY = 4400           # malformed request (bad origin, bad subprotocol)


@dataclass(frozen=True)
class RouteRule:
    """Declarative permission requirement for a route pattern."""

    method: str          # "GET" | "POST" | ... | "*"
    pattern: re.Pattern  # matched against the request path
    permission: Optional[str]   # None -> public, no auth required
    note: str = ""


def _rule(method: str, pattern: str, permission: Optional[str], note: str = "") -> RouteRule:
    return RouteRule(method.upper(), re.compile(pattern), permission, note)


#: Ordered rules; the first match wins.  Anything unmatched defaults to READ.
ROUTE_RULES: List[RouteRule] = [
    # -- always public: liveness + the honest security report ------------- #
    _rule("GET", r"^/api/health$", None, "liveness probe"),
    _rule("GET", r"^/api/security/status$", None, "security posture report"),
    # Interactive API docs: they only *exist* in developer mode (``app.py``
    # omits the routes in release builds), so they are not a protected resource
    # -- the honest answer for a packaged build is 404, not 401.
    _rule("GET", r"^/api/docs$", None, "developer API docs (absent in release)"),
    _rule("GET", r"^/api/redoc$", None, "developer API docs (absent in release)"),
    _rule("GET", r"^/api/openapi\.json$", None, "developer API schema (absent in release)"),

    # -- external program invocation (most sensitive) -------------------- #
    _rule("POST", r"^/api/simulations/run$", EXTERNAL, "may launch external software"),

    # -- task execution: runs a workflow / agent / model ----------------- #
    # NOTE: the inline ``POST /api/workflows/run`` must be listed *before* the
    # ``.+`` pattern below, which only matches ``/api/workflows/<name>/run``.
    # v0.7.1 missed it, so the inline execution route fell through to the
    # default READ permission.
    _rule("POST", r"^/api/workflows/run$", EXECUTE, "inline workflow execution"),
    _rule("POST", r"^/api/workflows/.+/run$", EXECUTE, "workflow execution"),
    _rule("POST", r"^/api/workflows/.+/dry-run$", EXECUTE, "workflow dry run"),
    _rule("POST", r"^/api/agent/", EXECUTE, "agent task execution"),
    _rule("POST", r"^/api/ai/complete$", EXECUTE, "LLM completion"),
    _rule("POST", r"^/api/ai/test$", EXECUTE, "provider probe"),
    _rule("PUT", r"^/api/ai/config$", WRITE, "AI configuration change"),

    # -- filesystem mutation -------------------------------------------- #
    _rule("POST", r"^/api/storage/upload/", WRITE, "file upload"),
    _rule("POST", r"^/api/storage/extract/", WRITE, "archive extraction"),
    _rule("DELETE", r"^/api/storage/file/", WRITE, "file deletion"),
    _rule("POST", r"^/api/workflows$", WRITE, "workflow create"),
    _rule("PUT", r"^/api/workflows/", WRITE, "workflow update"),
    _rule("DELETE", r"^/api/workflows/", WRITE, "workflow deletion"),
    _rule("POST", r"^/api/data/ingest$", WRITE, "catalog ingest"),

    # -- diagnostics (v0.7.2 P1-02): never a public debug surface --------- #
    _rule("GET", r"^/api/ws/sessions$", EXECUTE, "websocket diagnostics"),
]


def classify_route(method: str, path: str) -> RouteRule:
    """Return the rule governing ``method path`` (default: READ)."""
    method = (method or "GET").upper()
    for rule in ROUTE_RULES:
        if rule.method in ("*", method) and rule.pattern.search(path):
            return rule
    return RouteRule(method, re.compile(".*"), READ, "default read")


def generate_token(nbytes: int = 32) -> str:
    """URL-safe random session token."""
    return secrets.token_urlsafe(nbytes)


@dataclass
class SecurityConfig:
    """Resolved security posture of the running backend."""

    mode: str = "off"                    # "token" | "off"
    token: str = ""
    readonly_token: str = ""
    allowed_origins: List[str] = field(default_factory=list)
    audit_path: Optional[Path] = None
    #: Permissions granted to the *full* token.
    granted: Set[str] = field(default_factory=lambda: set(ALL_PERMISSIONS))
    #: Permissions granted to the read-only token.
    readonly_granted: Set[str] = field(default_factory=lambda: {READ})
    #: ``dev``  -- loopback developer mode, debug endpoints allowed;
    #: ``release`` -- packaged desktop build: fail closed, no debug endpoints.
    environment: str = "dev"
    #: Token lifetime in seconds (0 = never expires).  v0.7.2 task P0-01 #5.
    ttl_seconds: int = 0
    #: When the current session token was minted (unix seconds, 0 = unknown).
    issued_at: float = 0.0

    @property
    def enforced(self) -> bool:
        return self.mode == "token" and bool(self.token)

    @property
    def is_release(self) -> bool:
        return self.environment == "release"

    @property
    def expired(self) -> bool:
        """True when a TTL is configured and the session has outlived it."""
        if self.ttl_seconds <= 0 or self.issued_at <= 0:
            return False
        return (time.time() - self.issued_at) > self.ttl_seconds

    @property
    def fail_closed(self) -> bool:
        """Release builds must never fall back to an open API.

        A packaged desktop app that somehow lost its token must deny protected
        routes rather than silently serving an unauthenticated loopback API.
        """
        return self.is_release and not self.enforced

    # -- identity ------------------------------------------------------------ #
    def identify(self, presented: str) -> Optional[str]:
        """Resolve a presented credential to a principal (``None`` = unknown).

        Uses a constant-time comparison so a token cannot be recovered by
        timing the response.
        """
        if not presented:
            return None
        if self.token and secrets.compare_digest(presented, self.token):
            return PRINCIPAL_FULL
        if self.readonly_token and secrets.compare_digest(presented, self.readonly_token):
            return PRINCIPAL_READONLY
        return None

    # -- authorisation ------------------------------------------------------- #
    def authorize(self, presented: str, permission: str) -> Tuple[bool, str]:
        """Return ``(allowed, reason)`` -- never a bare boolean.

        v0.7.1 returned a bool, which made "no credential" and "wrong
        credential" indistinguishable at the API boundary.  v0.7.2 needs the
        distinction to answer 401-vs-403 and to log an honest audit reason.
        """
        if not self.enforced:
            # Loopback developer mode: the API is open by design, and the
            # posture endpoint says so.  Release builds never reach this branch
            # because ``fail_closed`` denies first.
            if self.fail_closed:
                return False, REASON_MISSING
            return True, REASON_OK
        if not presented:
            return False, REASON_MISSING
        principal = self.identify(presented)
        if principal is None:
            return False, REASON_INVALID
        if self.expired:
            return False, REASON_EXPIRED
        scope = self.granted if principal == PRINCIPAL_FULL else self.readonly_granted
        if permission in scope:
            return True, REASON_OK
        return False, REASON_SCOPE

    def authorizes(self, presented: str, permission: str) -> bool:
        """Backwards-compatible bool wrapper around :meth:`authorize`."""
        return self.authorize(presented, permission)[0]

    def principal_permissions(self, principal: Optional[str]) -> Set[str]:
        if principal == PRINCIPAL_FULL:
            return set(self.granted)
        if principal == PRINCIPAL_READONLY:
            return set(self.readonly_granted)
        return set(ALL_PERMISSIONS)  # dev mode

    # -- origin -------------------------------------------------------------- #
    def origin_allowed(self, origin: Optional[str]) -> bool:
        """Allowlist check for the ``Origin`` header.

        A missing ``Origin`` means a non-browser client (the bundled desktop
        renderer and CLI tools do not always send one) and is allowed.  This is
        a **CSRF defence only** -- the spec is explicit that an origin check is
        never a substitute for authentication.
        """
        if not origin:
            return True
        normalised = origin.strip().rstrip("/")
        if normalised in self.allowed_origins:
            return True
        # Same-origin loopback requests (any port) are always acceptable: the
        # server itself only binds 127.0.0.1.
        if re.match(r"^https?://(127\.0\.0\.1|localhost|\[::1\])(:\d+)?$", normalised):
            return True
        return False

    # -- reporting ------------------------------------------------------------ #
    def status(self) -> Dict[str, object]:
        """Honest, secret-free description of the current posture."""
        return {
            "auth_enforced": self.enforced,
            "mode": self.mode,
            "environment": self.environment,
            "fail_closed": self.fail_closed,
            "token_ttl_seconds": self.ttl_seconds,
            "expired": self.expired,
            "readonly_token_configured": bool(self.readonly_token),
            "allowed_origins": list(self.allowed_origins),
            "permissions": sorted(self.granted) if self.enforced else [],
            "readonly_permissions": sorted(self.readonly_granted) if self.enforced else [],
            "websocket": {
                "authentication": "required" if self.enforced else "disabled",
                "run_level_authorisation": True,
                "origin_check": "allowlist",
                "token_sources": [
                    "Sec-WebSocket-Protocol: chemml.token.<token>",
                    "X-ChemML-Token header",
                    "?token= query (legacy; discouraged)",
                ],
            },
            "note": (
                "token auth enforced"
                if self.enforced
                else (
                    "RELEASE MODE without a session token -- protected routes fail closed"
                    if self.fail_closed
                    else "no session token configured -- loopback-only developer mode; "
                         "launch via the desktop shell or start-platform.bat to enable "
                         "session-token authentication"
                )
            ),
        }


DEFAULT_ORIGINS = [
    "http://127.0.0.1:8000",
    "http://localhost:8000",
    "http://127.0.0.1:5173",
    "http://localhost:5173",
]


def _parse_origins(raw: str) -> List[str]:
    values = [item.strip().rstrip("/") for item in raw.split(",") if item.strip()]
    # Never allow a wildcard through; the spec forbids it explicitly.
    return [item for item in values if item != "*"]


def load_security_config(environ: Optional[Dict[str, str]] = None) -> SecurityConfig:
    """Build the security config from the environment (and config/session.json)."""
    env = dict(os.environ if environ is None else environ)

    token = env.get("CHEMML_SESSION_TOKEN", "").strip()
    readonly = env.get("CHEMML_READONLY_TOKEN", "").strip()

    # The desktop shell / launcher drops the token in config/session.json so a
    # bare `uvicorn` restart re-uses the same session without leaking it via
    # the process list.
    if not token:
        session_file = ROOT / "config" / "session.json"
        if session_file.exists():
            try:
                data = json.loads(session_file.read_text(encoding="utf-8"))
                token = str(data.get("token", "") or "").strip()
                readonly = readonly or str(data.get("readonly_token", "") or "").strip()
            except (OSError, ValueError):
                token = ""

    mode = env.get("CHEMML_AUTH_MODE", "").strip().lower()
    if not mode:
        mode = "token" if token else "off"

    environment = env.get("CHEMML_ENV", "").strip().lower() or ("release" if mode == "token" else "dev")
    if environment not in {"dev", "release"}:
        environment = "dev"

    try:
        ttl = int(env.get("CHEMML_SESSION_TTL", "0") or 0)
    except ValueError:
        ttl = 0
    try:
        issued_at = float(env.get("CHEMML_SESSION_ISSUED_AT", "0") or 0)
    except ValueError:
        issued_at = 0.0
    if issued_at <= 0 and token:
        # The launcher writes the token into config/session.json; its mtime is
        # the best honest answer for "when was this session minted".
        session_file = ROOT / "config" / "session.json"
        try:
            issued_at = session_file.stat().st_mtime
        except OSError:
            issued_at = 0.0

    origins_raw = env.get("CHEMML_ALLOWED_ORIGINS", "")
    origins = _parse_origins(origins_raw) if origins_raw else list(DEFAULT_ORIGINS)
    # An Electron renderer served from the backend origin or a file:// URL
    # sends Origin: null; allow it only when explicitly enabled.
    if env.get("CHEMML_ALLOW_NULL_ORIGIN", "").strip() in {"1", "true", "yes"}:
        origins.append("null")

    audit_path = Path(env.get("CHEMML_AUDIT_LOG", str(ROOT / "output" / "security_audit.jsonl")))

    return SecurityConfig(
        mode=mode,
        token=token,
        readonly_token=readonly,
        allowed_origins=origins,
        audit_path=audit_path,
        environment=environment,
        ttl_seconds=ttl,
        issued_at=issued_at,
    )


def _extract_token(scope: dict) -> str:
    """Pull the session token out of headers or the query string."""
    for name, value in scope.get("headers", []):
        key = name.decode("latin-1").lower()
        if key == "x-chemml-token":
            return value.decode("latin-1").strip()
        if key == "authorization":
            text = value.decode("latin-1").strip()
            if text.lower().startswith("bearer "):
                return text[7:].strip()
    query = scope.get("query_string", b"").decode("latin-1")
    for pair in query.split("&"):
        if pair.startswith("token="):
            return pair[6:]
    return ""


def current_principal(scope_or_request: Any) -> Optional[str]:
    """The principal the auth middleware attached to this request, if any.

    Routers use this to record *ownership* of the resources they create (see
    :mod:`backend.run_registry`).  Returns ``None`` when auth is disabled --
    callers then fall back to the ``dev`` principal.
    """
    scope = getattr(scope_or_request, "scope", scope_or_request)
    try:
        state = scope.get("state") or {}
    except AttributeError:
        return None
    return state.get("chemml_principal")


def append_audit(
    config: SecurityConfig,
    *,
    method: str,
    path: str,
    permission: str,
    outcome: str,
    client: str = "",
    reason: str = "",
    transport: str = "http",
) -> bool:
    """Append one audit record.  Returns False when auditing is unavailable.

    Auditing must never break the request path, so all I/O errors are swallowed
    -- but the caller is told so it can stop trying.  **Credentials are never
    written**: only the outcome, the reason code and a coarse client address.
    """
    if config.audit_path is None:
        return False
    record = {
        "at": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + "Z",
        "transport": transport,
        "method": method,
        "path": path,
        "permission": permission,
        "outcome": outcome,
        "client": client,
        "reason": reason,
    }
    try:
        config.audit_path.parent.mkdir(parents=True, exist_ok=True)
        with config.audit_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        return True
    except OSError:
        return False


class AuthMiddleware:
    """Pure-ASGI middleware enforcing the session token and writing the audit log."""

    def __init__(self, app, config: SecurityConfig):
        self.app = app
        self.config = config
        self._audit_disabled = False

    # -- audit ---------------------------------------------------------------- #
    def _audit(self, *, method: str, path: str, permission: str,
               outcome: str, client: str, reason: str = "") -> None:
        if self._audit_disabled:
            return
        ok = append_audit(
            self.config, method=method, path=path, permission=permission,
            outcome=outcome, client=client, reason=reason, transport="http",
        )
        if not ok and self.config.audit_path is not None:
            self._audit_disabled = True

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            return await self.app(scope, receive, send)

        path = scope.get("path", "")
        method = scope.get("method", "GET")

        # Only the platform API is governed; static assets stay open.
        if not path.startswith("/api"):
            return await self.app(scope, receive, send)

        # CORS pre-flight carries no credentials by design -- let the CORS
        # middleware answer it (it still enforces the allowlist).
        if method == "OPTIONS":
            return await self.app(scope, receive, send)

        rule = classify_route(method, path)
        if rule.permission is None:
            return await self.app(scope, receive, send)
        if not self.config.enforced and not self.config.fail_closed:
            return await self.app(scope, receive, send)

        presented = _extract_token(scope)
        client = ""
        try:
            client = scope.get("client", ("", 0))[0]
        except Exception:
            client = ""

        allowed, reason = self.config.authorize(presented, rule.permission)
        if allowed:
            # Record *who* this request is so routers can attach ownership to
            # the resources they create (v0.7.2 task P0-01 #3).
            try:
                scope.setdefault("state", {})["chemml_principal"] = (
                    self.config.identify(presented) or PRINCIPAL_DEV
                )
            except Exception:  # noqa: BLE001 - never block a request on bookkeeping
                pass
            self._audit(method=method, path=path, permission=rule.permission,
                        outcome="allow", client=client, reason=rule.note)
            return await self.app(scope, receive, send)

        self._audit(method=method, path=path, permission=rule.permission,
                    outcome="deny", client=client, reason=reason)

        from starlette.responses import JSONResponse

        # 401 = "we could not establish who you are"; 403 = "we know who you
        # are, and you still may not do this".  The spec requires the two to be
        # distinguishable (P0-01 #5).
        status = 401 if reason in {REASON_MISSING, REASON_INVALID, REASON_EXPIRED} else 403
        payload = {
            "code": "API_AUTH_ERROR" if status == 401 else "API_FORBIDDEN",
            "message": {
                REASON_MISSING: "未提供会话令牌，请通过桌面应用或启动脚本打开。",
                REASON_INVALID: "会话令牌无效。",
                REASON_EXPIRED: "会话令牌已过期，请重新启动应用。",
                REASON_SCOPE: "当前会话权限不足，无法执行该操作。",
            }.get(reason, "拒绝访问。"),
            "technical": f"{method} {path} requires '{rule.permission}' permission ({reason})",
            "reason": reason,
            "recoverable": reason == REASON_EXPIRED,
            "suggested_action": (
                "重新启动应用以获取新的会话令牌。"
                if reason == REASON_EXPIRED
                else "使用 start-platform.bat 或桌面应用启动以获得会话令牌。"
            ),
        }
        return await JSONResponse(payload, status_code=status)(scope, receive, send)

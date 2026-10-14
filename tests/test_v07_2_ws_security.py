"""v0.7.2 spec task P0-01 -- unified HTTP / WebSocket security policy.

Covers the acceptance scenarios from the task book §七 场景 B:

1. unauthenticated connection          -> refuse (4401)
2. wrong token                         -> refuse (4401)
3. expired token                       -> refuse (4408)
4. valid token, no permission on run   -> refuse (4403)
5. valid token + owned run             -> accept and subscribe
6. disconnect / audit handling         -> no credential ever written

Plus the HTTP/WebSocket *parity* checks: the same run-level rule must guard
``GET /api/workflows/runs/{id}/events``, otherwise the socket check is
decorative.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from backend import run_registry
from backend.security import (
    CLOSE_EXPIRED,
    CLOSE_FORBIDDEN,
    CLOSE_UNAUTHENTICATED,
)


TOKEN = "full-session-token"
READONLY = "readonly-session-token"
ORIGIN = "http://127.0.0.1:8000"


@pytest.fixture()
def secured(monkeypatch, tmp_path):
    """A release-mode app with a full token, a read-only token and an audit log."""
    monkeypatch.setenv("CHEMML_SESSION_TOKEN", TOKEN)
    monkeypatch.setenv("CHEMML_READONLY_TOKEN", READONLY)
    monkeypatch.setenv("CHEMML_AUTH_MODE", "token")
    monkeypatch.setenv("CHEMML_ENV", "release")
    monkeypatch.setenv("CHEMML_ALLOWED_ORIGINS", ORIGIN)
    monkeypatch.setenv("CHEMML_AUDIT_LOG", str(tmp_path / "audit.jsonl"))
    monkeypatch.setenv("CHEMML_SESSION_TTL", "0")
    monkeypatch.delenv("CHEMML_SESSION_ISSUED_AT", raising=False)

    from backend.app import create_app

    app = create_app()
    client = TestClient(app)
    audit = tmp_path / "audit.jsonl"
    run_registry.get_registry().forget("rid_owned")
    run_registry.get_registry().forget("rid_foreign")
    run_registry.register_run("rid_owned", "full")
    run_registry.register_run("rid_foreign", "readonly")
    return client, audit


def _ws_reject(client, url, **kwargs):
    """Connect and return (error_frame, close_code) for a refused socket."""
    with client.websocket_connect(url, **kwargs) as ws:
        frame = ws.receive_json()
        assert frame["type"] == "error"
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
        return frame, exc.value.code


class TestWebSocketAuthentication:
    """场景 B.1 / B.2 -- no credential and wrong credential are both refused."""

    def test_missing_token_is_refused(self, secured):
        client, _ = secured
        frame, code = _ws_reject(client, "/api/ws/run/rid_owned")
        assert frame["reason"] == "missing_token"
        assert code == CLOSE_UNAUTHENTICATED

    def test_wrong_token_is_refused(self, secured):
        client, _ = secured
        frame, code = _ws_reject(
            client, "/api/ws/run/rid_owned", headers={"x-chemml-token": "not-a-token"}
        )
        assert frame["reason"] == "invalid_token"
        assert code == CLOSE_UNAUTHENTICATED

    def test_bearer_header_is_accepted(self, secured):
        client, _ = secured
        with client.websocket_connect(
            "/api/ws/run/rid_owned", headers={"Authorization": f"Bearer {TOKEN}"}
        ) as ws:
            assert ws.receive_json()["type"] == "connected"

    def test_subprotocol_token_is_preferred_over_query(self, secured):
        client, _ = secured
        with client.websocket_connect(
            "/api/ws/run/rid_owned",
            subprotocols=[f"chemml.token.{TOKEN}"],
        ) as ws:
            hello = ws.receive_json()
            assert hello["type"] == "connected"
            assert hello["principal"] == "full"

    def test_legacy_query_token_still_works(self, secured):
        client, _ = secured
        with client.websocket_connect(f"/api/ws/run/rid_owned?token={TOKEN}") as ws:
            assert ws.receive_json()["type"] == "connected"

    def test_error_frame_never_echoes_the_token(self, secured):
        client, _ = secured
        secret = "leaky-token-value"
        frame, _ = _ws_reject(
            client, "/api/ws/run/rid_owned", headers={"x-chemml-token": secret}
        )
        assert secret not in json.dumps(frame)


class TestWebSocketExpiry:
    """場景 B.3 -- an expired token must not open a new protected socket."""

    def test_expired_token_is_refused(self, monkeypatch, tmp_path):
        monkeypatch.setenv("CHEMML_SESSION_TOKEN", TOKEN)
        monkeypatch.setenv("CHEMML_AUTH_MODE", "token")
        monkeypatch.setenv("CHEMML_ENV", "release")
        monkeypatch.setenv("CHEMML_SESSION_TTL", "60")
        monkeypatch.setenv("CHEMML_SESSION_ISSUED_AT", str(time.time() - 3600))
        monkeypatch.setenv("CHEMML_AUDIT_LOG", str(tmp_path / "audit.jsonl"))

        from backend.app import create_app

        client = TestClient(create_app())
        run_registry.register_run("rid_owned", "full")
        frame, code = _ws_reject(
            client, "/api/ws/run/rid_owned", headers={"x-chemml-token": TOKEN}
        )
        assert frame["reason"] == "expired_token"
        assert code == CLOSE_EXPIRED


class TestWebSocketRunAuthorization:
    """場景 B.4 / B.5 -- a valid token is not enough; ownership decides."""

    def test_foreign_run_is_refused(self, secured):
        client, _ = secured
        # The readonly token is a *valid* credential, but rid_owned belongs to
        # the full principal.
        frame, code = _ws_reject(
            client, "/api/ws/run/rid_owned", headers={"x-chemml-token": READONLY}
        )
        assert frame["reason"] == "run_not_owned"
        assert code == CLOSE_FORBIDDEN

    def test_unknown_run_is_refused(self, secured):
        client, _ = secured
        frame, code = _ws_reject(
            client, "/api/ws/run/never-registered", headers={"x-chemml-token": TOKEN}
        )
        assert frame["reason"] == "unknown_run"
        assert code == CLOSE_FORBIDDEN

    def test_owner_may_subscribe(self, secured):
        client, _ = secured
        with client.websocket_connect(
            "/api/ws/run/rid_owned", headers={"x-chemml-token": TOKEN}
        ) as ws:
            hello = ws.receive_json()
            assert hello["run_id"] == "rid_owned"
            assert hello["principal"] == "full"

    def test_issuing_session_can_watch_its_own_readonly_run(self, secured):
        client, _ = secured
        with client.websocket_connect(
            "/api/ws/run/rid_foreign", headers={"x-chemml-token": READONLY}
        ) as ws:
            assert ws.receive_json()["principal"] == "readonly"


class TestWebSocketOrigin:
    """Origin is CSRF defence and is refused *before* the socket is accepted."""

    def test_foreign_origin_is_refused_at_handshake(self, secured):
        client, _ = secured
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect(
                "/api/ws/run/rid_owned",
                headers={"x-chemml-token": TOKEN, "origin": "http://evil.example"},
            ):
                pass

    def test_loopback_origin_is_allowed(self, secured):
        client, _ = secured
        with client.websocket_connect(
            "/api/ws/run/rid_owned",
            headers={"x-chemml-token": TOKEN, "origin": ORIGIN},
        ) as ws:
            assert ws.receive_json()["type"] == "connected"


class TestHttpParity:
    """HTTP must enforce the same policy, or the socket check is bypassable."""

    def test_unauthenticated_read_is_401(self, secured):
        client, _ = secured
        assert client.get("/api/nodes").status_code == 401

    def test_bad_token_read_is_401(self, secured):
        client, _ = secured
        resp = client.get("/api/nodes", headers={"x-chemml-token": "nope"})
        assert resp.status_code == 401
        assert resp.json()["reason"] == "invalid_token"

    def test_readonly_token_may_read(self, secured):
        client, _ = secured
        assert client.get("/api/nodes", headers={"x-chemml-token": READONLY}).status_code == 200

    def test_readonly_token_may_not_execute(self, secured):
        client, _ = secured
        resp = client.post(
            "/api/workflows/run",
            headers={"x-chemml-token": READONLY},
            json={"nodes": [], "edges": []},
        )
        assert resp.status_code == 403
        assert resp.json()["reason"] == "insufficient_scope"

    def test_run_events_endpoint_enforces_ownership(self, secured):
        client, _ = secured
        resp = client.get(
            "/api/workflows/runs/rid_owned/events", headers={"x-chemml-token": READONLY}
        )
        assert resp.status_code == 403

    def test_run_status_hides_foreign_runs(self, secured):
        client, _ = secured
        resp = client.get(
            "/api/workflows/runs/rid_owned", headers={"x-chemml-token": READONLY}
        )
        assert resp.status_code == 404
        # The owner sees it (empty buffer -> 404 as well, but with no leakage of
        # ownership); the point is the two callers cannot be distinguished by a
        # 403-vs-404 probe.
        assert "403" not in str(resp.status_code)

    def test_ws_diagnostics_hidden_in_release(self, secured):
        client, _ = secured
        resp = client.get("/api/ws/sessions", headers={"x-chemml-token": TOKEN})
        assert resp.status_code == 404

    def test_api_docs_disabled_in_release(self, secured):
        client, _ = secured
        assert client.get("/api/docs").status_code == 404
        assert client.get("/api/openapi.json").status_code == 404


class TestAuditLog:
    """Refusals are logged, and the log never contains a credential."""

    def test_denials_are_audited_without_credentials(self, secured):
        client, audit = secured
        secret = "super-secret-token-value"
        _ws_reject(client, "/api/ws/run/rid_owned", headers={"x-chemml-token": secret})
        client.get("/api/nodes", headers={"x-chemml-token": secret})

        assert audit.exists(), "audit log was not written"
        text = audit.read_text(encoding="utf-8")
        assert secret not in text
        records = [json.loads(line) for line in text.splitlines() if line.strip()]
        assert any(r["transport"] == "websocket" and r["outcome"] == "deny" for r in records)
        assert any(r["transport"] == "http" and r["outcome"] == "deny" for r in records)
        # Reason *codes* legitimately contain the word "token" (missing_token /
        # invalid_token); what must never appear is a credential-bearing field:
        # no header bag, no query string, no "authorization" value.
        blob = json.dumps(records, ensure_ascii=False).lower()
        for forbidden in ("x-chemml-token", "authorization", "bearer ", "?token="):
            assert forbidden not in blob, f"audit record leaked {forbidden!r}"
        assert set(records[0]) == {
            "at", "transport", "method", "path", "permission", "outcome", "client", "reason",
        }

    def test_successful_http_call_is_audited(self, secured):
        client, audit = secured
        client.get("/api/nodes", headers={"x-chemml-token": TOKEN})
        records = [json.loads(l) for l in audit.read_text(encoding="utf-8").splitlines() if l.strip()]
        assert any(r["outcome"] == "allow" and r["transport"] == "http" for r in records)


class TestDeveloperMode:
    """With no token configured the API is open *and says so*."""

    def test_dev_mode_allows_connections_and_reports_it(self, monkeypatch, tmp_path):
        for var in ("CHEMML_SESSION_TOKEN", "CHEMML_READONLY_TOKEN"):
            monkeypatch.delenv(var, raising=False)
        monkeypatch.setenv("CHEMML_AUTH_MODE", "off")
        monkeypatch.setenv("CHEMML_ENV", "dev")
        monkeypatch.setenv("CHEMML_AUDIT_LOG", str(tmp_path / "audit.jsonl"))

        from backend.app import create_app

        client = TestClient(create_app())
        status = client.get("/api/security/status").json()
        assert status["auth_enforced"] is False
        assert status["environment"] == "dev"
        assert "developer mode" in status["note"]

    def test_release_without_token_fails_closed(self, monkeypatch, tmp_path):
        for var in ("CHEMML_SESSION_TOKEN", "CHEMML_READONLY_TOKEN"):
            monkeypatch.delenv(var, raising=False)
        monkeypatch.setenv("CHEMML_AUTH_MODE", "off")
        monkeypatch.setenv("CHEMML_ENV", "release")
        monkeypatch.setenv("CHEMML_AUDIT_LOG", str(tmp_path / "audit.jsonl"))

        from backend.app import create_app

        client = TestClient(create_app())
        assert client.get("/api/nodes").status_code == 401


class TestConnectionManager:
    """Broadcast / disconnect bookkeeping with a stub socket."""

    def test_broadcast_drops_dead_sockets(self):
        from backend.routers.ws import ConnectionManager

        class FakeSocket:
            def __init__(self, fail=False):
                self.sent = []
                self.fail = fail

            async def send_json(self, payload):
                if self.fail:
                    raise RuntimeError("client vanished")
                self.sent.append(payload)

        mgr = ConnectionManager()

        async def run():
            alive, dead = FakeSocket(), FakeSocket(fail=True)
            mgr.active["r"] = [alive, dead]
            await mgr.broadcast("r", {"type": "node_started"})
            return alive, dead

        import anyio

        alive, _ = anyio.run(run)
        assert alive.sent == [{"type": "node_started"}]
        # The dead socket is dropped, the alive one stays.
        assert len(mgr.active.get("r", [])) == 1


class TestRunRegistry:
    """Unit coverage for the ownership rules."""

    def test_dev_principal_may_watch_anything(self):
        assert run_registry.RunRegistry().may_subscribe("any", "dev") == (True, "ok")

    def test_owner_matches(self):
        reg = run_registry.RunRegistry()
        reg.register("r1", "full")
        assert reg.may_subscribe("r1", "full")[0] is True
        assert reg.may_subscribe("r1", "readonly") == (False, "run_not_owned")

    def test_unknown_run_is_refused(self):
        reg = run_registry.RunRegistry()
        assert reg.may_subscribe("ghost", "full") == (False, "unknown_run")

    def test_forget_clears_ownership(self):
        reg = run_registry.RunRegistry()
        reg.register("r1", "full")
        reg.forget("r1")
        assert reg.owner("r1") is None

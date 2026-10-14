"""v0.7.1 security tests -- local API auth, permissions, CORS allowlist (task D).

Covers the new ``backend/security.py`` boundary:
  * route -> permission classification;
  * token / read-only-token authorisation semantics (a read-only token can never
    reach a write, execute or external route);
  * config loading from the environment (wildcard origins are stripped);
  * the :class:`AuthMiddleware` end to end through the real FastAPI app.
"""

from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient

from backend.security import (
    ALL_PERMISSIONS,
    EXECUTE,
    EXTERNAL,
    READ,
    WRITE,
    AuthMiddleware,
    SecurityConfig,
    classify_route,
    generate_token,
    load_security_config,
)


# --------------------------------------------------------------- routing ---- #
class TestRouteClassification:
    def test_health_and_status_are_public(self):
        assert classify_route("GET", "/api/health").permission is None
        assert classify_route("GET", "/api/security/status").permission is None

    def test_simulation_run_requires_external(self):
        assert classify_route("POST", "/api/simulations/run").permission == EXTERNAL

    def test_agent_execution_requires_execute(self):
        assert classify_route("POST", "/api/agent/ask").permission == EXECUTE
        assert classify_route("POST", "/api/agent/tasks/task_00001/approve").permission == EXECUTE

    def test_workflow_run_requires_execute(self):
        assert classify_route("POST", "/api/workflows/wf_1/run").permission == EXECUTE

    def test_upload_requires_write(self):
        assert classify_route("POST", "/api/storage/upload/raw_data").permission == WRITE
        assert classify_route("DELETE", "/api/storage/file/raw_data/x.csv").permission == WRITE

    def test_default_read(self):
        assert classify_route("GET", "/api/nodes").permission == READ


# -------------------------------------------------------- authorisation ---- #
class TestAuthorisation:
    def _config(self):
        return SecurityConfig(
            mode="token",
            token="FULL",
            readonly_token="RO",
            granted=set(ALL_PERMISSIONS),
            readonly_granted={READ},
        )

    def test_enforced_when_token_present(self):
        assert self._config().enforced is True
        assert SecurityConfig(mode="off", token="").enforced is False

    def test_full_token_holds_every_permission(self):
        cfg = self._config()
        for permission in (READ, WRITE, EXECUTE, EXTERNAL):
            assert cfg.authorizes("FULL", permission) is True

    def test_readonly_token_is_read_only(self):
        cfg = self._config()
        assert cfg.authorizes("RO", READ) is True
        for permission in (WRITE, EXECUTE, EXTERNAL):
            assert cfg.authorizes("RO", permission) is False

    def test_wrong_or_missing_token_denied(self):
        cfg = self._config()
        assert cfg.authorizes("", READ) is False
        assert cfg.authorizes("nope", READ) is False

    def test_disabled_config_allows_everything(self):
        cfg = SecurityConfig(mode="off", token="")
        assert cfg.authorizes("", EXTERNAL) is True

    def test_status_never_leaks_the_token(self):
        blob = repr(self._config().status())
        assert "FULL" not in blob and "RO" not in blob


class TestConfigLoading:
    def test_token_from_environment(self):
        cfg = load_security_config({"CHEMML_SESSION_TOKEN": "abc123", "CHEMML_READONLY_TOKEN": "ro"})
        assert cfg.mode == "token" and cfg.token == "abc123" and cfg.readonly_token == "ro"

    def test_wildcard_origin_is_stripped(self):
        cfg = load_security_config(
            {"CHEMML_SESSION_TOKEN": "t", "CHEMML_ALLOWED_ORIGINS": "*,http://127.0.0.1:8000"}
        )
        assert "*" not in cfg.allowed_origins
        assert "http://127.0.0.1:8000" in cfg.allowed_origins

    def test_no_token_means_off(self):
        cfg = load_security_config({})
        assert cfg.mode == "off" and cfg.enforced is False

    def test_generate_token_is_random_and_long(self):
        a, b = generate_token(), generate_token()
        assert a != b and len(a) >= 32


# ---------------------------------------------------- middleware (e2e) ---- #
@pytest.fixture()
def secured_client(monkeypatch):
    """Real app with token auth enforced."""
    monkeypatch.setenv("CHEMML_SESSION_TOKEN", "full-token")
    monkeypatch.setenv("CHEMML_READONLY_TOKEN", "ro-token")
    monkeypatch.setenv("CHEMML_ALLOWED_ORIGINS", "http://127.0.0.1:8000")
    from backend.app import create_app

    return TestClient(create_app())


class TestAuthMiddleware:
    def test_health_open_without_token(self, secured_client):
        assert secured_client.get("/api/health").status_code == 200

    def test_read_route_requires_token(self, secured_client):
        assert secured_client.get("/api/storage/limits").status_code == 401

    def test_read_route_allowed_with_token(self, secured_client):
        resp = secured_client.get(
            "/api/storage/limits", headers={"X-ChemML-Token": "full-token"}
        )
        assert resp.status_code == 200

    def test_readonly_token_reaches_read_route(self, secured_client):
        resp = secured_client.get(
            "/api/storage/limits", headers={"Authorization": "Bearer ro-token"}
        )
        assert resp.status_code == 200

    def test_readonly_token_cannot_upload(self, secured_client):
        resp = secured_client.post(
            "/api/storage/upload/raw_data",
            files={"file": ("x.csv", io.BytesIO(b"a,b"), "text/csv")},
            headers={"Authorization": "Bearer ro-token"},
        )
        assert resp.status_code == 401
        assert resp.json()["code"] == "API_AUTH_ERROR"

    def test_full_token_can_upload(self, secured_client):
        resp = secured_client.post(
            "/api/storage/upload/raw_data",
            files={"file": ("x.csv", io.BytesIO(b"a,b"), "text/csv")},
            headers={"X-ChemML-Token": "full-token"},
        )
        assert resp.status_code == 200

    def test_query_token_accepted(self, secured_client):
        resp = secured_client.get("/api/storage/limits?token=full-token")
        assert resp.status_code == 200

    def test_cors_allowlist_is_not_wildcard(self, secured_client):
        assert "*" not in secured_client.app.state.security.allowed_origins

    def test_audit_record_written(self, secured_client, tmp_path, monkeypatch):
        # point the audit log at a temp file, fire one denied request
        import json

        from backend.security import SecurityConfig

        cfg: SecurityConfig = secured_client.app.state.security
        audit = tmp_path / "audit.jsonl"
        monkeypatch.setattr(cfg, "audit_path", audit)
        secured_client.get("/api/storage/limits")
        lines = [ln for ln in audit.read_text(encoding="utf-8").splitlines() if ln.strip()]
        assert lines, "expected at least one audit line"
        record = json.loads(lines[-1])
        assert record["outcome"] == "deny"
        assert record["permission"] == READ

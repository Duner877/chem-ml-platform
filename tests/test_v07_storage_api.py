"""v0.7 Phase C tests -- storage REST API (spec sections 8, 22-C)."""

from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient

from backend.app import create_app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """App instance whose workspace points into a temp directory."""
    import backend.routers.storage as storage_router

    from storage import StorageLimits, WorkspaceService

    monkeypatch.setattr(
        storage_router, "workspace",
        WorkspaceService(tmp_path / "ws", StorageLimits()),
    )
    return TestClient(create_app())


class TestUpload:
    def test_upload_and_list(self, client):
        resp = client.post(
            "/api/storage/upload/raw_data",
            files={"file": ("sample.csv", io.BytesIO(b"a,b\n1,2\n"), "text/csv")},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        # path is relative to the category root (no double nesting)
        assert body["path"] == "sample.csv"
        assert body["category"] == "raw_data"
        assert body["sha256"]
        assert body["format"]["format_class"] == "Universal Format"

        listing = client.get("/api/storage/list/raw_data").json()
        assert isinstance(listing, list)
        assert any(e["name"] == "sample.csv" for e in listing)

    def test_upload_rejects_bad_category(self, client):
        resp = client.post(
            "/api/storage/upload/runs",
            files={"file": ("x.csv", io.BytesIO(b"x"), "text/csv")},
        )
        assert resp.status_code == 400

    def test_upload_sanitises_traversal(self, client):
        resp = client.post(
            "/api/storage/upload/raw_data",
            files={"file": ("../evil.csv", io.BytesIO(b"x"), "text/csv")},
        )
        assert resp.status_code == 200
        assert ".." not in resp.json()["path"]

    def test_vendor_format_flagged(self, client):
        resp = client.post(
            "/api/storage/upload/raw_data",
            files={"file": ("run.raw", io.BytesIO(b"x"), "application/octet-stream")},
        )
        body = resp.json()
        assert body["format"]["format_class"] == "Vendor Native Format"
        assert body["format"]["vendor_warning"] is True


class TestSecurity:
    def test_list_escape_rejected(self, client):
        resp = client.get("/api/storage/list/raw_data/..%2F..%2Fetc")
        assert resp.status_code == 403

    def test_download_still_locked_to_artifacts(self, client):
        resp = client.get("/api/runs/artifacts/../backend/app.py")
        assert resp.status_code in {403, 404}

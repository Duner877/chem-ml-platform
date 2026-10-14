"""v0.7.1 streaming-upload tests (task C / spec §P1-01, P1-09).

The upload path must never buffer a whole file before enforcing its budget:
data is written in chunks to a ``*.part`` temp file and aborted the moment it
crosses the byte limit, leaving no half-written file behind.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from storage import StorageLimits, WorkspaceService
from storage.service import UploadLimitExceeded


@pytest.fixture()
def service(tmp_path):
    return WorkspaceService(tmp_path / "ws", StorageLimits()).category("raw_data")


class TestStreamedUpload:
    def test_commit_writes_atomically(self, service):
        with service.begin_upload("", "data.csv") as session:
            session.write(b"a,b\n")
            session.write(b"1,2\n")
            stored = session.commit()
        assert Path(stored.absolute).read_bytes() == b"a,b\n1,2\n"
        assert stored.size == 8
        # no temp residue
        leftovers = [p.name for p in Path(stored.absolute).parent.glob("*.part")]
        assert leftovers == []

    def test_sha256_matches_content(self, service):
        import hashlib

        payload = b"abcdef"
        with service.begin_upload("", "x.bin") as session:
            session.write(payload)
            stored = session.commit()
        assert stored.sha256 == hashlib.sha256(payload).hexdigest()

    def test_oversize_aborts_eagerly_and_leaves_nothing(self, service):
        with pytest.raises(UploadLimitExceeded):
            with service.begin_upload("", "big.bin", max_bytes=10) as session:
                session.write(b"0123456789" * 5)  # crosses 10 bytes
        target = service.resolve("big.bin")
        assert not target.exists()
        assert list(target.parent.glob("*.part")) == []

    def test_context_manager_aborts_on_error(self, service):
        with pytest.raises(RuntimeError):
            with service.begin_upload("", "oops.bin") as session:
                session.write(b"partial")
                raise RuntimeError("boom")
        target = service.resolve("oops.bin")
        assert not target.exists()
        assert list(target.parent.glob("*.part")) == []

    def test_write_after_commit_is_refused(self, service):
        session = service.begin_upload("", "c.bin")
        session.write(b"x")
        session.commit()
        from storage.paths import SafePathError

        with pytest.raises(SafePathError):
            session.write(b"y")


@pytest.fixture()
def tiny_client(tmp_path, monkeypatch):
    """App whose upload budget is 8 bytes so the limit is easy to hit."""
    import backend.routers.storage as storage_router

    monkeypatch.setattr(
        storage_router, "workspace",
        WorkspaceService(tmp_path / "ws", StorageLimits(max_upload_bytes=8)),
    )
    from backend.app import create_app

    return TestClient(create_app())


class TestUploadApiLimits:
    def test_upload_within_limit(self, tiny_client):
        resp = tiny_client.post(
            "/api/storage/upload/raw_data",
            files={"file": ("a.csv", io.BytesIO(b"12345678"), "text/csv")},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["size"] == 8

    def test_oversize_upload_returns_413(self, tiny_client):
        resp = tiny_client.post(
            "/api/storage/upload/raw_data",
            files={"file": ("a.csv", io.BytesIO(b"0123456789ABCDEF"), "text/csv")},
        )
        assert resp.status_code == 413
        assert resp.json()["detail"]["code"] == "STORAGE_SECURITY_ERROR"

    def test_limits_endpoint_reports_policy(self, tiny_client):
        body = tiny_client.get("/api/storage/limits").json()
        assert body["max_upload_bytes"] == 8
        assert body["max_concurrent_uploads"] >= 1
        assert body["chunk_size"] > 0
        assert "raw_data" in body["uploadable_categories"]

    def test_concurrent_guard_matches_policy(self):
        import backend.routers.storage as storage_router

        storage_router._upload_semaphore = None  # reset lazy binding
        guard = storage_router._uploads_guard()
        assert guard._value == storage_router.workspace.limits.max_concurrent_uploads

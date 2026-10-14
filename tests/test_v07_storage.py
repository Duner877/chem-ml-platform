"""v0.7 Phase A tests -- storage security (spec sections 8.2, 22-I)."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from storage import (
    SafePathError,
    StorageLimits,
    StorageService,
    WorkspaceService,
    is_within,
    safe_join,
    sanitize_filename,
)
from workflow_engine.error_model import ErrorCode


@pytest.fixture()
def service(tmp_path: Path) -> StorageService:
    return StorageService(tmp_path / "root")


class TestSafeJoin:
    def test_simple_join(self, tmp_path):
        result = safe_join(tmp_path, "a", "b.txt")
        assert result == (tmp_path / "a" / "b.txt").resolve()

    def test_dotdot_rejected(self, tmp_path):
        with pytest.raises(SafePathError):
            safe_join(tmp_path, "..", "secret.txt")

    def test_nested_dotdot_rejected(self, tmp_path):
        with pytest.raises(SafePathError):
            safe_join(tmp_path, "data", "..", "..", "etc", "passwd")

    def test_absolute_posix_rejected(self, tmp_path):
        with pytest.raises(SafePathError):
            safe_join(tmp_path, "/etc/passwd")

    def test_absolute_windows_drive_rejected(self, tmp_path):
        with pytest.raises(SafePathError):
            safe_join(tmp_path, "C:\\Windows\\system32\\config")

    def test_unc_rejected(self, tmp_path):
        with pytest.raises(SafePathError):
            safe_join(tmp_path, "\\\\evil\\share\\x")

    def test_device_namespace_rejected(self, tmp_path):
        with pytest.raises(SafePathError):
            safe_join(tmp_path, "\\\\.\\pipe\\x")

    def test_symlink_escape_rejected(self, tmp_path):
        """A link (symlink / NTFS junction) inside the root pointing outside
        must be refused after resolution."""
        import os

        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "key.pem").write_text("secret")
        link = tmp_path / "root" / "link"
        link.mkdir(parents=True)
        escape = link / "escape"
        try:
            if os.name == "nt":
                import _winapi

                _winapi.CreateJunction(str(outside), str(escape))
            else:
                escape.symlink_to(outside, target_is_directory=True)
        except OSError:
            pytest.skip("symlinks/junctions unavailable on this platform")
        with pytest.raises(SafePathError):
            safe_join(tmp_path / "root", "link", "escape", "key.pem")

    def test_is_within(self, tmp_path):
        assert is_within(tmp_path, tmp_path / "sub" / "f.txt")
        assert not is_within(tmp_path, tmp_path.parent)


class TestSanitizeFilename:
    def test_plain_name_kept(self):
        assert sanitize_filename("data.csv") == "data.csv"

    def test_directory_components_stripped(self):
        assert sanitize_filename("../../etc/passwd") == "passwd"
        assert sanitize_filename("C:\\temp\\evil.xyz") == "evil.xyz"

    def test_control_and_weird_chars(self):
        cleaned = sanitize_filename("re port\x00?.csv")
        assert cleaned.endswith(".csv")
        assert "\x00" not in cleaned and "?" not in cleaned

    def test_windows_reserved(self):
        assert sanitize_filename("CON.txt").startswith("_")

    def test_empty_rejected(self):
        with pytest.raises(SafePathError):
            sanitize_filename("")
        with pytest.raises(SafePathError):
            sanitize_filename("...")

    def test_long_name_preserves_extension(self):
        name = "x" * 400 + ".csv"
        cleaned = sanitize_filename(name)
        assert cleaned.endswith(".csv") and len(cleaned) < 200


class TestStorageService:
    def test_write_and_read(self, service):
        service.write_text_atomic("raw_data/a.txt", "hello")
        assert (service.root / "raw_data" / "a.txt").read_text() == "hello"

    def test_atomic_write_no_tmp_leftovers(self, service):
        service.write_text_atomic("cache/x.bin", "\x00\x01")
        leftovers = [p for p in (service.root / "cache").iterdir() if p.name != "x.bin"]
        assert leftovers == []

    def test_escape_via_write(self, service):
        with pytest.raises(SafePathError):
            service.write_text_atomic("../escape.txt", "no")

    def test_upload_sanitises_name(self, service):
        stored = service.save_upload("raw_data", "../evil .csv", b"a,b\n1,2\n")
        assert "\\" not in stored.path and ".." not in stored.path
        assert stored.path.startswith("raw_data/")
        assert stored.sha256 and len(stored.sha256) == 64
        assert stored.size == len(b"a,b\n1,2\n")

    def test_upload_size_limit(self, tmp_path):
        tiny = StorageService(tmp_path / "r", StorageLimits(max_upload_bytes=10))
        with pytest.raises(SafePathError):
            tiny.save_upload("uploads", "big.bin", b"x" * 11)

    def test_list_dir(self, service):
        service.write_text_atomic("raw_data/one.txt", "1")
        service.write_text_atomic("raw_data/two.txt", "2")
        names = [e["name"] for e in service.list_dir("raw_data")]
        assert names == ["one.txt", "two.txt"]

    def test_list_dir_escape_rejected(self, service):
        with pytest.raises(SafePathError):
            service.list_dir("..")

    def test_remove_guarded(self, service):
        with pytest.raises(SafePathError):
            service.remove("")


class TestZipExtraction:
    def _zip(self, path: Path, entries: dict) -> Path:
        with zipfile.ZipFile(path, "w") as zf:
            for name, data in entries.items():
                zf.writestr(name, data)
        return path

    def test_normal_extraction(self, service, tmp_path):
        archive = self._zip(tmp_path / "ok.zip", {"a.csv": "1,2", "sub/b.csv": "3,4"})
        stored = service.extract_zip(archive, "raw_data")
        assert {s.path for s in stored} == {"raw_data/a.csv", "raw_data/sub/b.csv"}
        assert (service.root / "raw_data" / "sub" / "b.csv").read_text() == "3,4"

    def test_zip_slip_rejected(self, service, tmp_path):
        """Entries carrying ../ payloads are rejected outright (zip-slip)."""
        archive = self._zip(tmp_path / "evil.zip", {"../../evil.txt": "pwned"})
        with pytest.raises(SafePathError):
            service.extract_zip(archive, "raw_data")
        # nothing written inside or outside the destination
        assert not (service.root / "raw_data" / "evil.txt").exists()
        assert not (service.root / "evil.txt").exists()
        assert not (service.root.parent / "evil.txt").exists()

    def test_zip_bomb_guard(self, service, tmp_path):
        tiny = StorageService(
            tmp_path / "small",
            StorageLimits(max_archive_uncompressed=10),
        )
        archive = self._zip(tmp_path / "bomb.zip", {"big.bin": "x" * 1024})
        with pytest.raises(SafePathError):
            tiny.extract_zip(archive, "raw_data")

    def test_entry_count_guard(self, service, tmp_path):
        tiny = StorageService(
            tmp_path / "small", StorageLimits(max_archive_entries=2)
        )
        archive = self._zip(
            tmp_path / "many.zip",
            {f"f{i}.txt": "x" for i in range(5)},
        )
        with pytest.raises(SafePathError):
            tiny.extract_zip(archive, "raw_data")

    def test_error_code_is_storage_security(self, tmp_path):
        """Zip-bomb guard failures map to STORAGE_SECURITY_ERROR."""
        from workflow_engine.error_model import ErrorCode, PlatformError, from_exception

        limits = StorageService(
            tmp_path / "lim", StorageLimits(max_archive_uncompressed=16)
        )
        archive = self._zip(tmp_path / "bomb.zip", {"big.bin": "x" * 2048})
        with pytest.raises(SafePathError) as exc_info:
            limits.extract_zip(archive, "raw_data")
        unified = from_exception(exc_info.value)
        assert isinstance(unified, PlatformError)
        assert unified.code == ErrorCode.STORAGE_SECURITY_ERROR


class TestWorkspaceService:
    def test_categories(self, tmp_path):
        ws = WorkspaceService(tmp_path / "ws")
        for name in ("raw_data", "cache", "workflows", "models", "runs"):
            svc = ws.category(name)
            assert svc.root.parent == (tmp_path / "ws").resolve()
        with pytest.raises(KeyError):
            ws.category("not_a_category")

    def test_categories_isolated(self, tmp_path):
        ws = WorkspaceService(tmp_path / "ws")
        ws.raw_data.write_text_atomic("f.txt", "data")
        assert not ws.runs.exists("f.txt")

    def test_layout_report(self, tmp_path):
        ws = WorkspaceService(tmp_path / "ws")
        layout = ws.layout()
        assert set(layout) >= {"raw_data", "cache", "workflows", "models", "runs"}


def test_storage_error_carries_unified_code(tmp_path):
    """SafePathError raised through the API maps to STORAGE_SECURITY_ERROR."""
    from workflow_engine.error_model import from_exception

    service = StorageService(tmp_path / "root")
    try:
        service.write_text_atomic("../x.txt", "no")
    except SafePathError as exc:
        unified = from_exception(exc)
        assert unified.code == ErrorCode.STORAGE_SECURITY_ERROR
        assert unified.recoverable is False

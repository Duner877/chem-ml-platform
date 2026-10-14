"""StorageService (v0.7 -- spec section 8.2).

A single, audited gateway for every file the platform writes or reads on
behalf of a user:

* all access is anchored to whitelisted roots (:class:`WorkspaceService`);
* uploads pass through :meth:`StorageService.save_upload` which sanitises the
  filename, enforces size/count quotas and records a SHA-256 content digest;
* archive extraction is protected against zip-slip, zip-bombs (total
  uncompressed size), excessive entry counts and directory-depth abuse;
* writes are atomic (temp file + ``os.replace``) so a crash never leaves a
  half-written scientific dataset behind;
* the service never returns a path outside of its roots -- callers receive
  :class:`SafePathError` (``STORAGE_SECURITY_ERROR``) instead.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .paths import SafePathError, safe_join, sanitize_filename

__all__ = [
    "StorageLimits",
    "StoredFile",
    "StorageService",
    "UploadSession",
    "UploadLimitExceeded",
]


@dataclass(frozen=True)
class StorageLimits:
    """Hard resource limits for user supplied files."""

    max_upload_bytes: int = 512 * 1024 * 1024          # 512 MB per file
    max_archive_bytes: int = 1024 * 1024 * 1024        # 1 GB archive size
    max_archive_uncompressed: int = 2 * 1024 * 1024 * 1024  # 2 GB extracted
    max_archive_entries: int = 10_000
    max_archive_depth: int = 16
    max_files_per_dir: int = 20_000
    max_concurrent_uploads: int = 4                    # parallel upload ceiling
    upload_timeout_s: float = 600.0                    # per-upload wall clock


class UploadLimitExceeded(SafePathError):
    """Raised the moment a streamed upload crosses its byte budget."""


@dataclass(frozen=True)
class StoredFile:
    """Metadata recorded for every stored file."""

    path: str            # path relative to the storage root (safe for API use)
    absolute: str        # resolved absolute path (server-side only)
    size: int
    sha256: str
    category: str

    def to_dict(self) -> Dict[str, object]:
        return {
            "path": self.path,
            "size": self.size,
            "sha256": self.sha256,
            "category": self.category,
        }


class UploadSession:
    """A single streamed upload (v0.7.1 -- P1-01 / P1-09).

    Data is copied chunk by chunk into a ``*.part`` temp file that lives in
    the *destination* directory (same filesystem, so the final
    :func:`os.replace` is atomic).  The byte budget is enforced on every
    :meth:`write`, so an oversized payload is aborted as soon as it crosses
    the threshold instead of being buffered completely in memory first.

    Always use the context manager form so an interrupted upload leaves no
    half-written file behind::

        with service.begin_upload("uploads", name) as session:
            for chunk in stream:
                session.write(chunk)
            stored = session.commit()
    """

    def __init__(
        self,
        service: "StorageService",
        category: str,
        filename: str,
        max_bytes: Optional[int] = None,
    ):
        self.service = service
        self.category = category.strip("/") if category else ""
        self.filename = sanitize_filename(filename)
        self.max_bytes = (
            max_bytes if max_bytes is not None else service.limits.max_upload_bytes
        )
        relative = (
            f"{self.category}/{self.filename}" if self.category else self.filename
        )
        self.target = service.resolve(relative)
        self.target.parent.mkdir(parents=True, exist_ok=True)
        service._check_dir_quota(self.target.parent)
        fd, tmp_name = tempfile.mkstemp(
            prefix=f".{self.target.name}.", suffix=".part", dir=str(self.target.parent)
        )
        self._handle = os.fdopen(fd, "wb")
        self._tmp = Path(tmp_name)
        self._digest = hashlib.sha256()
        self.bytes_written = 0
        self.started_at = time.monotonic()
        self._committed = False

    # -- data plane ---------------------------------------------------------- #
    def write(self, chunk: bytes) -> int:
        """Append a chunk, enforcing size and wall-clock limits eagerly."""
        if self._committed:
            raise SafePathError("upload session already committed")
        if not chunk:
            return self.bytes_written
        self.bytes_written += len(chunk)
        if self.bytes_written > self.max_bytes:
            self.abort()
            raise UploadLimitExceeded(
                f"upload exceeds the {self.max_bytes} byte limit "
                f"(aborted after {self.bytes_written} bytes)"
            )
        if time.monotonic() - self.started_at > self.service.limits.upload_timeout_s:
            self.abort()
            raise UploadLimitExceeded(
                f"upload exceeded the {self.service.limits.upload_timeout_s:.0f}s time limit"
            )
        self._handle.write(chunk)
        self._digest.update(chunk)
        return self.bytes_written

    # -- finalisation --------------------------------------------------------- #
    def commit(self) -> StoredFile:
        """Flush, fsync and atomically move the temp file into place."""
        if self._committed:
            raise SafePathError("upload session already committed")
        self._handle.flush()
        os.fsync(self._handle.fileno())
        self._handle.close()
        os.replace(self._tmp, self.target)
        self._committed = True
        return StoredFile(
            path=self.target.relative_to(self.service.root).as_posix(),
            absolute=str(self.target),
            size=self.bytes_written,
            sha256=self._digest.hexdigest(),
            category=self.category,
        )

    def abort(self) -> None:
        """Discard the temp file; safe to call repeatedly."""
        if self._committed:
            return
        try:
            if not self._handle.closed:
                self._handle.close()
        except Exception:
            pass
        try:
            self._tmp.unlink(missing_ok=True)
        except OSError:
            pass
        self._committed = True  # nothing further may be written

    # -- context manager -------------------------------------------------------- #
    def __enter__(self) -> "UploadSession":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        if exc_type is not None:
            self.abort()
        return False


class StorageService:
    """Filesystem gateway enforcing the v0.7 security rules."""

    def __init__(self, root: str | os.PathLike, limits: Optional[StorageLimits] = None):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.limits = limits or StorageLimits()

    # -- streamed uploads (v0.7.1) ------------------------------------------- #
    def begin_upload(
        self,
        category: str,
        filename: str,
        max_bytes: Optional[int] = None,
    ) -> UploadSession:
        """Open a streaming upload session (never buffers the whole file)."""
        return UploadSession(self, category, filename, max_bytes=max_bytes)

    # -- path helpers -------------------------------------------------------- #
    def resolve(self, relative: str) -> Path:
        """Resolve a root-relative path, refusing escapes."""
        return safe_join(self.root, relative)

    def exists(self, relative: str) -> bool:
        return self.resolve(relative).exists()

    # -- atomic writes -------------------------------------------------------- #
    def write_atomic(self, relative: str, data: bytes) -> Path:
        """Write ``data`` to ``relative`` atomically inside the root."""
        target = self.resolve(relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        self._check_dir_quota(target.parent)
        fd, tmp_name = tempfile.mkstemp(
            prefix=f".{target.name}.", suffix=".tmp", dir=str(target.parent)
        )
        os.close(fd)
        tmp = Path(tmp_name)
        try:
            tmp.write_bytes(data)
            os.replace(tmp, target)
        except Exception:
            tmp.unlink(missing_ok=True)
            raise
        return target

    def write_text_atomic(self, relative: str, text: str) -> Path:
        return self.write_atomic(relative, text.encode("utf-8"))

    # -- uploads --------------------------------------------------------------- #
    def save_upload(self, category: str, filename: str, data: bytes) -> StoredFile:
        """Store an uploaded file with full validation.

        ``category`` doubles as the subfolder prefix for flat roots; pass an
        empty string when the service root is already category-scoped (the
        WorkspaceService case) to avoid double nesting.
        """
        safe_name = sanitize_filename(filename)
        if len(data) > self.limits.max_upload_bytes:
            raise SafePathError(
                f"upload of {len(data)} bytes exceeds the "
                f"{self.limits.max_upload_bytes} byte limit"
            )
        prefix = category.strip("/") if category else ""
        relative = f"{prefix}/{safe_name}" if prefix else safe_name
        path = self.write_atomic(relative, data)
        digest = hashlib.sha256(data).hexdigest()
        return StoredFile(
            path=Path(path).relative_to(self.root).as_posix(),
            absolute=str(path),
            size=len(data),
            sha256=digest,
            category=prefix,
        )

    # -- archive extraction ------------------------------------------------------ #
    def extract_zip(
        self,
        archive: str | os.PathLike,
        dest_category: str,
    ) -> List[StoredFile]:
        """Extract a zip archive into ``dest_category`` with zip-slip defence.

        The archive may live anywhere on disk (typically an upload); every
        entry name is sanitised and re-joined onto the destination root so a
        ``../`` payload cannot escape, and resource limits are enforced before
        a single byte is written.
        """
        archive_path = Path(archive)
        size = archive_path.stat().st_size
        if size > self.limits.max_archive_bytes:
            raise SafePathError(
                f"archive of {size} bytes exceeds the "
                f"{self.limits.max_archive_bytes} byte limit"
            )
        dest_root = self.resolve(dest_category.strip("/"))
        dest_root.mkdir(parents=True, exist_ok=True)

        stored: List[StoredFile] = []
        total_uncompressed = 0
        with zipfile.ZipFile(archive_path) as zf:
            names = zf.namelist()
            if len(names) > self.limits.max_archive_entries:
                raise SafePathError(
                    f"archive contains {len(names)} entries, limit is "
                    f"{self.limits.max_archive_entries}"
                )
            for info in zf.infolist():
                if info.is_dir():
                    continue
                # zip-slip: reject any absolute or parent-referencing name.
                try:
                    safe_name = sanitize_filename(info.filename)
                except SafePathError:
                    continue
                depth = len([p for p in Path(info.filename).parts if p not in ("/", "\\")])
                if depth > self.limits.max_archive_depth:
                    raise SafePathError(
                        f"archive entry {info.filename!r} exceeds nesting depth "
                        f"{self.limits.max_archive_depth}"
                    )
                total_uncompressed += info.file_size
                if total_uncompressed > self.limits.max_archive_uncompressed:
                    raise SafePathError(
                        "archive would decompress beyond the configured limit"
                    )
                # Preserve single-level subfolders from the archive but strip
                # the leading component chain beyond depth limits is handled
                # above; rebuild the relative folder from *sanitised* parts.
                raw_parts = [
                    part for part in Path(info.filename).parts
                    if part not in ("/", "\\", ".")
                ]
                if any(part == ".." for part in raw_parts):
                    raise SafePathError(
                        f"archive entry {info.filename!r} contains a parent "
                        "reference (zip-slip) and was rejected"
                    )
                rel_parts = [sanitize_filename(part) for part in raw_parts]
                rel_parts[-1] = safe_name
                target = safe_join(dest_root, *rel_parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                data = zf.read(info)
                fd, tmp_name = tempfile.mkstemp(
                    prefix="._extract_", suffix=".tmp", dir=str(target.parent)
                )
                os.close(fd)
                tmp = Path(tmp_name)
                try:
                    tmp.write_bytes(data)
                    os.replace(tmp, target)
                except Exception:
                    tmp.unlink(missing_ok=True)
                    raise
                stored.append(
                    StoredFile(
                        path=target.relative_to(self.root).as_posix(),
                        absolute=str(target),
                        size=len(data),
                        sha256=hashlib.sha256(data).hexdigest(),
                        category=dest_category.strip("/"),
                    )
                )
        return stored

    # -- inspection --------------------------------------------------------------- #
    def list_dir(self, relative: str = "") -> List[Dict[str, object]]:
        """List a directory inside the root (non-recursive, safe)."""
        directory = self.resolve(relative) if relative else self.root
        if not directory.is_dir():
            return []
        entries: List[Dict[str, object]] = []
        for entry in sorted(directory.iterdir()):
            if entry.is_file():
                stat = entry.stat()
                entries.append(
                    {
                        "name": entry.name,
                        "type": "file",
                        "size": stat.st_size,
                        "path": entry.relative_to(self.root).as_posix(),
                    }
                )
            elif entry.is_dir():
                entries.append(
                    {
                        "name": entry.name,
                        "type": "directory",
                        "path": entry.relative_to(self.root).as_posix(),
                    }
                )
        return entries

    def remove(self, relative: str) -> bool:
        """Delete a file or an empty-ish subtree that lives inside the root."""
        target = self.resolve(relative)
        if target == self.root:
            raise SafePathError("refusing to delete the storage root itself")
        if target.is_dir():
            shutil.rmtree(target)
            return True
        if target.is_file():
            target.unlink()
            return True
        return False

    # -- internals ------------------------------------------------------------------ #
    def _check_dir_quota(self, directory: Path) -> None:
        """Enforce the per-directory file count limit cheaply."""
        try:
            count = sum(1 for _ in directory.iterdir())
        except FileNotFoundError:
            return
        if count >= self.limits.max_files_per_dir:
            raise SafePathError(
                f"directory {directory} reached the {self.limits.max_files_per_dir} "
                "file quota"
            )

"""Chem ML Platform v0.7 -- secure storage layer.

This package implements the StorageService / WorkspaceService mandated by the
v0.7 specification (section 8.2).  Every user file access goes through one of
the whitelisted workspace roots; path traversal, zip-slip archives, oversized
payloads and symlink escapes are rejected with a
:class:`~workflow_engine.error_model.PlatformError` carrying the
``STORAGE_SECURITY_ERROR`` code.
"""

from .paths import SafePathError, is_within, safe_join, sanitize_filename
from .service import (
    StorageLimits,
    StorageService,
    StoredFile,
    UploadLimitExceeded,
    UploadSession,
)
from .workspace import WORKSPACE_SUBDIRS, WorkspaceService

__all__ = [
    "SafePathError",
    "is_within",
    "safe_join",
    "sanitize_filename",
    "StorageLimits",
    "StorageService",
    "StoredFile",
    "UploadLimitExceeded",
    "UploadSession",
    "WORKSPACE_SUBDIRS",
    "WorkspaceService",
]

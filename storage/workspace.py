"""WorkspaceService (v0.7 -- spec section 8.2).

Splits one storage root into the canonical categories required by the spec --
raw data, cache, workflows, models and run artefacts -- and hands out a
:class:`StorageService` per category so that callers can never reach across
boundaries (e.g. a report cannot read another user's uploads by guessing
paths).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, Optional

from .service import StorageLimits, StorageService

__all__ = ["WORKSPACE_SUBDIRS", "WorkspaceService"]

#: Canonical workspace layout (spec section 8.2: "区分原始数据、缓存、
#: 工作流、模型和运行产物").
WORKSPACE_SUBDIRS = {
    "raw_data": "raw_data",      # user uploaded / imported source data
    "cache": "cache",            # node result cache, safe to delete
    "workflows": "workflows",    # saved workflow JSON documents
    "models": "models",          # model weights and checkpoints
    "runs": "runs",              # run artefacts and provenance
    "uploads": "uploads",        # transient upload landing zone
    "reports": "reports",        # exported report documents
    "records": "records",        # experiment records & dataset catalog
}


class WorkspaceService:
    """Manages the whitelisted workspace roots of a Chem ML installation."""

    def __init__(
        self,
        base: str | os.PathLike,
        limits: Optional[StorageLimits] = None,
    ):
        self.base = Path(base).resolve()
        self.base.mkdir(parents=True, exist_ok=True)
        self.limits = limits
        self._services: Dict[str, StorageService] = {}

    # -- categories ------------------------------------------------------------ #
    def category(self, name: str) -> StorageService:
        """Return the :class:`StorageService` for a canonical category."""
        if name not in WORKSPACE_SUBDIRS:
            raise KeyError(
                f"unknown workspace category {name!r}; "
                f"valid: {sorted(WORKSPACE_SUBDIRS)}"
            )
        if name not in self._services:
            service = StorageService(self.base / WORKSPACE_SUBDIRS[name], self.limits)
            self._services[name] = service
        return self._services[name]

    @property
    def raw_data(self) -> StorageService:
        return self.category("raw_data")

    @property
    def cache(self) -> StorageService:
        return self.category("cache")

    @property
    def runs(self) -> StorageService:
        return self.category("runs")

    @property
    def uploads(self) -> StorageService:
        return self.category("uploads")

    @property
    def reports(self) -> StorageService:
        return self.category("reports")

    # -- diagnostics -------------------------------------------------------------- #
    def layout(self) -> Dict[str, str]:
        """Return the workspace layout for the diagnostics page."""
        return {name: str(self.base / sub) for name, sub in WORKSPACE_SUBDIRS.items()}

    def total_disk_usage(self) -> int:
        """Sum of file sizes across the workspace (best effort)."""
        total = 0
        for _, service in self._services.items():
            for path in service.root.rglob("*"):
                try:
                    if path.is_file():
                        total += path.stat().st_size
                except OSError:
                    continue
        return total

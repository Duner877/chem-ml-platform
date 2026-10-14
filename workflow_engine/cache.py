"""Result cache for workflow nodes.

The cache key is a SHA-1 hash built from the node type, its (normalised)
parameters and a hash of every input object.  Results are stored as JSON so
they survive a process restart, which keeps iterative scientific work fast.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

from .objects import serialize_object
from .utils import ensure_dir, stable_hash

__all__ = ["ResultCache", "compute_cache_key"]


def compute_cache_key(
    node_type: str, params: Dict[str, Any], inputs: Dict[str, Any]
) -> str:
    """Build a deterministic cache key for a node invocation."""
    return stable_hash(
        {
            "node_type": node_type,
            "params": params,
            "inputs": serialize_object(inputs),
        }
    )


class ResultCache:
    """Tiny file based JSON cache."""

    def __init__(self, directory: str | Path, enabled: bool = True) -> None:
        self.directory = ensure_dir(directory)
        self.enabled = enabled
        self._memory: Dict[str, Any] = {}

    # -- api ---------------------------------------------------------------- #
    def get(self, key: str) -> Optional[Dict[str, Any]]:
        if not self.enabled:
            return None
        if key in self._memory:
            return self._memory[key]
        path = self.directory / f"{key}.json"
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
        self._memory[key] = data
        return data

    def put(self, key: str, payload: Any) -> None:
        if not self.enabled:
            return
        self._memory[key] = payload
        path = self.directory / f"{key}.json"
        try:
            path.write_text(
                json.dumps(serialize_object(payload), ensure_ascii=False),
                encoding="utf-8",
            )
        except (TypeError, OSError):  # pragma: no cover - non serialisable payload
            pass

    def invalidate(self, key: str) -> None:
        self._memory.pop(key, None)
        path = self.directory / f"{key}.json"
        if path.exists():
            try:
                path.unlink()
            except OSError:  # pragma: no cover
                pass

    def clear(self) -> None:
        self._memory.clear()
        for path in self.directory.glob("*.json"):
            try:
                path.unlink()
            except OSError:  # pragma: no cover
                pass

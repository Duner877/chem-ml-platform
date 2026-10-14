"""Agent memory.

The agent is a *scientific workflow controller*, not a chatbot: what it has to
remember is experiments, not small talk.  Four memory layers are supported,
exactly as the specification requires:

===========================  ================================================
``experiment``               the run currently in flight
``workflows``                previously generated / executed workflows
``preferences``              user preferences (language, units, verbosity)
``knowledge``                reusable scientific knowledge (findings, notes)
===========================  ================================================

The store is a plain JSON document on disk (``memory/memory.json`` by default,
overridable with ``CHEMML_MEMORY``), so a memory survives restarts and can be
inspected with any text editor.  Writes are atomic: the document is rewritten
through a temporary file and renamed.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from workflow_engine.utils import new_id, now_iso

__all__ = ["MemoryStore", "memory", "get_memory"]

#: Default location of the memory document.
DEFAULT_PATH = Path(__file__).resolve().parents[1] / "memory" / "memory.json"


class MemoryStore:
    """Persistent, JSON backed agent memory."""

    def __init__(self, path: Optional[str | Path] = None) -> None:
        self.path = Path(path) if path else self._default_path()
        self._data: Dict[str, Any] = {
            "experiment": {},
            "workflows": [],
            "preferences": {},
            "knowledge": [],
        }
        self.load()

    # -- location ----------------------------------------------------------- #
    @staticmethod
    def _default_path() -> Path:
        env = os.environ.get("CHEMML_MEMORY")
        if env:
            return Path(env)
        return DEFAULT_PATH

    # -- persistence -------------------------------------------------------- #
    def load(self) -> None:
        """Read the memory document (missing or broken file -> fresh memory)."""
        if not self.path.exists():
            return
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return
        if isinstance(payload, dict):
            self._data["experiment"] = dict(payload.get("experiment") or {})
            self._data["workflows"] = list(payload.get("workflows") or [])
            self._data["preferences"] = dict(payload.get("preferences") or {})
            self._data["knowledge"] = list(payload.get("knowledge") or [])

    def save(self) -> Path:
        """Atomically write the memory document and return its path."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=str(self.path.parent), delete=False, suffix=".tmp"
        )
        try:
            json.dump(self._data, handle, ensure_ascii=False, indent=2, default=str)
            handle.flush()
            os.fsync(handle.fileno())
        finally:
            handle.close()
        os.replace(handle.name, self.path)
        return self.path

    # -- experiment (current run) ------------------------------------------- #
    def start_experiment(self, question: str, **context: Any) -> Dict[str, Any]:
        """Begin a new experiment; the previous one is archived as knowledge."""
        previous = self._data["experiment"]
        if previous:
            self.remember(
                f"experiment:{previous.get('question', '')[:80]}",
                previous,
                tags=["experiment", "archived"],
            )
        self._data["experiment"] = {
            "id": new_id("exp_"),
            "question": question,
            "started_at": now_iso(),
            "context": context,
            "steps": [],
            "findings": [],
        }
        return dict(self._data["experiment"])

    def experiment(self) -> Dict[str, Any]:
        """The experiment currently in flight (``{}`` when idle)."""
        return dict(self._data["experiment"])

    def record_step(self, step: str, **payload: Any) -> None:
        """Append a step to the running experiment."""
        entry = {"at": now_iso(), "step": step}
        entry.update(payload)
        self._data["experiment"].setdefault("steps", []).append(entry)

    def record_finding(self, text: str, confidence: float = 0.0, **payload: Any) -> None:
        """Record a conclusion of the running experiment."""
        entry = {"at": now_iso(), "text": text, "confidence": float(confidence)}
        entry.update(payload)
        self._data["experiment"].setdefault("findings", []).append(entry)

    def end_experiment(self, status: str = "completed") -> Dict[str, Any]:
        """Close the running experiment and archive it under ``workflows``."""
        experiment = self._data["experiment"]
        if not experiment:
            return {}
        experiment["finished_at"] = now_iso()
        experiment["status"] = status
        self._data["workflows"].append(experiment)
        # keep the history bounded but useful
        del self._data["workflows"][:-50]
        self._data["experiment"] = {}
        return dict(experiment)

    # -- workflows (history) ------------------------------------------------- #
    def remember_workflow(self, workflow: Dict[str, Any], result: Optional[Dict[str, Any]] = None) -> str:
        """Archive a generated workflow plus its outcome."""
        entry = {
            "id": new_id("wf_"),
            "at": now_iso(),
            "workflow": workflow,
            "result": {
                "status": (result or {}).get("status", ""),
                "nodes": len((result or {}).get("records", {})),
                "duration_ms": (result or {}).get("duration_ms", 0),
            },
        }
        self._data["workflows"].append(entry)
        del self._data["workflows"][:-50]
        return entry["id"]

    def workflows(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Most recently remembered workflows."""
        return list(reversed(self._data["workflows"]))[: max(0, int(limit))]

    # -- preferences --------------------------------------------------------- #
    def set_preference(self, key: str, value: Any) -> None:
        self._data["preferences"][str(key)] = value

    def preference(self, key: str, default: Any = None) -> Any:
        return self._data["preferences"].get(str(key), default)

    def preferences(self) -> Dict[str, Any]:
        return dict(self._data["preferences"])

    # -- knowledge ----------------------------------------------------------- #
    def remember(self, text: str, payload: Any = None, tags: Optional[List[str]] = None) -> str:
        """Store a reusable piece of scientific knowledge."""
        entry = {
            "id": new_id("k_"),
            "at": now_iso(),
            "text": text,
            "tags": list(tags or []),
            "payload": payload,
        }
        self._data["knowledge"].append(entry)
        del self._data["knowledge"][:-200]
        return entry["id"]

    def recall(self, query: str = "", limit: int = 10) -> List[Dict[str, Any]]:
        """Keyword search over the knowledge base."""
        needle = (query or "").strip().lower()
        items = list(reversed(self._data["knowledge"]))
        if needle:
            items = [
                item
                for item in items
                if needle in str(item.get("text", "")).lower()
                or any(needle in str(tag).lower() for tag in item.get("tags", []))
            ]
        return items[: max(0, int(limit))]

    def knowledge(self) -> List[Dict[str, Any]]:
        return list(self._data["knowledge"])

    # -- housekeeping -------------------------------------------------------- #
    def clear(self, layer: str = "") -> None:
        """Empty one layer (or everything when ``layer`` is empty)."""
        if not layer:
            self._data = {"experiment": {}, "workflows": [], "preferences": {}, "knowledge": []}
            return
        if layer in self._data:
            self._data[layer] = {} if layer in {"experiment", "preferences"} else []

    def stats(self) -> Dict[str, Any]:
        return {
            "path": str(self.path),
            "workflows": len(self._data["workflows"]),
            "knowledge": len(self._data["knowledge"]),
            "preferences": len(self._data["preferences"]),
            "experiment_active": bool(self._data["experiment"]),
        }

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<MemoryStore {self.path} workflows={len(self._data['workflows'])}>"


#: Process wide store, lazily created so importing the package is cheap.
_store: Optional[MemoryStore] = None


def get_memory() -> MemoryStore:
    """The process wide :class:`MemoryStore`."""
    global _store
    if _store is None:
        _store = MemoryStore()
    return _store


def memory() -> MemoryStore:
    """Alias of :func:`get_memory`."""
    return get_memory()

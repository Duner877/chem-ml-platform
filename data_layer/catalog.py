"""Scientific data catalog.

The :mod:`data_layer` turns raw files (and database rows) into universal
:class:`~data_layer.objects.ScientificDataObject` envelopes.  The catalog keeps
those envelopes together in one place so they can be searched, listed and fed
to the foundation models later::

    from data_layer import catalog

    catalog.ingest("datasets/demo/caffeine_ms.xy", tags=["demo", "ms"])
    hits = catalog.search("caffeine")
    stats = catalog.stats()

Each entry is a JSON safe record: identity, provenance, a data pointer, free
form tags and -- when the payload can be embedded -- a foundation model vector
so spectra and molecules can be compared without re-reading the source file.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from workflow_engine.utils import new_id, now_iso

from data_layer.objects import ScientificDataObject

__all__ = ["DataCatalog", "catalog", "get_catalog", "CATALOG_PATH"]

ROOT = Path(__file__).resolve().parents[1]

#: Default location of the catalog document.
CATALOG_PATH = ROOT / "output" / "catalog" / "catalog.json"


def _default_path() -> Path:
    override = (os.environ.get("CHEMML_CATALOG") or "").strip()
    return Path(override) if override else CATALOG_PATH


class DataCatalog:
    """A persistent, searchable index of scientific data objects."""

    def __init__(self, path: Optional[str | Path] = None) -> None:
        self.path = Path(path) if path else _default_path()
        self._entries: List[Dict[str, Any]] = []
        self.load()

    # -- persistence -------------------------------------------------------- #
    def load(self) -> None:
        """Read the catalog document (missing / broken file -> empty)."""
        if not self.path.exists():
            return
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return
        entries = payload.get("entries") if isinstance(payload, dict) else payload
        if isinstance(entries, list):
            self._entries = [entry for entry in entries if isinstance(entry, dict)]

    def save(self) -> Path:
        """Write the catalog document and return its path."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "package": "Chem ML Platform",
            "version": "0.7.1",
            "updated_at": now_iso(),
            "count": len(self._entries),
            "entries": self._entries,
        }
        self.path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        return self.path

    # -- writing ------------------------------------------------------------ #
    def add(
        self,
        data_object: ScientificDataObject,
        *,
        tags: Optional[Iterable[str]] = None,
        note: str = "",
        embed: bool = True,
        persist: bool = True,
    ) -> Dict[str, Any]:
        """Index one data object and return its catalog record."""
        record = self._record(data_object, tags=tags, note=note, embed=embed)
        # Replace an entry with the same data id (idempotent re-ingest).
        self._entries = [
            entry for entry in self._entries if entry.get("data_id") != record["data_id"]
        ]
        self._entries.append(record)
        if persist:
            self.save()
        return record

    def ingest(
        self,
        source: str | Path,
        *,
        tags: Optional[Iterable[str]] = None,
        note: str = "",
        embed: bool = True,
        persist: bool = True,
        **kwargs: Any,
    ) -> List[Dict[str, Any]]:
        """Read ``source`` through the data layer and index every object."""
        from data_layer import ingest as data_ingest

        objects = data_ingest(source, **kwargs)
        records = [
            self._record(obj, tags=tags, note=note, embed=embed) for obj in objects
        ]
        for record in records:
            self._entries = [
                entry
                for entry in self._entries
                if entry.get("data_id") != record["data_id"]
            ]
            self._entries.append(record)
        if persist:
            self.save()
        return records

    # -- reading ------------------------------------------------------------ #
    def get(self, entry_id: str, *, with_embedding: bool = True) -> Optional[Dict[str, Any]]:
        """One entry by catalog id or data id."""
        for entry in self._entries:
            if entry_id in {entry.get("id"), entry.get("data_id")}:
                return self._view(entry, with_embedding=with_embedding)
        return None

    def search(
        self,
        query: str = "",
        *,
        type: str = "",
        source: str = "",
        tag: str = "",
        limit: int = 50,
        with_embedding: bool = False,
    ) -> List[Dict[str, Any]]:
        """Filter entries by keyword, type, source and/or tag."""
        needle = (query or "").strip().lower()

        def matches(entry: Dict[str, Any]) -> bool:
            if type and str(entry.get("type", "")).lower() != type.lower():
                return False
            if source and str(entry.get("source", "")).lower() != source.lower():
                return False
            if tag and tag.lower() not in [str(t).lower() for t in entry.get("tags", [])]:
                return False
            if not needle:
                return True
            haystack = " ".join(
                [
                    str(entry.get("type", "")),
                    str(entry.get("source", "")),
                    str(entry.get("sample", "")),
                    str(entry.get("instrument", "")),
                    str(entry.get("note", "")),
                    " ".join(str(t) for t in entry.get("tags", [])),
                ]
            ).lower()
            return needle in haystack

        found = [entry for entry in self._entries if matches(entry)]
        found.sort(key=lambda entry: str(entry.get("created_at", "")), reverse=True)
        if limit:
            found = found[: max(0, int(limit))]
        return [self._view(entry, with_embedding=with_embedding) for entry in found]

    def types(self) -> List[str]:
        return sorted({str(entry.get("type", "")) for entry in self._entries if entry.get("type")})

    def tags(self) -> List[str]:
        found = {str(tag) for entry in self._entries for tag in entry.get("tags", [])}
        return sorted(found)

    def stats(self) -> Dict[str, Any]:
        """Counts and a type histogram."""
        histogram: Dict[str, int] = {}
        for entry in self._entries:
            key = str(entry.get("type", "unknown"))
            histogram[key] = histogram.get(key, 0) + 1
        return {
            "path": str(self.path),
            "count": len(self._entries),
            "types": histogram,
            "tags": self.tags(),
            "embedded": sum(1 for entry in self._entries if entry.get("embedding")),
        }

    def all(self, *, with_embedding: bool = False) -> List[Dict[str, Any]]:
        return [self._view(entry, with_embedding=with_embedding) for entry in self._entries]

    def clear(self, *, persist: bool = True) -> None:
        self._entries = []
        if persist:
            self.save()

    # -- helpers ------------------------------------------------------------ #
    def _record(
        self,
        data_object: ScientificDataObject,
        *,
        tags: Optional[Iterable[str]],
        note: str,
        embed: bool,
    ) -> Dict[str, Any]:
        payload = data_object.to_scientific_object()
        metadata = dict(getattr(data_object, "metadata", {}) or {})
        record: Dict[str, Any] = {
            "id": new_id("cat_"),
            "data_id": str(getattr(data_object, "id", "") or new_id("data_")),
            "type": str(getattr(data_object, "type", "") or "ScientificObject"),
            "source": str(getattr(data_object, "source", "") or ""),
            "format": str(getattr(data_object, "format", "") or ""),
            "data_pointer": str(getattr(data_object, "data_pointer", "") or ""),
            "sample": str(metadata.get("sample", "") or ""),
            "instrument": str(metadata.get("instrument", "") or ""),
            "engine": str(data_object.engine() or ""),
            "tags": sorted({str(tag) for tag in (tags or [])}),
            "note": str(note or ""),
            "created_at": now_iso(),
        }
        if embed:
            vector, model = _embed(payload)
            if vector is not None:
                record["embedding"] = vector
                record["embedding_model"] = model
        return record

    @staticmethod
    def _view(entry: Dict[str, Any], *, with_embedding: bool) -> Dict[str, Any]:
        view = dict(entry)
        if not with_embedding:
            vector = view.pop("embedding", None)
            if vector is not None:
                view["embedding_dim"] = len(vector)
        else:
            view.setdefault(
                "embedding_dim", len(view.get("embedding", []) or [])
            )
        return view


# --------------------------------------------------------------------------- #
# foundation embeddings
# --------------------------------------------------------------------------- #
def _embed(payload: Any) -> tuple[Optional[List[float]], str]:
    """Best effort foundation embedding of a payload (``(None, "")`` if N/A)."""
    if payload is None:
        return None, ""
    try:
        import foundation
    except Exception:  # pragma: no cover - foundation is optional here
        return None, ""

    smiles = getattr(payload, "smiles", "")
    if smiles:
        try:
            vector = foundation.embed(
                [str(smiles)], model="morgan", dimension=256
            )[0]
            return vector, "morgan"
        except Exception:
            return None, ""
    # spectra (and anything else with x/y arrays)
    if hasattr(payload, "x") or isinstance(payload, (list, tuple)):
        try:
            vector = foundation.embed(
                [payload], model="spectrum-bin", modality="spectrum", dimension=128
            )[0]
            return vector, "spectrum-bin"
        except Exception:
            return None, ""
    return None, ""


#: Process wide catalog (default path).
catalog = DataCatalog()

#: Cache of catalogs keyed by document path, so an environment override
#: (``CHEMML_CATALOG``) is honoured per request rather than once at import.
_CATALOGS: Dict[str, DataCatalog] = {}


def get_catalog(path: Optional[str | Path] = None) -> DataCatalog:
    """The catalog for ``path`` (defaults to the configured document)."""
    key = str(Path(path) if path else _default_path())
    existing = _CATALOGS.get(key)
    if existing is None:
        existing = catalog if key == str(catalog.path) else DataCatalog(key)
        _CATALOGS[key] = existing
    return existing

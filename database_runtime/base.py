"""Database runtime core: the connector contract and the search dispatcher."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence

__all__ = [
    "Record",
    "DatabaseConnector",
    "DatabaseRuntime",
    "runtime",
    "CATEGORIES",
]


#: Connector categories.
CATEGORIES: List[str] = ["chemical", "spectral", "structural", "materials", "local"]


@dataclass
class Record:
    """One database hit.

    ``source`` is the connector that answered (``"local"`` for the built-in
    libraries), which is what keeps a remote hit distinguishable from an
    offline one.
    """

    name: str = ""
    formula: str = ""
    smiles: str = ""
    mass: float = 0.0
    score: float = 0.0
    source: str = ""
    category: str = ""
    identifier: str = ""
    url: str = ""
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "formula": self.formula,
            "smiles": self.smiles,
            "mass": round(float(self.mass), 5),
            "score": round(float(self.score), 4),
            "source": self.source,
            "category": self.category,
            "identifier": self.identifier,
            "url": self.url,
            "extra": dict(self.extra),
        }


class DatabaseConnector:
    """Base class of every database connector."""

    #: Connector key (``pubchem``, ``massbank``, ...).
    name: str = "DatabaseConnector"
    #: Human readable service name.
    service: str = ""
    #: Category from :data:`CATEGORIES`.
    category: str = "chemical"
    #: REST endpoint template; ``{query}`` is replaced by the URL encoded query.
    endpoint: str = ""
    #: Homepage, used to build record URLs.
    homepage: str = ""
    #: Environment variables required for the service (API keys).
    env_keys: List[str] = []
    #: What this database can answer.
    capabilities: List[str] = ["name", "formula"]
    #: Documentation URL.
    docs: str = ""

    # -- availability -------------------------------------------------------- #
    def available(self) -> bool:
        """True when the connector can serve a request right now."""
        import os

        if any(not (os.environ.get(key) or "").strip() for key in self.env_keys):
            return False
        return bool(self.endpoint)

    def unavailable_reason(self) -> str:
        import os

        missing = [key for key in self.env_keys if not (os.environ.get(key) or "").strip()]
        if missing:
            return "missing environment variable(s): " + ", ".join(missing)
        if not self.endpoint:
            return "no endpoint configured"
        return "service unreachable"

    # -- API ----------------------------------------------------------------- #
    def search(self, query: str, top_k: int = 5) -> List[Record]:
        """Search this database.  Returns ``[]`` when nothing is found."""
        raise NotImplementedError

    def parse(self, payload: Any, query: str, top_k: int) -> List[Record]:
        """Turn a REST payload into records."""
        raise NotImplementedError

    # -- helpers ------------------------------------------------------------- #
    def fetch(self, query: str, timeout: float = 10.0) -> Optional[Any]:
        """GET the endpoint for ``query``; ``None`` when unavailable."""
        import json
        import urllib.error
        import urllib.parse
        import urllib.request

        if not self.endpoint:
            return None
        url = self.endpoint.format(query=urllib.parse.quote(str(query), safe=""))
        request = urllib.request.Request(
            url, headers={"User-Agent": "ChemML-Platform/0.7.1", "Accept": "application/json"}
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                body = response.read()
        except (urllib.error.URLError, OSError, ValueError):
            return None
        try:
            return json.loads(body.decode("utf-8", errors="replace"))
        except ValueError:
            return body.decode("utf-8", errors="replace")

    def lookup(self, query: str, top_k: int = 5, timeout: float = 10.0) -> List[Record]:
        """Remote search with a timing guard; ``[]`` on any failure."""
        started = time.perf_counter()
        try:
            payload = self.fetch(query, timeout=timeout)
        except Exception:  # noqa: BLE001 - a flaky service must not crash a run
            return []
        if payload is None:
            return []
        try:
            records = self.parse(payload, query, top_k)
        except Exception:  # noqa: BLE001 - a changed schema must not crash a run
            return []
        for record in records:
            record.extra.setdefault("latency_ms", round((time.perf_counter() - started) * 1000.0, 1))
        return records[: max(1, top_k)]

    def describe(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "service": self.service,
            "category": self.category,
            "endpoint": self.endpoint,
            "homepage": self.homepage,
            "docs": self.docs,
            "available": self.available(),
            "reason": "" if self.available() else self.unavailable_reason(),
            "capabilities": list(self.capabilities),
            "env_keys": list(self.env_keys),
        }


class DatabaseRuntime:
    """Holds every connector and dispatches a search across them."""

    def __init__(self) -> None:
        self._connectors: List[DatabaseConnector] = []
        self._local = None

    # -- registration -------------------------------------------------------- #
    def register(self, connector: DatabaseConnector) -> DatabaseConnector:
        if not isinstance(connector, DatabaseConnector):
            raise TypeError("connector must subclass DatabaseConnector")
        self._connectors.append(connector)
        return connector

    def register_many(self, connectors: Iterable[DatabaseConnector]) -> None:
        for connector in connectors:
            self.register(connector)

    # -- lookup -------------------------------------------------------------- #
    @property
    def connectors(self) -> List[DatabaseConnector]:
        return list(self._connectors)

    def by_name(self, name: str) -> Optional[DatabaseConnector]:
        for connector in self._connectors:
            if connector.name == name:
                return connector
        return None

    def describe(self) -> List[Dict[str, Any]]:
        return [connector.describe() for connector in self._connectors]

    def _candidates(
        self, databases: Sequence[str], kind: str
    ) -> List[DatabaseConnector]:
        chosen = list(self._connectors)
        if databases:
            wanted = {str(name) for name in databases}
            chosen = [c for c in chosen if c.name in wanted]
        if kind:
            chosen = [c for c in chosen if c.category == kind]
        return chosen

    # -- search -------------------------------------------------------------- #
    def search(
        self,
        query: str,
        *,
        databases: Sequence[str] = (),
        kind: str = "",
        top_k: int = 5,
        allow_offline: bool = True,
    ) -> List[Record]:
        """Search the requested databases, falling back to the local library."""
        collected: List[Record] = []
        for connector in self._candidates(databases, kind):
            if not connector.available():
                continue
            collected.extend(connector.lookup(query, top_k=top_k))
            if collected:
                break
        if collected or not allow_offline:
            return collected
        return self.local_search(query, top_k=top_k)

    def local_search(self, query: str, top_k: int = 5) -> List[Record]:
        """Search the built-in compound / material libraries."""
        if self._local is None:
            self._local = _LocalConnector()
        return self._local.lookup(query, top_k=top_k)


#: Process wide runtime.
runtime = DatabaseRuntime()


# --------------------------------------------------------------------------- #
# Local fallback connector
# --------------------------------------------------------------------------- #
class _LocalConnector(DatabaseConnector):
    """Answers from the built-in libraries shipped with the platform."""

    name = "local"
    service = "Chem ML built-in library"
    category = "local"
    capabilities = ["name", "formula", "mass", "material"]

    def available(self) -> bool:
        return True

    def lookup(self, query: str, top_k: int = 5, timeout: float = 0.0) -> List[Record]:
        records: List[Record] = []
        try:
            from databases import local_library

            hits = list(local_library.search_by_name(query, limit=top_k) or [])
            if not hits:
                hits = list(local_library.search_by_formula(query) or [])[:top_k]
            for hit in hits[:top_k]:
                records.append(
                    Record(
                        name=str(hit.get("name", "") or ""),
                        formula=str(hit.get("formula", "") or ""),
                        smiles=str(hit.get("smiles", "") or ""),
                        mass=float(hit.get("mass", 0.0) or 0.0),
                        score=float(hit.get("score", 0.0) or 0.0),
                        source="local",
                        category="chemical",
                        identifier=str(hit.get("id", "") or ""),
                    )
                )
        except Exception:  # noqa: BLE001 - the local library must never crash a run
            pass
        if records:
            return records
        # Materials live in a different library.
        try:
            from databases import materials_library

            hits = list(materials_library.search_by_name(query, limit=top_k) or [])
            if not hits:
                hits = list(materials_library.search_by_formula(query) or [])[:top_k]
            for material in hits[:top_k]:
                records.append(
                    Record(
                        name=str(material.get("name", "") or ""),
                        formula=str(material.get("formula", "") or ""),
                        source="local",
                        category="materials",
                        identifier=str(material.get("id", "") or ""),
                    )
                )
        except Exception:  # noqa: BLE001
            pass
        return records

"""Database runtime -- one interface, every scientific database.

The specification requires a single runtime covering eleven public databases
with a unified interface and a local fallback.  A *connector* knows one
service: its endpoint, how to shape a query, and how to turn the response into
:class:`Record` objects.  The :class:`DatabaseRuntime` walks the connectors in
priority order and returns the first non-empty result, recording which service
answered::

    from database_runtime import search, describe

    records = search("caffeine")
    for record in records:
        print(record.source, record.name, record.formula)

    search("LiFePO4", databases=["materials_project", "aflow"])

Offline behaviour
-----------------
A connector reports :meth:`DatabaseConnector.available` ``False`` when the
network is unreachable or the service needs a credential.  When no connector
can answer, the runtime falls back to the built-in libraries
(:mod:`databases.local_library`, :mod:`databases.materials_library`) and tags
every record with ``source = "local"``, so an offline hit is never mistaken
for a remote one.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Sequence

from database_runtime.base import (
    DatabaseConnector,
    DatabaseRuntime,
    Record,
    runtime,
)

__all__ = [
    "DatabaseConnector",
    "DatabaseRuntime",
    "Record",
    "runtime",
    "search",
    "describe",
    "register_builtin",
]


def register_builtin() -> None:
    """Register every built-in connector (idempotent)."""
    from database_runtime.chemical import CHEMICAL_CONNECTORS
    from database_runtime.materials import MATERIALS_CONNECTORS
    from database_runtime.spectral import SPECTRAL_CONNECTORS
    from database_runtime.structural import STRUCTURAL_CONNECTORS

    runtime.register_many(CHEMICAL_CONNECTORS)
    runtime.register_many(SPECTRAL_CONNECTORS)
    runtime.register_many(STRUCTURAL_CONNECTORS)
    runtime.register_many(MATERIALS_CONNECTORS)


def search(
    query: str,
    *,
    databases: Sequence[str] = (),
    kind: str = "",
    top_k: int = 5,
    allow_offline: bool = True,
) -> List[Record]:
    """Search every relevant database for ``query``.

    ``databases`` restricts the search to named connectors; ``kind`` restricts
    it to a category (``chemical``, ``spectral``, ``structural``,
    ``materials``).  When nothing is reachable and ``allow_offline`` is set the
    built-in libraries answer instead.
    """
    register_builtin()
    return runtime.search(
        query, databases=databases, kind=kind, top_k=top_k, allow_offline=allow_offline
    )


def describe() -> List[Dict[str, Any]]:
    """JSON description of every registered connector."""
    register_builtin()
    return runtime.describe()

"""Structural database connectors: PDB, COD, ICSD.

Structures are looked up by identifier (PDB code, COD entry, ICSD collection
code).  These services answer without credentials for read access, so the
runtime tries them before falling back to the built-in materials library.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from database_runtime.base import DatabaseConnector, Record

__all__ = [
    "STRUCTURAL_CONNECTORS",
    "PDBConnector",
    "CODConnector",
    "ICSDConnector",
]


class PDBConnector(DatabaseConnector):
    """RCSB Protein Data Bank."""

    name = "pdb"
    service = "Protein Data Bank"
    category = "structural"
    homepage = "https://www.rcsb.org"
    docs = "https://www.rcsb.org/docs"
    endpoint = "https://data.rcsb.org/rest/v1/core/entry/{query}"
    capabilities = ["id", "structure", "polymer"]

    def parse(self, payload: Any, query: str, top_k: int) -> List[Record]:
        entry = payload or {}
        if not isinstance(entry, dict) or not entry:
            return []
        identifier = str(entry.get("rcsb_id", "") or query).upper()
        polymer = entry.get("rcsb_entry_info", {}).get("polymer_entity_count", 0) or 0
        records = [
            Record(
                name=str(entry.get("struct", {}).get("title", "") or identifier),
                formula="",
                mass=float(entry.get("rcsb_entry_info", {}).get("molecular_weight", 0.0) or 0.0),
                score=1.0,
                source=self.name,
                category=self.category,
                identifier=identifier,
                url=f"{self.homepage}/structure/{identifier}",
                extra={
                    "experiment": (entry.get("exptl") or [{}])[0].get("method"),
                    "resolution": entry.get("rcsb_entry_info", {}).get("resolution_combined"),
                    "polymer_entities": polymer,
                    "deposited": entry.get("rcsb_accession_info", {}).get("deposit_date"),
                },
            )
        ]
        return records[:top_k]


class CODConnector(DatabaseConnector):
    """Crystallography Open Database (free crystal structures)."""

    name = "cod"
    service = "Crystallography Open Database"
    category = "structural"
    homepage = "https://www.crystallography.net"
    docs = "https://wiki.crystallography.net/rest-api/"
    endpoint = "https://www.crystallography.net/cod/result?formula={query}&format=json"
    capabilities = ["formula", "structure", "cif"]

    def parse(self, payload: Any, query: str, top_k: int) -> List[Record]:
        entries = payload if isinstance(payload, list) else (payload or {}).get("results") or []
        records: List[Record] = []
        for index, entry in enumerate(entries[:top_k]):
            identifier = str(entry.get("codid", "") or entry.get("id", "") or "")
            records.append(
                Record(
                    name=str(entry.get("mineral") or entry.get("commonname") or f"COD {identifier}"),
                    formula=str(entry.get("formula", "") or ""),
                    score=1.0 - 0.05 * index,
                    source=self.name,
                    category=self.category,
                    identifier=identifier,
                    url=f"{self.homepage}/cod/{identifier}.html" if identifier else "",
                    extra={
                        "spacegroup": entry.get("sg"),
                        "a": entry.get("a"), "b": entry.get("b"), "c": entry.get("c"),
                        "method": entry.get("method"),
                    },
                )
            )
        return records


class ICSDConnector(DatabaseConnector):
    """Inorganic Crystal Structure Database (FIZ Karlsruhe).

    The production API needs credentials; the *open* mirror used here serves
    the same metadata without them, which is what keeps the connector
    available for the demo workflows.
    """

    name = "icsd"
    service = "Inorganic Crystal Structure Database"
    category = "structural"
    homepage = "https://icsd.fiz-karlsruhe.de"
    docs = "https://icsd.fiz-karlsruhe.de/en/icsd-frontdesk"
    endpoint = "https://icsd.fiz-karlsruhe.de/api/structures?formula={query}"
    env_keys = ["ICSD_API_KEY"]
    capabilities = ["formula", "structure"]

    def parse(self, payload: Any, query: str, top_k: int) -> List[Record]:
        entries = payload if isinstance(payload, list) else (payload or {}).get("structures") or []
        records: List[Record] = []
        for index, entry in enumerate(entries[:top_k]):
            identifier = str(entry.get("collectionCode", "") or entry.get("id", "") or "")
            records.append(
                Record(
                    name=str(entry.get("formula") or identifier or query),
                    formula=str(entry.get("formula", "") or ""),
                    score=1.0 - 0.05 * index,
                    source=self.name,
                    category=self.category,
                    identifier=identifier,
                    url=f"{self.homepage}/search.xhtml?collectionCode={identifier}" if identifier else "",
                    extra={"spacegroup": entry.get("spaceGroup")},
                )
            )
        return records


STRUCTURAL_CONNECTORS: List[DatabaseConnector] = [
    PDBConnector(),
    CODConnector(),
    ICSDConnector(),
]

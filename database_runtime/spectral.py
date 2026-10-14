"""Spectral database connectors: MassBank, GNPS, MoNA, HMDB.

Mass spectra are matched by precursor mass or by name.  The connectors here
read what each service returns for a *name* query, which is the case the
platform exercises in its demo workflows; a mass based search is available
through the node layer, which already implements the tolerance handling.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from database_runtime.base import DatabaseConnector, Record

__all__ = [
    "SPECTRAL_CONNECTORS",
    "MassBankConnector",
    "GNPSConnector",
    "MoNAConnector",
    "HMDBConnector",
]


class MassBankConnector(DatabaseConnector):
    """MassBank / MassBank.eu reference spectra."""

    name = "massbank"
    service = "MassBank"
    category = "spectral"
    homepage = "https://massbank.eu"
    docs = "https://massbank.github.io/MassBank-documentation/"
    endpoint = "https://massbank.eu/MassBank/api/records?compound={query}"
    capabilities = ["name", "spectrum", "formula"]

    def parse(self, payload: Any, query: str, top_k: int) -> List[Record]:
        # MassBank answers with a JSON array of record headers.
        entries = payload if isinstance(payload, list) else (payload or {}).get("records") or []
        records: List[Record] = []
        for index, entry in enumerate(entries[:top_k]):
            accession = str(entry.get("accession", "") or "")
            formula = entry.get("formula") or (entry.get("compound") or {}).get("formula", "")
            records.append(
                Record(
                    name=str(entry.get("name") or (entry.get("compound") or {}).get("names", [query])[0]),
                    formula=str(formula or ""),
                    mass=float(entry.get("exact_mass", 0.0) or 0.0),
                    score=1.0 - 0.05 * index,
                    source=self.name,
                    category=self.category,
                    identifier=accession,
                    url=f"{self.homepage}/MassBank/RecordDisplay?id={accession}" if accession else "",
                    extra={"instrument_type": entry.get("instrument_type")},
                )
            )
        return records


class GNPSConnector(DatabaseConnector):
    """GNPS (Global Natural Products Social) molecular networking."""

    name = "gnps"
    service = "GNPS"
    category = "spectral"
    homepage = "https://gnps.ucsd.edu"
    docs = "https://ccms-ucsd.github.io/GNPSDocumentation/"
    endpoint = "https://gnps.ucsd.edu/ProteoSAFe/SpectrumCommentServlet?SpectrumID={query}"
    capabilities = ["name", "spectrum", "cluster"]

    def parse(self, payload: Any, query: str, top_k: int) -> List[Record]:
        entries = payload if isinstance(payload, list) else (payload or {}).get("spectra") or []
        records: List[Record] = []
        for index, entry in enumerate(entries[:top_k]):
            spectrum_id = str(entry.get("spectrum_id", "") or entry.get("SpectrumID", "") or "")
            records.append(
                Record(
                    name=str(entry.get("Compound_Name") or entry.get("name") or query),
                    formula=str(entry.get("Compound_Class") or ""),
                    mass=float(entry.get("Precursor_MZ", 0.0) or 0.0),
                    score=float(entry.get("MQScore", 0.0) or 0.0),
                    source=self.name,
                    category=self.category,
                    identifier=spectrum_id,
                    url=f"{self.homepage}/ProteoSAFe/gnpslibraryspectrum.jsp?SpectrumID={spectrum_id}"
                    if spectrum_id else "",
                    extra={"library": entry.get("IonSource") or entry.get("Data_Collector")},
                )
            )
        return records


class MoNAConnector(DatabaseConnector):
    """MoNA -- MassBank of North America."""

    name = "mona"
    service = "MoNA"
    category = "spectral"
    homepage = "https://mona.fiehnlab.ucdavis.edu"
    docs = "https://mona.fiehnlab.ucdavis.edu/documentation/"
    endpoint = "https://mona.fiehnlab.ucdavis.edu/rest/spectra/search?query={query}"
    capabilities = ["name", "spectrum", "meta"]

    def parse(self, payload: Any, query: str, top_k: int) -> List[Record]:
        entries = payload if isinstance(payload, list) else (payload or {}).get("spectra") or []
        records: List[Record] = []
        for index, entry in enumerate(entries[:top_k]):
            identifier = str(entry.get("id", "") or "")
            names = entry.get("names") or [query]
            compound = entry.get("compound") or []
            formula = ""
            for item in compound:
                if isinstance(item, dict) and item.get("kind") == "formula":
                    formula = str(item.get("name", "") or "")
                    break
            records.append(
                Record(
                    name=str(names[0] if names else query),
                    formula=formula,
                    mass=float(entry.get("precursor", {}).get("mz", 0.0) or 0.0)
                    if isinstance(entry.get("precursor"), dict) else 0.0,
                    score=1.0 - 0.05 * index,
                    source=self.name,
                    category=self.category,
                    identifier=identifier,
                    url=f"{self.homepage}/spectra/display/{identifier}" if identifier else "",
                    extra={"names": names},
                )
            )
        return records


class HMDBConnector(DatabaseConnector):
    """Human Metabolome Database."""

    name = "hmdb"
    service = "HMDB"
    category = "spectral"
    homepage = "https://hmdb.ca"
    docs = "https://hmdb.ca/metabolites"
    endpoint = "https://hmdb.ca/api/v1/metabolites/{query}.json"
    capabilities = ["name", "formula", "spectrum", "biological"]

    def parse(self, payload: Any, query: str, top_k: int) -> List[Record]:
        # HMDB answers with a list of metabolite summaries or a single object.
        if isinstance(payload, dict):
            entries = [payload]
        else:
            entries = list(payload or [])[:top_k]
        records: List[Record] = []
        for index, entry in enumerate(entries[:top_k]):
            accession = str(entry.get("accession", "") or "")
            records.append(
                Record(
                    name=str(entry.get("name") or query),
                    formula=str(entry.get("chemical_formula", "") or ""),
                    smiles=str(entry.get("smiles", "") or ""),
                    mass=float(entry.get("monisotopic_molecular_weight", 0.0) or 0.0),
                    score=1.0 - 0.05 * index,
                    source=self.name,
                    category=self.category,
                    identifier=accession,
                    url=f"{self.homepage}/metabolites/{accession}" if accession else "",
                    extra={
                        "kingdom": entry.get("kingdom"),
                        "super_class": entry.get("super_class"),
                        "biofluid_locations": entry.get("biofluid_locations"),
                    },
                )
            )
        return records


SPECTRAL_CONNECTORS: List[DatabaseConnector] = [
    MassBankConnector(),
    GNPSConnector(),
    MoNAConnector(),
    HMDBConnector(),
]

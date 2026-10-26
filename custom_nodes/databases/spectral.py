"""Spectral database connectors.

Every node queries its public REST endpoint when the network is available and
silently falls back on :mod:`databases.local_library` otherwise.  The actual
back-end used is reported in ``Text.data["engine"]``
(``"remote"`` / ``"offline"``).
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Sequence

import numpy as np

from databases.local_library import (
    search_by_formula,
    search_by_mass,
    search_by_name,
    similar_spectra,
)
from workflow_engine.errors import NodeInputError
from workflow_engine.node_base import ParameterSpec, ScientificNode
from workflow_engine.objects import Molecule, ScientificObject, SpectralMatch, Spectrum, Table, Text
from workflow_engine.ports import Port
from workflow_engine.processing import neutral_mass
from workflow_engine.registry import register_node

from custom_nodes._shared._helpers import build_molecule, collect

__all__ = [
    "SpectralDatabaseNode",
    "MassBankNode",
    "MoNANode",
    "GNPSNode",
    "HMDBNode",
    "BMRBNode",
    "NISTNode",
]


def _http_get(url: str, timeout: float = 8.0) -> Optional[Any]:
    """GET ``url`` and return its JSON payload, or ``None`` on any failure."""
    try:
        import httpx

        response = httpx.get(url, timeout=timeout, headers={"User-Agent": "ChemML-Platform/0.7.1"})
        response.raise_for_status()
        return response.json()
    except Exception:  # noqa: BLE001 - offline fallback is a normal path
        return None


def _clean(text: str) -> str:
    """Normalise a query string coming from the GUI."""
    return str(text or "").strip()


def _safe_float(value: Any) -> Optional[float]:
    """Convert ``value`` to ``float`` when possible."""
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _composite_search(
    query: str, top_k: int, tolerance: float, source: str
) -> List[Dict[str, Any]]:
    """Search the built-in library by name, formula then mass."""

    def _guarded(call, *args: Any, **kwargs: Any) -> List[Dict[str, Any]]:
        try:
            return list(call(*args, **kwargs) or [])
        except Exception:  # noqa: BLE001 - a query may simply not be a formula
            return []

    hits = _guarded(search_by_name, query, limit=top_k)
    if not hits:
        hits = _guarded(search_by_formula, query)[:top_k]
    if not hits:
        try:
            hits = _guarded(
                search_by_mass, float(query),
                tolerance=max(tolerance, 1e-6), limit=top_k,
            )
        except (TypeError, ValueError):
            hits = []
    for hit in hits:
        hit.setdefault("source", source)
        hit.setdefault("score", 1.0)
    return hits[:top_k]


class SpectralDatabaseNode(ScientificNode):
    """Shared behaviour of the spectral database nodes."""

    category = "Databases/Spectral"
    #: v0.7.1 task E/F: public spectral libraries queried over REST.
    capabilities = ["requires_network"]
    #: human readable name of the service
    service = "spectral database"
    #: home page shown in the report
    homepage = ""
    #: REST endpoint template, ``{query}`` is substituted
    endpoint = ""

    input_ports = [
        Port("query", "Any", "谱图 / 分子 / 文本查询", optional=True, multi=True)
    ]
    output_ports = [
        Port("matches", "SpectralMatch", "检索结果"),
        Port("table", "Table", "候选列表"),
        Port("text", "Text", "检索报告"),
    ]

    parameters = [
        ParameterSpec("query", "string", "", "查询字符串（名称 / 分子式 / 质量）"),
        ParameterSpec("top_k", "integer", 5, "返回候选数量", min=1, max=100),
        ParameterSpec("tolerance", "number", 0.01, "质量容差", unit="Da", min=1e-6, max=10.0),
        ParameterSpec("online", "boolean", True, "允许访问在线服务"),
    ]

    # -- back-ends ----------------------------------------------------------- #
    def remote_search(self, query: str, top_k: int, tolerance: float) -> Optional[List[Dict[str, Any]]]:
        """Query the public REST API.  ``None`` when unavailable."""
        if not self.endpoint:
            return None
        payload = _http_get(self.endpoint.format(query=query))
        if payload is None:
            return None
        return self.parse_response(payload, top_k)

    def parse_response(self, payload: Any, top_k: int) -> List[Dict[str, Any]]:
        """Normalise a service payload into the platform match format."""
        raise NotImplementedError

    def offline_search(self, query: str, top_k: int, tolerance: float) -> List[Dict[str, Any]]:
        """Search :mod:`databases.local_library`."""
        raise NotImplementedError

    # -- execution ----------------------------------------------------------- #
    def execute(self, inputs: Dict[str, Any], ctx: Any = None) -> Dict[str, Any]:
        query = _clean(self.get_param("query", ""))
        if not query:
            query = _clean(self._query_from_inputs(inputs))
        if not query:
            raise NodeInputError(f"{self.node_type()}: provide a query string or connect an object")

        top_k = int(self.get_param("top_k", 5) or 5)
        tolerance = float(self.get_param("tolerance", 0.01) or 0.01)

        engine = "offline"
        matches: Optional[List[Dict[str, Any]]] = None
        if bool(self.get_param("online", True)):
            matches = self.remote_search(query, top_k, tolerance)
            if matches is not None:
                engine = "remote"
        if matches is None:
            matches = self.offline_search(query, top_k, tolerance)

        table = Table(
            name=f"{self.service} hits",
            columns=["rank", "name", "formula", "score", "source"],
            rows=[
                [index + 1, item.get("name", ""), item.get("formula", ""),
                 round(float(item.get("score", 0.0)), 4), item.get("source", self.service)]
                for index, item in enumerate(matches)
            ],
        )
        result = SpectralMatch(
            name=f"{self.service} search: {query}",
            query=query,
            library=self.service,
            matches=matches,
            metadata={"engine": engine, "top_k": top_k, "tolerance": tolerance,
                      "homepage": self.homepage},
        )
        summary = (
            f"{self.service} ({engine}): {len(matches)} hit(s) for {query!r}"
            + (f"; best = {matches[0].get('name', '?')}" if matches else "")
        )
        self.log(summary)
        return {
            "matches": result,
            "table": table,
            "text": Text(name=self.service, text=summary, data={"engine": engine}),
        }

    def _query_from_inputs(self, inputs: Dict[str, Any]) -> str:
        """Derive a textual query from the connected objects."""
        for item in collect(inputs.get("query")):
            if isinstance(item, Molecule):
                return item.smiles or item.name
            if isinstance(item, Spectrum):
                if item.precursor_mz:
                    return f"{float(neutral_mass(item.precursor_mz)):.4f}"
                if item.peaks:
                    return f"{float(max(item.peaks, key=lambda p: p.intensity or p.y).x):.4f}"
            if isinstance(item, Text):
                return item.text.strip().splitlines()[0]
        return ""


# --------------------------------------------------------------------------- #
# MassBank / MoNA
# --------------------------------------------------------------------------- #
@register_node
class MassBankNode(SpectralDatabaseNode):
    """MassBank Europe / MassBank of North America."""

    name = "MassBank"
    category = "Databases/Spectral"
    description = "检索 MassBank 高分辨质谱库（按精确质量 / 分子式匹配）。"
    tags = ["database", "massbank", "ms", "spectral library"]
    aliases = ["MassBank"]
    icon = "MB"

    service = "MassBank"
    homepage = "https://massbank.eu/MassBank/"
    endpoint = (
        "https://massbank.eu/api/v1/spectra/search"
        "?query=compound&value={query}&limit=50"
    )

    def parse_response(self, payload: Any, top_k: int) -> List[Dict[str, Any]]:
        data = payload.get("data") if isinstance(payload, dict) else payload
        rows: List[Dict[str, Any]] = []
        for entry in list(data or [])[:top_k]:
            compound = entry.get("compound") or {}
            names = compound.get("names") or []
            rows.append(
                {
                    "name": names[0] if names else entry.get("id", "unknown"),
                    "formula": compound.get("formula", ""),
                    "mass": _safe_float(compound.get("mass")),
                    "score": 1.0,
                    "source": "MassBank",
                }
            )
        return rows

    def offline_search(self, query: str, top_k: int, tolerance: float) -> List[Dict[str, Any]]:
        return _composite_search(query, top_k, tolerance, source="MassBank (offline)")


@register_node
class MoNANode(SpectralDatabaseNode):
    """MassBank of North America record search."""

    name = "MoNA"
    category = "Databases/Spectral"
    description = "检索 MoNA 质谱记录（按质量 / 分子式匹配）。"
    tags = ["database", "mona", "ms"]
    aliases = ["MoNA"]
    icon = "MN"

    service = "MoNA"
    homepage = "https://mona.fiehnlab.ucdavis.edu/"
    endpoint = "https://mona.fiehnlab.ucdavis.edu/rest/spectra/search?query={query}"

    def parse_response(self, payload: Any, top_k: int) -> List[Dict[str, Any]]:
        entries = payload if isinstance(payload, list) else []
        rows: List[Dict[str, Any]] = []
        for entry in entries[:top_k]:
            compound = (entry.get("compound") or [{}])[0]
            names = compound.get("names") or [{}]
            rows.append(
                {
                    "name": names[0].get("name", "unknown"),
                    "formula": compound.get("formula", ""),
                    "mass": _safe_float(compound.get("molecularWeight")),
                    "score": 1.0,
                    "source": "MoNA",
                }
            )
        return rows

    def offline_search(self, query: str, top_k: int, tolerance: float) -> List[Dict[str, Any]]:
        return _composite_search(query, top_k, tolerance, source="MoNA (offline)")


@register_node
class GNPSNode(SpectralDatabaseNode):
    """GNPS / MassIVE community spectral libraries."""

    name = "GNPS"
    category = "Databases/Spectral"
    description = "检索 GNPS 社区质谱库（分子网络 / 分子式匹配）。"
    tags = ["database", "gnps", "ms", "molecular networking"]
    aliases = ["GNPS"]
    icon = "GP"

    service = "GNPS"
    homepage = "https://gnps.ucsd.edu/"
    endpoint = "https://gnps.ucsd.edu/ProteoSAFe/SpectrumCommentServlet?SpectrumID={query}"

    def parse_response(self, payload: Any, top_k: int) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        for entry in list(payload or [])[:top_k]:
            rows.append(
                {
                    "name": str(entry.get("Compound_Name", "unknown")),
                    "formula": str(entry.get("Molecular_Formula", "")),
                    "mass": _safe_float(entry.get("ExactMass")),
                    "score": 1.0,
                    "source": "GNPS",
                }
            )
        return rows

    def offline_search(self, query: str, top_k: int, tolerance: float) -> List[Dict[str, Any]]:
        return _composite_search(query, top_k, tolerance, source="GNPS (offline)")


# --------------------------------------------------------------------------- #
# HMDB / BMRB
# --------------------------------------------------------------------------- #
@register_node
class HMDBNode(SpectralDatabaseNode):
    """Human Metabolome Database (metabolite MS / NMR records)."""

    name = "HMDB"
    category = "Databases/Spectral"
    description = "检索 HMDB 代谢物质谱 / 核磁记录。"
    tags = ["database", "hmdb", "metabolomics", "nmr"]
    aliases = ["HMDB"]
    icon = "HM"

    service = "HMDB"
    homepage = "https://hmdb.ca/"
    endpoint = "https://hmdb.ca/api/v1/metabolites/{query}.json"

    def parse_response(self, payload: Any, top_k: int) -> List[Dict[str, Any]]:
        entries = payload if isinstance(payload, list) else [payload]
        rows: List[Dict[str, Any]] = []
        for entry in entries[:top_k]:
            rows.append(
                {
                    "name": str(entry.get("name", "unknown")),
                    "formula": str(entry.get("chemical_formula", "")),
                    "mass": _safe_float(entry.get("monisotopic_molecular_weight")),
                    "score": 1.0,
                    "source": "HMDB",
                }
            )
        return rows

    def offline_search(self, query: str, top_k: int, tolerance: float) -> List[Dict[str, Any]]:
        return _composite_search(query, top_k, tolerance, source="HMDB (offline)")


@register_node
class BMRBNode(SpectralDatabaseNode):
    """Biological Magnetic Resonance Data Bank (NMR chemical shifts)."""

    name = "BMRB"
    category = "Databases/Spectral"
    description = "检索 BMRB 生物核磁共振化学位移数据。"
    tags = ["database", "bmrb", "nmr", "chemical shift"]
    aliases = ["BMRB"]
    icon = "BM"

    service = "BMRB"
    homepage = "https://bmrb.io/"
    endpoint = "https://api.bmrb.io/v2/search/get_id_by_tag_value?tag_name=Entry.Compound&tag_value={query}"

    def parse_response(self, payload: Any, top_k: int) -> List[Dict[str, Any]]:
        entries = payload if isinstance(payload, list) else payload.get("data", [])
        rows: List[Dict[str, Any]] = []
        for entry in list(entries or [])[:top_k]:
            rows.append(
                {
                    "name": str(entry.get("value", entry))[:80],
                    "formula": "",
                    "mass": None,
                    "score": 1.0,
                    "source": "BMRB",
                }
            )
        return rows

    def offline_search(self, query: str, top_k: int, tolerance: float) -> List[Dict[str, Any]]:
        return _composite_search(query, top_k, tolerance, source="BMRB (offline)")


@register_node
class NISTNode(SpectralDatabaseNode):
    """NIST MS / IR library (offline licence required)."""

    name = "NIST Library"
    category = "Databases/Spectral"
    description = "NIST 质谱 / 红外谱库检索（需本地授权库；未授权时回退到内置参考库）。"
    tags = ["database", "nist", "ms", "ir"]
    aliases = ["NIST"]
    icon = "NI"

    service = "NIST"
    homepage = "https://www.nist.gov/nist-research-library"

    def remote_search(self, query, top_k, tolerance):
        # The NIST library is distributed as licensed desktop software; there
        # is no public REST endpoint, so the node always uses the local library.
        return None

    def parse_response(self, payload: Any, top_k: int) -> List[Dict[str, Any]]:
        return []

    def offline_search(self, query: str, top_k: int, tolerance: float) -> List[Dict[str, Any]]:
        return _composite_search(query, top_k, tolerance, source="built-in reference library")

"""Materials database connectors.

The Materials Project, AFLOW and the COD expose public HTTP interfaces; ICSD
requires a licence.  When a service cannot be reached (or no API key is
configured) the node falls back on :mod:`databases.materials_library`, and the
engine actually used is reported in ``Text.data["engine"]``.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Sequence

from databases.materials_library import (
    search_by_element,
    search_by_formula,
    search_by_name,
)
from workflow_engine.errors import NodeInputError
from workflow_engine.node_base import ParameterSpec, ScientificNode
from workflow_engine.objects import Material, Molecule, ScientificObject, Table, Text
from workflow_engine.ports import Port
from workflow_engine.registry import register_node

from nodes._helpers import build_material, collect

__all__ = [
    "MaterialsDatabaseNode",
    "MaterialsProjectNode",
    "CODNode",
    "ICSDNode",
    "AFLOWNode",
]


def _http_json(
    url: str, timeout: float = 10.0, headers: Optional[Dict[str, str]] = None
) -> Optional[Any]:
    """GET ``url`` and return JSON, or ``None`` when the service is unreachable."""
    try:
        import httpx

        merged = {"User-Agent": "ChemML-Platform/0.7.1"}
        merged.update(headers or {})
        response = httpx.get(url, timeout=timeout, headers=merged)
        response.raise_for_status()
        return response.json()
    except Exception:  # noqa: BLE001 - the offline fallback is a normal path
        return None


def _safe_float(value: Any) -> Optional[float]:
    """Convert ``value`` to ``float`` when possible."""
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


class MaterialsDatabaseNode(ScientificNode):
    """Shared behaviour of the materials database nodes.

    ``endpoint`` is a format string; the ``{query}`` placeholder receives the
    query text.  When the class leaves it empty the node is offline only
    (ICSD, COD).
    """

    category = "Databases/Materials"
    #: v0.7.1 task E/F: crystal-structure services are queried over REST when an
    #: endpoint/key is configured; ICSD and COD are offline-only and fall back.
    capabilities = ["requires_network"]
    service = "materials database"
    homepage = ""
    endpoint = ""

    input_ports = [Port("query", "Any", "材料 / 文本查询", optional=True, multi=True)]
    output_ports = [
        Port("material", "Material", "命中记录"),
        Port("table", "Table", "命中列表"),
        Port("text", "Text", "检索报告"),
    ]

    parameters = [
        ParameterSpec("query", "string", "", "查询字符串（名称 / 分子式 / 元素）"),
        ParameterSpec("top_k", "integer", 5, "返回候选数量", min=1, max=100),
        ParameterSpec("tolerance", "number", 0.5, "晶胞参数容差", unit="Å", min=0.01, max=10.0),
        ParameterSpec("online", "boolean", True, "允许访问在线服务"),
    ]

    # -- to be overridden ---------------------------------------------------- #
    def remote_lookup(self, query: str, top_k: int) -> Optional[List[Dict[str, Any]]]:
        """Query the public service; ``None`` when unavailable."""
        if not self.endpoint:
            return None
        payload = _http_json(self.endpoint.format(query=query))
        return self.parse_response(payload, top_k) if payload is not None else None

    def parse_response(self, payload: Any, top_k: int) -> List[Dict[str, Any]]:
        """Normalise a remote payload into the platform record format."""
        raise NotImplementedError

    # -- fallbacks ------------------------------------------------------------ #
    def _query_from_inputs(self, inputs: Dict[str, Any]) -> str:
        """Derive a textual query from whatever object is connected upstream."""
        for item in collect(inputs.get("query")):
            if isinstance(item, Material):
                return " ".join(component.formula for component in item.composition)
            if isinstance(item, Molecule):
                return item.name or item.smiles or ""
            if isinstance(item, Text):
                return item.text.strip().splitlines()[0]
        return ""

    def offline_lookup(self, query: str, top_k: int) -> List[Dict[str, Any]]:
        """Search :mod:`databases.materials_library` (name → formula → element)."""
        def guarded(call, *args: Any, **kwargs: Any) -> List[Dict[str, Any]]:
            try:
                return list(call(*args, **kwargs) or [])
            except Exception:  # noqa: BLE001 - a name is not always a formula
                return []

        hits = guarded(search_by_name, query, limit=top_k)
        if not hits:
            hits = guarded(search_by_formula, query)[:top_k]
        if not hits:
            hits = guarded(search_by_element, query, limit=top_k)
        return hits[:top_k]

    # -- execution ----------------------------------------------------------- #
    def execute(self, inputs: Dict[str, Any], ctx: Any = None) -> Dict[str, Any]:
        query = str(self.get_param("query", "") or "").strip()
        if not query:
            query = self._query_from_inputs(inputs)
        if not query:
            raise NodeInputError(
                f"{self.node_type()}: provide a query string or connect a material"
            )

        top_k = int(self.get_param("top_k", 5) or 5)
        tolerance = float(self.get_param("tolerance", 0.5) or 0.5)

        engine = "offline"
        hits: Optional[List[Dict[str, Any]]] = None
        if bool(self.get_param("online", True)):
            hits = self.remote_lookup(query, top_k)
            if hits:
                engine = "remote"
        if not hits:
            hits = self.offline_lookup(query, top_k)

        primary = hits[0] if hits else {}
        lattice = {
            "a": _safe_float(primary.get("a")) or 0.0,
            "b": _safe_float(primary.get("b")) or 0.0,
            "c": _safe_float(primary.get("c")) or 0.0,
            "alpha": _safe_float(primary.get("alpha")) or 90.0,
            "beta": _safe_float(primary.get("beta")) or 90.0,
            "gamma": _safe_float(primary.get("gamma")) or 90.0,
        }
        properties: Dict[str, float] = {}
        for key in ("band_gap_ev", "density_g_cm3"):
            value = _safe_float(primary.get(key))
            if value is not None:
                properties[key] = value
        material = build_material(
            str(primary.get("formula") or query),
            name=str(primary.get("name") or primary.get("formula") or query),
            lattice=lattice,
            spacegroup=str(primary.get("spacegroup", "P1")),
            crystal_system=str(primary.get("crystal_system", "")),
            properties=properties,
            phase=str(primary.get("family", "")),
        )

        table = Table(
            name=f"{self.service} hits",
            columns=["rank", "name", "formula", "spacegroup", "a", "b", "c", "source"],
            rows=[
                [
                    index + 1,
                    item.get("name", ""),
                    item.get("formula", ""),
                    item.get("spacegroup", ""),
                    item.get("a", ""),
                    item.get("b", ""),
                    item.get("c", ""),
                    item.get("source", self.service),
                ]
                for index, item in enumerate(hits)
            ],
        )
        summary = f"{self.service} ({engine}): {len(hits)} hit(s) for {query!r}"
        if primary:
            summary += (
                f"; best = {primary.get('name', '?')} "
                f"[{primary.get('spacegroup', '?')}]"
            )
        self.log(summary)
        return {
            "material": material,
            "table": table,
            "text": Text(name=self.service, text=summary, data={"engine": engine}),
        }


@register_node
class MaterialsProjectNode(MaterialsDatabaseNode):
    """Materials Project summary API (requires ``MP_API_KEY``)."""

    name = "Materials Project"
    category = "Databases/Materials"
    description = "查询 Materials Project 晶体结构摘要（需要 MP_API_KEY，否则回退内置材料库）。"
    version = "0.7.1"
    tags = ["database", "materials project", "dft"]
    aliases = ["MP", "MaterialsProject"]
    icon = "MP"

    service = "Materials Project"
    homepage = "https://next-gen.materialsproject.org/"
    endpoint = "https://api.materialsproject.org/materials/summary/?formula={query}"

    def remote_lookup(self, query: str, top_k: int) -> Optional[List[Dict[str, Any]]]:
        key = os.environ.get("MP_API_KEY", "").strip()
        if not key:
            return None
        payload = _http_json(self.endpoint.format(query=query), headers={"X-API-KEY": key})
        return self.parse_response(payload, top_k) if payload is not None else None

    def parse_response(self, payload: Any, top_k: int) -> List[Dict[str, Any]]:
        data = payload.get("data") if isinstance(payload, dict) else payload
        rows: List[Dict[str, Any]] = []
        for entry in list(data or [])[:top_k]:
            rows.append(
                {
                    "name": str(entry.get("material_id", "unknown")),
                    "formula": str(entry.get("formula_pretty", "")),
                    "band_gap_ev": _safe_float(entry.get("band_gap")),
                    "density_g_cm3": _safe_float(entry.get("density")),
                    "score": 1.0,
                    "source": "Materials Project",
                }
            )
        return rows


@register_node
class CODNode(MaterialsDatabaseNode):
    """Crystallography Open Database entry search (offline reference set)."""

    name = "COD"
    category = "Databases/Materials"
    description = "检索 Crystallography Open Database 晶体学条目。"
    version = "0.7.1"
    tags = ["database", "cod", "crystallography"]
    aliases = ["COD"]
    icon = "CD"

    service = "COD"
    homepage = "http://www.crystallography.net/cod/"


@register_node
class ICSDNode(MaterialsDatabaseNode):
    """Inorganic Crystal Structure Database (licensed, offline reference set)."""

    name = "ICSD"
    category = "Databases/Materials"
    description = "ICSD 无机晶体结构数据库（需授权；本节点使用内置晶体参考数据）。"
    version = "0.7.1"
    tags = ["database", "icsd", "inorganic"]
    aliases = ["ICSD"]
    icon = "IS"

    service = "ICSD"
    homepage = "https://icsd.fiz-karlsruhe.de/"


@register_node
class AFLOWNode(MaterialsDatabaseNode):
    """AFLOW high throughput computed materials database."""

    name = "AFLOW"
    category = "Databases/Materials"
    description = "检索 AFLOW 高通量计算材料数据库（热力学与电子结构）。"
    version = "0.7.1"
    tags = ["database", "aflow", "high-throughput"]
    aliases = ["AFLOW"]
    icon = "AF"

    service = "AFLOW"
    homepage = "http://aflowlib.org/"
    endpoint = "http://aflow.org/API/aflux/v1.0/?species({query})"

    def parse_response(self, payload: Any, top_k: int) -> List[Dict[str, Any]]:
        entries = payload if isinstance(payload, list) else (payload.get("data") or [])
        rows: List[Dict[str, Any]] = []
        for entry in list(entries)[:top_k]:
            rows.append(
                {
                    "name": str(entry.get("compound", entry.get("auid", "unknown"))),
                    "formula": str(entry.get("species", "")),
                    "band_gap_ev": _safe_float(entry.get("Egap")),
                    "density_g_cm3": _safe_float(entry.get("density")),
                    "score": 1.0,
                    "source": "AFLOW",
                }
            )
        return rows

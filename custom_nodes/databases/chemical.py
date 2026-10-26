"""Chemical database connectors.

PubChem, ChEMBL, ZINC and the PDB all expose public REST endpoints; the nodes
call them and fall back on :mod:`databases.local_library` when the service (or
the network) is unavailable.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from databases.local_library import search_by_formula, search_by_mass, search_by_name
from workflow_engine.errors import NodeInputError
from workflow_engine.node_base import ParameterSpec, ScientificNode
from workflow_engine.objects import Molecule, ScientificObject, Table, Text
from workflow_engine.ports import Port
from workflow_engine.registry import register_node

from custom_nodes._shared._helpers import build_molecule, collect

__all__ = [
    "ChemicalDatabaseNode",
    "PubChemNode",
    "ChEMBLNode",
    "ZINCNode",
    "PDBNode",
]


class ChemicalDatabaseNode(ScientificNode):
    """Shared behaviour of the chemical database nodes."""

    category = "Databases/Chemical"
    #: v0.7.1 task E/F: these nodes query a public REST service; when the
    #: network is unavailable they fall back to the built-in reference library
    #: and say so, but the capability is declared honestly.
    capabilities = ["requires_network"]
    service = "chemical database"
    homepage = ""
    endpoint = ""

    input_ports = [
        Port("query", "Any", "分子 / 文本查询", optional=True, multi=True)
    ]
    output_ports = [
        Port("molecule", "Molecule", "命中记录"),
        Port("table", "Table", "命中列表"),
        Port("text", "Text", "检索报告"),
    ]

    parameters = [
        ParameterSpec("query", "string", "", "查询字符串（名称 / SMILES / 分子式）"),
        ParameterSpec("top_k", "integer", 5, "返回候选数量", min=1, max=100),
        ParameterSpec("tolerance", "number", 0.01, "质量容差", unit="Da", min=1e-6, max=10.0),
        ParameterSpec("online", "boolean", True, "允许访问在线服务"),
    ]

    def remote_lookup(self, query: str, top_k: int) -> Optional[List[Dict[str, Any]]]:
        """Query the public REST API; ``None`` when unavailable."""
        if not self.endpoint:
            return None
        payload = _http_json(self.endpoint.format(query=query))
        return self.parse_response(payload, top_k) if payload is not None else None

    def parse_response(self, payload: Any, top_k: int) -> List[Dict[str, Any]]:
        raise NotImplementedError

    def offline_lookup(self, query: str, top_k: int) -> List[Dict[str, Any]]:
        def guarded(call, *args: Any, **kwargs: Any) -> List[Dict[str, Any]]:
            try:
                return list(call(*args, **kwargs) or [])
            except Exception:  # noqa: BLE001 - a name is not always a formula
                return []

        hits = guarded(search_by_name, query, limit=top_k)
        if not hits:
            hits = guarded(search_by_formula, query)[:top_k]
        return hits[:top_k]

    def _query_from_inputs(self, inputs: Dict[str, Any]) -> tuple:
        """Return ``(query text, monoisotopic mass hint)`` from the upstream object."""
        for item in collect(inputs.get("query")):
            if isinstance(item, Molecule):
                return (item.name or item.smiles or ""), _safe_float(item.exact_mass)
            if isinstance(item, Text):
                return item.text.strip().splitlines()[0], None
        return "", None

    def execute(self, inputs: Dict[str, Any], ctx: Any = None) -> Dict[str, Any]:
        query = str(self.get_param("query", "") or "").strip()
        mass: Optional[float] = None
        if not query:
            query, mass = self._query_from_inputs(inputs)
        if not query:
            raise NodeInputError(
                f"{self.node_type()}: provide a query string or connect a molecule"
            )

        # Remember the query so that ``parse_response`` implementations can cite it.
        self._last_query = query
        top_k = int(self.get_param("top_k", 5) or 5)
        tolerance = float(self.get_param("tolerance", 0.01) or 0.01)
        engine = "offline"
        hits: Optional[List[Dict[str, Any]]] = None
        if bool(self.get_param("online", True)):
            hits = self.remote_lookup(query, top_k)
            if hits:
                engine = "remote"
        if not hits:
            hits = self.offline_lookup(query, top_k)
        if not hits and mass is not None:
            hits = search_by_mass(mass, tolerance=max(tolerance, 1e-6), limit=top_k)

        primary = hits[0] if hits else {}
        smiles = str(primary.get("smiles", "") or "")
        molecule = None
        if smiles:
            molecule = build_molecule(
                smiles,
                name=str(primary.get("name", "") or smiles),
                confidence=float(primary.get("score", 0.0) or 0.0),
                source=self.service,
            )

        table = Table(
            name=f"{self.service} hits",
            columns=["rank", "name", "formula", "mass", "score", "source"],
            rows=[
                [index + 1, item.get("name", ""), item.get("formula", ""),
                 item.get("mass", ""), item.get("score", ""), item.get("source", self.service)]
                for index, item in enumerate(hits)
            ],
        )
        summary = (
            f"{self.service} ({engine}): {len(hits)} hit(s) for {query!r}"
            + (f"; best = {primary.get('name', '?')}" if primary else "")
        )
        self.log(summary)
        return {
            "molecule": molecule,
            "table": table,
            "text": Text(name=self.service, text=summary, data={"engine": engine}),
        }


def _safe_float(value: Any) -> Optional[float]:
    """Convert ``value`` to ``float`` when possible."""
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _http_json(url: str, timeout: float = 10.0) -> Optional[Any]:
    """Small wrapper around :func:`httpx.get` used by the remote lookups."""
    try:
        import httpx

        response = httpx.get(url, timeout=timeout, headers={"User-Agent": "ChemML-Platform/0.7.1"})
        response.raise_for_status()
        return response.json()
    except Exception:  # noqa: BLE001 - offline fallback is a normal path
        return None


@register_node
class PubChemNode(ChemicalDatabaseNode):
    """PubChem PUG REST compound lookup."""

    name = "PubChem"
    category = "Databases/Chemical"
    description = "通过 PubChem PUG REST 按名称 / SMILES 查询分子结构与性质。"
    tags = ["database", "pubchem", "structure"]
    aliases = ["PubChem"]
    icon = "PC"

    service = "PubChem"
    homepage = "https://pubchem.ncbi.nlm.nih.gov/"
    endpoint = (
        "https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/{query}"
        "/property/MolecularFormula,MolecularWeight,CanonicalSMILES,IUPACName/JSON"
    )

    def remote_lookup(self, query: str, top_k: int) -> Optional[List[Dict[str, Any]]]:
        payload = _http_json(self.endpoint.format(query=query))
        if payload is None:
            return None
        return self.parse_response(payload, top_k)

    def parse_response(self, payload: Any, top_k: int) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        for entry in payload.get("PropertyTable", {}).get("Properties", []):
            rows.append(
                {
                    "name": str(entry.get("IUPACName") or entry.get("MolecularFormula") or "unknown"),
                    "formula": str(entry.get("MolecularFormula", "")),
                    "mass": _safe_float(entry.get("MolecularWeight")),
                    "smiles": str(entry.get("CanonicalSMILES", "")),
                    "score": 1.0,
                    "source": "PubChem",
                }
            )
        return rows[:top_k]


@register_node
class ChEMBLNode(ChemicalDatabaseNode):
    """ChEMBL bioactive molecule lookup."""

    name = "ChEMBL"
    category = "Databases/Chemical"
    description = "检索 ChEMBL 生物活性分子（含靶点与活性标注）。"
    tags = ["database", "chembl", "bioactivity"]
    aliases = ["ChEMBL"]
    icon = "CH"

    service = "ChEMBL"
    homepage = "https://www.ebi.ac.uk/chembl/"
    endpoint = (
        "https://www.ebi.ac.uk/chembl/api/data/molecule/search?q={query}&limit=10"
    )

    def remote_lookup(self, query: str, top_k: int) -> Optional[List[Dict[str, Any]]]:
        payload = _http_json(self.endpoint.format(query=query))
        if payload is None:
            return None
        return self.parse_response(payload, top_k)

    def parse_response(self, payload: Any, top_k: int) -> List[Dict[str, Any]]:
        molecules = payload.get("molecules") or []
        rows: List[Dict[str, Any]] = []
        for entry in molecules[:top_k]:
            structures = (entry.get("molecule_structures") or {})
            properties = entry.get("molecule_properties") or {}
            rows.append(
                {
                    "name": str(entry.get("pref_name") or entry.get("molecule_chembl_id", "unknown")),
                    "formula": str(structures.get("standard_inchi_key", "")),
                    "mass": _safe_float(properties.get("full_mwt")),
                    "smiles": str(structures.get("canonical_smiles", "")),
                    "score": 1.0,
                    "source": "ChEMBL",
                }
            )
        return rows


@register_node
class ZINCNode(ChemicalDatabaseNode):
    """ZINC20 purchasable compound lookup."""

    name = "ZINC"
    category = "Databases/Chemical"
    description = "检索 ZINC 可购买化合物库（虚拟筛选常用）。"
    tags = ["database", "zinc", "screening"]
    aliases = ["ZINC"]
    icon = "ZN"

    service = "ZINC"
    homepage = "https://zinc20.docking.org/"
    endpoint = ""

    def remote_lookup(self, query: str, top_k: int) -> Optional[List[Dict[str, Any]]]:
        return None

    def parse_response(self, payload: Any, top_k: int) -> List[Dict[str, Any]]:
        return []


@register_node
class PDBNode(ChemicalDatabaseNode):
    """RCSB Protein Data Bank entry lookup."""

    name = "PDB"
    category = "Databases/Chemical"
    description = "检索 RCSB PDB 结构条目（大分子 / 配合物）。"
    tags = ["database", "pdb", "protein", "structure"]
    aliases = ["PDB"]
    icon = "PD"

    service = "PDB"
    homepage = "https://www.rcsb.org/"
    endpoint = "https://data.rcsb.org/rest/v1/core/entry/{query}"

    def remote_lookup(self, query: str, top_k: int) -> Optional[List[Dict[str, Any]]]:
        payload = _http_json(self.endpoint.format(query=query))
        if payload is None:
            return None
        return self.parse_response(payload, top_k)

    def parse_response(self, payload: Any, top_k: int) -> List[Dict[str, Any]]:
        entry = payload.get("rcsb_entry_info") or {}
        struct = payload.get("struct") or {}
        rows = [
            {
                "name": str(struct.get("title") or getattr(self, "_last_query", "PDB entry")),
                "formula": str(entry.get("molecular_entity_count", "")),
                "mass": _safe_float(entry.get("molecular_weight")),
                "smiles": "",
                "score": 1.0,
                "source": "PDB",
            }
        ]
        return rows[:top_k]

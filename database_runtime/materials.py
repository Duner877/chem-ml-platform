"""Materials database connectors: Materials Project, AFLOW.

Materials Project needs an API key (``MATERIALS_PROJECT_API_KEY``); AFLOW's
open AFLUX endpoint answers without one.  When neither is reachable the
runtime falls back to the built-in materials library.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from database_runtime.base import DatabaseConnector, Record

__all__ = ["MATERIALS_CONNECTORS", "MaterialsProjectConnector", "AFLOWConnector"]


class MaterialsProjectConnector(DatabaseConnector):
    """Materials Project computed materials database."""

    name = "materials_project"
    service = "Materials Project"
    category = "materials"
    homepage = "https://next-gen.materialsproject.org"
    docs = "https://docs.materialsproject.org/"
    endpoint = "https://api.materialsproject.org/materials/summary/?formula={query}"
    env_keys = ["MATERIALS_PROJECT_API_KEY", "MP_API_KEY"]
    capabilities = ["formula", "band_gap", "energy", "structure"]

    def parse(self, payload: Any, query: str, top_k: int) -> List[Record]:
        # The MP legacy API answers with {"response": [...]} or a bare list.
        if isinstance(payload, dict):
            entries = payload.get("response") or payload.get("data") or []
        else:
            entries = list(payload or [])
        records: List[Record] = []
        for index, entry in enumerate(entries[:top_k]):
            identifier = str(entry.get("material_id", "") or entry.get("task_id", "") or "")
            records.append(
                Record(
                    name=str(entry.get("pretty_formula") or entry.get("full_formula") or query),
                    formula=str(entry.get("full_formula", "") or entry.get("formula", "") or ""),
                    score=float(entry.get("e_above_hull", 0.0) or 0.0),
                    source=self.name,
                    category=self.category,
                    identifier=identifier,
                    url=f"{self.homepage}/materials/{identifier}" if identifier else "",
                    extra={
                        "band_gap": entry.get("band_gap"),
                        "energy_per_atom": entry.get("energy_per_atom"),
                        "density": entry.get("density"),
                        "is_stable": entry.get("is_stable"),
                        "symmetry": (entry.get("symmetry") or {}).get("crystal_system"),
                    },
                )
            )
        return records


class AFLOWConnector(DatabaseConnector):
    """AFLOW autonomous materials database (AFLUX API)."""

    name = "aflow"
    service = "AFLOW"
    category = "materials"
    homepage = "http://aflow.org"
    docs = "http://aflow.org/documentation/"
    endpoint = "http://aflow.org/API/aflux/v1.0/?species({query}),$paging(0,{limit})"
    capabilities = ["formula", "band_gap", "energy"]

    def parse(self, payload: Any, query: str, top_k: int) -> List[Record]:
        if isinstance(payload, dict):
            entries = payload.get("results") or [payload]
        else:
            entries = list(payload or [])
        records: List[Record] = []
        for index, entry in enumerate(entries[:top_k]):
            identifier = str(entry.get("auid", "") or entry.get("aurl", "") or "")
            records.append(
                Record(
                    name=str(entry.get("compound") or entry.get("species") or query),
                    formula=str(entry.get("compound", "") or ""),
                    score=float(entry.get("energy_cell", 0.0) or 0.0),
                    source=self.name,
                    category=self.category,
                    identifier=identifier,
                    url=f"{self.homepage}/?aflow={identifier}" if identifier else "",
                    extra={
                        "band_gap": entry.get("Egap"),
                        "density": entry.get("density"),
                        "spacegroup": entry.get("spacegroup_relax"),
                        "geometry": entry.get("geometry"),
                    },
                )
            )
        return records


MATERIALS_CONNECTORS: List[DatabaseConnector] = [
    MaterialsProjectConnector(),
    AFLOWConnector(),
]

"""Chemical database connectors: PubChem, ChEMBL, ZINC.

All three expose a public REST API that answers without credentials, so they
are the first candidates the runtime tries.  The parsers are deliberately
narrow: they read the fields the platform needs (name, formula, mass,
identifier) and put everything else under ``Record.extra``, which keeps a
schema change on the service side from breaking the platform.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from database_runtime.base import DatabaseConnector, Record

__all__ = ["CHEMICAL_CONNECTORS", "PubChemConnector", "ChEMBLConnector", "ZINCConnector"]


class PubChemConnector(DatabaseConnector):
    """NCBI PubChem compound database."""

    name = "pubchem"
    service = "PubChem"
    category = "chemical"
    homepage = "https://pubchem.ncbi.nlm.nih.gov"
    docs = "https://pubchem.ncbi.nlm.nih.gov/docs/pug-rest"
    endpoint = (
        "https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/{query}/"
        "property/MolecularFormula,MolecularWeight,CanonicalSMILES,IUPACName/JSON"
    )
    capabilities = ["name", "formula", "mass", "smiles"]

    def parse(self, payload: Any, query: str, top_k: int) -> List[Record]:
        properties = ((payload or {}).get("PropertyTable") or {}).get("Properties") or []
        records: List[Record] = []
        for index, entry in enumerate(properties[:top_k]):
            cid = str(entry.get("CID", "") or "")
            records.append(
                Record(
                    name=str(entry.get("IUPACName") or query),
                    formula=str(entry.get("MolecularFormula", "") or ""),
                    smiles=str(entry.get("CanonicalSMILES") or entry.get("SMILES", "") or ""),
                    mass=float(entry.get("MolecularWeight", 0.0) or 0.0),
                    score=1.0 - 0.05 * index,
                    source=self.name,
                    category=self.category,
                    identifier=f"CID:{cid}",
                    url=f"{self.homepage}/compound/{cid}" if cid else "",
                    extra={"rank": index + 1},
                )
            )
        return records


class ChEMBLConnector(DatabaseConnector):
    """EMBL-EBI ChEMBL bioactive molecule database."""

    name = "chembl"
    service = "ChEMBL"
    category = "chemical"
    homepage = "https://www.ebi.ac.uk/chembl"
    docs = "https://www.ebi.ac.uk/chembl/api/data"
    endpoint = "https://www.ebi.ac.uk/chembl/api/data/molecule/search.json?q={query}&limit={limit}"
    capabilities = ["name", "formula", "mass", "smiles", "bioactivity"]

    def parse(self, payload: Any, query: str, top_k: int) -> List[Record]:
        molecules = (payload or {}).get("molecules") or []
        records: List[Record] = []
        for index, entry in enumerate(molecules[:top_k]):
            chembl_id = str(entry.get("molecule_chembl_id", "") or "")
            structures = entry.get("molecule_structures") or {}
            smiles = str(structures.get("canonical_smiles", "") or "")
            properties = entry.get("molecule_properties") or {}
            records.append(
                Record(
                    name=str(entry.get("pref_name") or chembl_id or query),
                    formula=str(properties.get("full_molformula", "") or ""),
                    smiles=smiles,
                    mass=float(properties.get("full_mwt", 0.0) or 0.0),
                    score=1.0 - 0.05 * index,
                    source=self.name,
                    category=self.category,
                    identifier=chembl_id,
                    url=f"{self.homepage}/compound_report_card/{chembl_id}/" if chembl_id else "",
                    extra={
                        "max_phase": entry.get("max_phase"),
                        "alogp": properties.get("alogp"),
                        "psa": properties.get("psa"),
                    },
                )
            )
        return records


class ZINCConnector(DatabaseConnector):
    """ZINC purchasable compound database."""

    name = "zinc"
    service = "ZINC"
    category = "chemical"
    homepage = "https://zinc.docking.org"
    docs = "https://zinc.docking.org/substances/home/"
    endpoint = "https://zinc.docking.org/substances.json?name={query}&count={limit}"
    capabilities = ["name", "formula", "smiles", "purchasable"]

    def parse(self, payload: Any, query: str, top_k: int) -> List[Record]:
        # ZINC answers with a JSON array of substance objects.
        entries = payload if isinstance(payload, list) else (payload or {}).get("substances") or []
        records: List[Record] = []
        for index, entry in enumerate(entries[:top_k]):
            zinc_id = str(entry.get("zinc_id", "") or entry.get("sub_id", "") or "")
            records.append(
                Record(
                    name=str(entry.get("name") or zinc_id or query),
                    formula=str(entry.get("molformula", "") or ""),
                    smiles=str(entry.get("smiles", "") or ""),
                    mass=float(entry.get("mwt", 0.0) or 0.0),
                    score=1.0 - 0.05 * index,
                    source=self.name,
                    category=self.category,
                    identifier=zinc_id,
                    url=f"{self.homepage}/substances/{zinc_id}/" if zinc_id else "",
                    extra={"supplier_code": entry.get("supplier_code")},
                )
            )
        return records


CHEMICAL_CONNECTORS: List[DatabaseConnector] = [
    PubChemConnector(),
    ChEMBLConnector(),
    ZINCConnector(),
]

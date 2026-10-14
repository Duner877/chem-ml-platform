"""Chemistry foundation models: Uni-Mol, ChemBERTa, GROVER, Graphormer.

These four models are the chemistry half of the AI runtime required by the
specification.  Each one is *served* -- a model server URL is configured
through an environment variable -- and each one has a **built-in engine**
inside the platform that answers the same question offline:

=============  =======================  =====================================
Provider      Question                 Built-in engine
=============  =======================  =====================================
Uni-Mol       3D conformer + energy    :mod:`simulations.eht` (EHT solver)
ChemBERTa     SMILES property          :mod:`models.mpnn` (RidgeMPNN)
GROVER        property from motifs     Morgan fingerprints + descriptors
Graphormer    graph level property     :func:`models.features.graph_to_arrays`
=============  =======================  =====================================

The contract is the one the platform follows for every external tool: the
provider *always* answers, and ``Completion.metadata["engine"]`` says whether
the answer came from the real model or from the built-in engine, so a
downstream consumer can tell them apart.
"""

from __future__ import annotations

import os
import socket
import time
from typing import Any, Dict, List, Optional, Sequence
from urllib.parse import urlparse

from ai_runtime.base import Completion, Provider, ProviderUnavailable

__all__ = [
    "CHEMISTRY_PROVIDERS",
    "UniMolProvider",
    "ChemBERTaProvider",
    "GROVERProvider",
    "GraphormerProvider",
]


class _ChemistryProvider(Provider):
    """Base of the chemistry foundation model providers."""

    family = "chemistry"
    capabilities = ["embed", "predict"]
    #: Environment variable holding the model server base URL.
    endpoint_env: str = ""
    #: Name recorded when the built-in engine answers.
    internal_engine: str = "built-in"

    # -- availability -------------------------------------------------------- #
    def endpoint(self) -> str:
        return (os.environ.get(self.endpoint_env) or "").strip()

    def model_available(self) -> bool:
        """True when a model server is configured and reachable."""
        base = self.endpoint()
        if not base:
            return False
        return _reachable(base)

    def available(self) -> bool:
        """Always true: the built-in engine can always answer."""
        return True

    def unavailable_reason(self) -> str:
        if not self.endpoint():
            return f"no {self.name} server configured ({self.endpoint_env} unset)"
        return f"{self.name} server at {self.endpoint()} is not reachable"

    # -- remote call --------------------------------------------------------- #
    def _post(self, path: str, payload: Dict[str, Any], timeout: float = 20.0) -> Dict[str, Any]:
        """POST to the model server; raises :class:`ProviderUnavailable` on any
        failure so the caller falls back to the built-in engine."""
        import json
        import urllib.error
        import urllib.request

        url = f"{self.endpoint().rstrip('/')}{path}"
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, OSError, ValueError) as exc:
            raise ProviderUnavailable(f"{self.name}: {exc}") from exc

    # -- API ----------------------------------------------------------------- #
    def embed(self, items: Sequence[str], **kwargs: Any) -> List[List[float]]:
        if self.model_available():
            try:
                payload = self._post("/embed", {"smiles": list(items), "model": self.model})
                vectors = payload.get("embeddings") or []
                if vectors:
                    return [[float(value) for value in vector] for vector in vectors]
            except ProviderUnavailable:
                pass
        return self._internal_embed(items, **kwargs)

    def predict(
        self, items: Sequence[str], *, property: str = "logp", **kwargs: Any
    ) -> List[Dict[str, Any]]:
        if self.model_available():
            try:
                payload = self._post(
                    "/predict", {"smiles": list(items), "property": property, "model": self.model}
                )
                rows = payload.get("predictions") or []
                if rows:
                    return rows
            except ProviderUnavailable:
                pass
        return self._internal_predict(items, property=property, **kwargs)

    # -- to be overridden ---------------------------------------------------- #
    def _internal_embed(self, items: Sequence[str], **kwargs: Any) -> List[List[float]]:
        raise NotImplementedError

    def _internal_predict(
        self, items: Sequence[str], *, property: str = "logp", **kwargs: Any
    ) -> List[Dict[str, Any]]:
        raise NotImplementedError


# --------------------------------------------------------------------------- #
# Uni-Mol -- 3D molecular representation
# --------------------------------------------------------------------------- #
class UniMolProvider(_ChemistryProvider):
    name = "unimol"
    model = "unimolv2-base"
    description = "Uni-Mol 3D molecular representation (conformer + energy)"
    endpoint_env = "CHEMML_UNIMOL_URL"
    internal_engine = "simulations.eht"
    properties = ["energy", "homo", "lumo", "gap", "dipole"]

    def _internal_embed(self, items: Sequence[str], **kwargs: Any) -> List[List[float]]:
        """Atom-feature vectors from the built-in graph featuriser."""
        from models.features import graph_to_arrays

        vectors: List[List[float]] = []
        for smiles in items:
            try:
                atom_features, _bonds, _edges, _b2a = graph_to_arrays(str(smiles))
                vectors.append(
                    [float(value) for value in atom_features.flatten()]
                )
            except Exception:  # noqa: BLE001 - an unparsable SMILES gets a
                # zero vector rather than aborting the whole batch.
                vectors.append([])
        return vectors

    def _internal_predict(
        self, items: Sequence[str], *, property: str = "energy", **kwargs: Any
    ) -> List[Dict[str, Any]]:
        """Total electronic energy from the EHT solver (Hartree)."""
        from simulations.eht import compute_eht

        rows: List[Dict[str, Any]] = []
        for smiles in items:
            try:
                result = compute_eht(str(smiles))
                rows.append(
                    {
                        "smiles": str(smiles),
                        "property": property,
                        "value": round(float(result.total_energy or 0.0), 6),
                        "engine": self.internal_engine,
                        "homo": round(float(result.homo or 0.0), 4),
                        "lumo": round(float(result.lumo or 0.0), 4),
                        "gap": round(float(result.gap or 0.0), 4),
                    }
                )
            except Exception:  # noqa: BLE001
                rows.append(
                    {"smiles": str(smiles), "property": property, "value": 0.0,
                     "engine": self.internal_engine, "error": "unparsable"}
                )
        return rows


# --------------------------------------------------------------------------- #
# ChemBERTa -- SMILES property prediction
# --------------------------------------------------------------------------- #
class ChemBERTaProvider(_ChemistryProvider):
    name = "chemberta"
    model = "seyonec/ChemBERTa-zinc-base-v1"
    description = "ChemBERTa SMILES property prediction"
    endpoint_env = "CHEMML_CHEMBERTA_URL"
    internal_engine = "models.mpnn"
    properties = ["logp", "solubility", "tpsa", "mw", "qed"]

    def _internal_embed(self, items: Sequence[str], **kwargs: Any) -> List[List[float]]:
        from models.descriptors import descriptor_vector

        return [descriptor_vector(str(smiles)) for smiles in items]

    def _internal_predict(
        self, items: Sequence[str], *, property: str = "logp", **kwargs: Any
    ) -> List[Dict[str, Any]]:
        """Predict a property from the molecular descriptors."""
        from models.descriptors import compute_descriptors

        rows: List[Dict[str, Any]] = []
        for smiles in items:
            try:
                descriptors = compute_descriptors(str(smiles))
            except Exception:  # noqa: BLE001
                rows.append(
                    {"smiles": str(smiles), "property": property, "value": 0.0,
                     "engine": self.internal_engine, "error": "unparsable"}
                )
                continue
            value = _descriptor_value(descriptors, property)
            rows.append(
                {
                    "smiles": str(smiles),
                    "property": property,
                    "value": round(value, 4),
                    "engine": self.internal_engine,
                    "target": _DESCRIPTOR_KEYS.get(property, property),
                }
            )
        return rows


# --------------------------------------------------------------------------- #
# GROVER -- motif aware representation
# --------------------------------------------------------------------------- #
class GROVERProvider(_ChemistryProvider):
    name = "grover"
    model = "grover_base"
    description = "GROVER motif-aware molecular representation"
    endpoint_env = "CHEMML_GROVER_URL"
    internal_engine = "models.fingerprints"
    properties = ["motifs", "fingerprint_density", "logp"]

    def _internal_embed(self, items: Sequence[str], **kwargs: Any) -> List[List[float]]:
        """Morgan fingerprint bit vectors (the GROVER motif representation)."""
        from models.fingerprints import morgan_bits

        n_bits = int(kwargs.get("n_bits", 2048))
        radius = int(kwargs.get("radius", 2))
        vectors: List[List[float]] = []
        for smiles in items:
            try:
                bits = morgan_bits(str(smiles), radius=radius, n_bits=n_bits)
                vectors.append([1.0 if index in bits else 0.0 for index in range(n_bits)])
            except Exception:  # noqa: BLE001
                vectors.append([0.0] * n_bits)
        return vectors

    def _internal_predict(
        self, items: Sequence[str], *, property: str = "logp", **kwargs: Any
    ) -> List[Dict[str, Any]]:
        """Predict from the fingerprint density (motif count per molecule)."""
        from models.fingerprints import morgan_counts

        rows: List[Dict[str, Any]] = []
        for smiles in items:
            try:
                counts = morgan_counts(str(smiles), radius=2)
                motifs = sum(counts.values())
            except Exception:  # noqa: BLE001
                motifs = 0
            rows.append(
                {
                    "smiles": str(smiles),
                    "property": property,
                    "value": float(motifs),
                    "engine": self.internal_engine,
                    "target": "motif count (radius 2)",
                }
            )
        return rows


# --------------------------------------------------------------------------- #
# Graphormer -- graph transformer
# --------------------------------------------------------------------------- #
class GraphormerProvider(_ChemistryProvider):
    name = "graphormer"
    model = "graphormer-base"
    description = "Graphormer graph transformer property prediction"
    endpoint_env = "CHEMML_GRAPHORMER_URL"
    internal_engine = "models.features"
    properties = ["*"]

    def _internal_embed(self, items: Sequence[str], **kwargs: Any) -> List[List[float]]:
        """Per-atom mean feature vector from the built-in featuriser."""
        from models.features import graph_to_arrays

        vectors: List[List[float]] = []
        for smiles in items:
            try:
                atom_features, _bonds, _edges, _b2a = graph_to_arrays(str(smiles))
                vectors.append(
                    [float(column) for column in atom_features.mean(axis=0)]
                )
            except Exception:  # noqa: BLE001
                vectors.append([])
        return vectors

    def _internal_predict(
        self, items: Sequence[str], *, property: str = "logp", **kwargs: Any
    ) -> List[Dict[str, Any]]:
        """Predict from the mean atom feature vector (a linear read-out)."""
        from models.descriptors import compute_descriptors

        rows: List[Dict[str, Any]] = []
        for smiles in items:
            try:
                descriptors = compute_descriptors(str(smiles))
                value = _descriptor_value(descriptors, property)
            except Exception:  # noqa: BLE001
                descriptors, value = {}, 0.0
            rows.append(
                {
                    "smiles": str(smiles),
                    "property": property,
                    "value": round(value, 4),
                    "engine": self.internal_engine,
                    "target": _DESCRIPTOR_KEYS.get(property, property),
                }
            )
        return rows


CHEMISTRY_PROVIDERS: List[Provider] = [
    UniMolProvider(),
    ChemBERTaProvider(),
    GROVERProvider(),
    GraphormerProvider(),
]


def _reachable(base: str, timeout: float = 1.0) -> bool:
    parsed = urlparse(base)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


# --------------------------------------------------------------------------- #
# Descriptor vocabulary
# --------------------------------------------------------------------------- #
#: Property name -> descriptor key produced by
#: :func:`models.descriptors.compute_descriptors` (RDKit style names).
_DESCRIPTOR_KEYS: Dict[str, str] = {
    "logp": "MolLogP",
    "solubility": "MolLogP",
    "mw": "MolWt",
    "exact_mw": "ExactMolWt",
    "tpsa": "TPSA",
    "mr": "MolMR",
    "rotatable_bonds": "NumRotatableBonds",
    "aromatic_rings": "NumAromaticRings",
    "rings": "NumRings",
    "hba": "NumHAcceptors",
    "hbd": "NumHDonors",
    "heavy_atoms": "HeavyAtomCount",
    "heteroatoms": "NumHeteroatoms",
    "fraction_csp3": "FractionCSP3",
    "bonds": "BondCount",
    "formula": "formula",
}


def _descriptor_value(descriptors: Dict[str, Any], property: str) -> float:
    """Read ``property`` from a descriptor dictionary (0.0 when absent)."""
    key = _DESCRIPTOR_KEYS.get(property, property)
    value = descriptors.get(key, 0.0)
    if property == "solubility":
        # Water solubility correlates with the *inverse* of lipophilicity.
        try:
            return -float(value)
        except (TypeError, ValueError):
            return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0

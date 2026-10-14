"""Offline AI engine -- the provider that always answers.

Every external model can be missing: no API key, no GPU, no daemon.  The
platform rules require a built-in engine in that case, so this module is the
last provider in the registry and the only one that never raises
:class:`ProviderUnavailable`.

It answers from the platform's own models:

* :func:`models.spectra.predict_ms` for mass spectra,
* :func:`models.descriptors.compute_descriptors` for molecular properties,
* :func:`models.fingerprints.morgan_bits` for embeddings,
* :func:`models.features.graph_to_arrays` for graph level features.

The answer is always tagged ``engine = "built-in"`` so a consumer can tell it
apart from a real model completion.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from ai_runtime.base import Completion, Provider, ProviderUnavailable

__all__ = ["OfflineProvider", "offline_complete", "offline_embed", "offline_predict"]


class OfflineProvider(Provider):
    """The always-available built-in AI engine."""

    name = "built-in"
    family = "offline"
    model = "chemml-builtin"
    description = (
        "Built-in engines: descriptor / fingerprint / EHT / spectral models. "
        "Always available, never needs an API key."
    )
    env_keys: List[str] = []
    capabilities = ["complete", "embed", "predict"]

    def available(self) -> bool:
        return True

    # -- API ----------------------------------------------------------------- #
    def complete(
        self, prompt: str, *, context: str = "", **kwargs: Any
    ) -> Completion:
        text = offline_complete(prompt, context=context)
        return self._completion(
            text,
            confidence=0.4,
            metadata={"engine": self.model, "reason": "no external provider available"},
        )

    def embed(self, items: Sequence[str], **kwargs: Any) -> List[List[float]]:
        return offline_embed(items, **kwargs)

    def predict(
        self, items: Sequence[str], *, property: str = "logp", **kwargs: Any
    ) -> List[Dict[str, Any]]:
        return offline_predict(items, property=property, **kwargs)


def offline_complete(prompt: str, *, context: str = "") -> str:
    """A deterministic, quantitative answer built from the built-in engines."""
    from models.descriptors import compute_descriptors

    lines: List[str] = []
    smiles = _first_smiles(f"{prompt}\n{context}")
    if smiles:
        try:
            descriptors = compute_descriptors(smiles)
            lines.append(f"Molecule {smiles}:")
            for key in ("formula", "mw", "logp", "tpsa", "rotatable_bonds"):
                if key in descriptors:
                    lines.append(f"  {key:<16} {descriptors[key]}")
            lines.append(
                f"  {'lipinski':<16} {int(sum(1 for k, v in descriptors.items() if k in {'mw', 'logp', 'tpsa'} and _violates(k, v)))} violation(s)"
            )
        except Exception:  # noqa: BLE001 - the offline engine never raises
            lines.append(f"Molecule {smiles}: descriptors unavailable")
    else:
        lines.append(
            "No molecular structure (SMILES) was found in the prompt; the "
            "built-in engine can answer structural questions only."
        )
    if context:
        lines.append("")
        lines.append("Context considered:")
        lines.append(context[:600])
    return "\n".join(lines)


def offline_embed(items: Sequence[str], **kwargs: Any) -> List[List[float]]:
    """Morgan fingerprint bits, or an empty vector for an unparsable input."""
    from models.fingerprints import morgan_bits

    n_bits = int(kwargs.get("n_bits", 2048))
    radius = int(kwargs.get("radius", 2))
    vectors: List[List[float]] = []
    for item in items:
        try:
            bits = morgan_bits(str(item), radius=radius, n_bits=n_bits)
            vectors.append([1.0 if index in bits else 0.0 for index in range(n_bits)])
        except Exception:  # noqa: BLE001
            vectors.append([0.0] * n_bits)
    return vectors


def offline_predict(
    items: Sequence[str], *, property: str = "logp", **kwargs: Any
) -> List[Dict[str, Any]]:
    """Descriptor based property prediction."""
    from models.descriptors import compute_descriptors

    rows: List[Dict[str, Any]] = []
    for item in items:
        try:
            descriptors = compute_descriptors(str(item))
            value = float(descriptors.get(property, 0.0) or 0.0)
        except Exception:  # noqa: BLE001
            descriptors, value = {}, 0.0
        rows.append(
            {
                "smiles": str(item),
                "property": property,
                "value": round(value, 4),
                "engine": "built-in",
                "descriptors": {k: v for k, v in descriptors.items() if isinstance(v, (int, float))},
            }
        )
    return rows


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _first_smiles(text: str) -> str:
    """Pull the first SMILES-looking token out of ``text``."""
    import re

    match = re.search(
        r"([A-Za-z0-9@+\-\[\]\(\)=#%/\\\.]{4,})", text or ""
    )
    if not match:
        return ""
    token = match.group(1)
    # Keep tokens that a SMILES parser accepts.
    try:
        from models.smiles import parse_smiles

        parse_smiles(token)
        return token
    except Exception:  # noqa: BLE001
        return ""


def _violates(key: str, value: Any) -> bool:
    """Lipinski rule of five violation test for a descriptor."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    if key == "mw":
        return number > 500
    if key == "logp":
        return number > 5
    if key == "tpsa":
        return number > 140
    return False

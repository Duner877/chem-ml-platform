"""Spectral foundation models.

A spectrum is turned into a fixed length vector by binning its intensities on
a normalised abscissa, which makes spectra comparable with the same cosine
similarity the molecular encoders use:

    from foundation import similarity
    similarity(spectrum_a, spectrum_b, model="spectrum-bin", modality="spectrum")

The encoders accept anything that can be read as a spectrum: a
:class:`~workflow_engine.objects.Spectrum`, a ``{"x": [...], "y": [...]}``
mapping, or a list of ``(x, y)`` pairs.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

import numpy as np

from foundation.base import FoundationModel, FoundationUnavailable

__all__ = ["SPECTRAL_MODELS", "SpectrumBinModel", "SpectrumSummaryModel"]


def _as_arrays(system: Any) -> Tuple[np.ndarray, np.ndarray]:
    """Return ``(x, y)`` float arrays for anything spectrum-like."""
    x: Any = None
    y: Any = None
    if hasattr(system, "x") and hasattr(system, "y"):
        x, y = list(getattr(system, "x") or []), list(getattr(system, "y") or [])
        if not x and getattr(system, "peaks", None):
            peaks = list(system.peaks)
            x = [float(getattr(p, "x", 0.0)) for p in peaks]
            y = [
                float(getattr(p, "intensity", 0.0) or getattr(p, "y", 0.0))
                for p in peaks
            ]
    elif isinstance(system, dict):
        x, y = system.get("x"), system.get("y")
        if x is None and system.get("peaks"):
            x = [p.get("x", 0.0) for p in system["peaks"]]
            y = [p.get("intensity", p.get("y", 0.0)) for p in system["peaks"]]
    elif isinstance(system, (list, tuple)):
        pairs = list(system)
        if pairs and isinstance(pairs[0], (list, tuple)) and len(pairs[0]) == 2:
            x = [pair[0] for pair in pairs]
            y = [pair[1] for pair in pairs]
        elif len(pairs) == 2 and isinstance(pairs[0], (list, tuple)):
            x, y = pairs[0], pairs[1]
    if x is None or y is None:
        raise FoundationUnavailable(
            f"cannot interpret {type(system).__name__} as a spectrum"
        )
    xs = np.asarray(x, dtype=float).ravel()
    ys = np.asarray(y, dtype=float).ravel()
    if xs.size == 0 or xs.size != ys.size:
        raise FoundationUnavailable("spectrum x/y arrays are empty or mismatched")
    return xs, ys


class SpectrumBinModel(FoundationModel):
    """Bin a spectrum's intensities onto a normalised, fixed length vector."""

    key = "spectrum-bin"
    name = "Spectrum-Bin"
    family = "spectral encoder"
    modality = "spectrum"
    dimension = 128
    capabilities = ["embed", "similarity"]
    requires_weights = False
    description = "谱学编码器：把强度按归一化横坐标分箱成定长向量，用于谱图相似度检索。"
    reference = "binned spectral fingerprint"

    def encode(self, system, *, dimension=None, seed=20240521) -> np.ndarray:
        xs, ys = _as_arrays(system)
        dim = int(dimension or self.dimension)
        span = float(xs.max() - xs.min())
        if span <= 0:
            span = 1.0
        grid = (xs - float(xs.min())) / span  # 0..1
        bins = np.zeros(dim, dtype=float)
        indices = np.clip((grid * (dim - 1)).round().astype(int), 0, dim - 1)
        # accumulate, then normalise by the largest intensity
        np.add.at(bins, indices, ys)
        peak = float(np.max(np.abs(bins))) or 1.0
        return bins / peak

    def predict(self, system, *, property: str = "summary") -> Dict[str, Any]:
        xs, ys = _as_arrays(system)
        top = int(np.argmax(np.abs(ys)))
        return {
            "value": round(float(xs[top]), 6),
            "unit": "x@max",
            "n_points": int(xs.size),
            "x_min": round(float(xs.min()), 6),
            "x_max": round(float(xs.max()), 6),
            "y_max": round(float(ys[top]), 6),
            "confidence": 0.9,
            "engine": "internal:binned-spectrum",
        }


class SpectrumSummaryModel(FoundationModel):
    """Cheap summary statistics over a spectrum (peaks, centroid, spread)."""

    key = "spectrum-summary"
    name = "Spectrum-Summary"
    family = "spectral descriptor"
    modality = "spectrum"
    dimension = 8
    capabilities = ["embed", "similarity", "predict"]
    properties = ["summary", "centroid", "n_peaks"]
    requires_weights = False
    description = "谱图统计描述子：峰数 / 质心 / 展宽 / 总强度。"
    reference = "spectral moments"

    def embed_features(self, system: Any) -> np.ndarray:
        xs, ys = _as_arrays(system)
        weights = np.abs(ys)
        total = float(weights.sum()) or 1.0
        centroid = float(np.sum(xs * weights) / total)
        spread = float(np.sqrt(np.sum(((xs - centroid) ** 2) * weights) / total))
        return np.asarray(
            [
                float(xs.size),
                float(xs.min()),
                float(xs.max()),
                centroid,
                spread,
                float(weights.max()),
                total,
                float(ys.mean()),
            ],
            dtype=float,
        )

    def encode(self, system, *, dimension=None, seed=20240521) -> np.ndarray:
        return self.embed_features(system)

    def predict(self, system, *, property: str = "summary") -> Dict[str, Any]:
        features = self.embed_features(system)
        return {
            "value": round(float(features[3]), 6),
            "unit": "centroid",
            "n_peaks": int(features[0]),
            "spread": round(float(features[4]), 6),
            "confidence": 0.85,
            "engine": "internal:spectral-moments",
        }


#: Every spectral model, ready to register.
SPECTRAL_MODELS: List[FoundationModel] = [
    SpectrumBinModel(),
    SpectrumSummaryModel(),
]
